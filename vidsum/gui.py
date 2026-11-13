"""Interfejs w przeglądarce: lokalny serwer (tylko 127.0.0.1) + kolejka analiz.

Bez zewnętrznych bibliotek (http.server ze standardowej biblioteki). Każde żądanie API wymaga
losowego tokenu z adresu strony — inne strony otwarte w przeglądarce nie mogą wywołać API.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import BRAND, __version__
from .llm import DEFAULT_TEXT_MODEL, ClaudeCode, LLMError, Ollama
from .pipeline import Options, analyze
from .tools import ToolError, find_tool


from .paths import app_dir, default_results_dir  # noqa: E402  (0.13.0: foldery „Vidsumly”, przeniesienie starych)


def web_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for p in (base / "vidsum" / "web", Path(__file__).resolve().parent / "web"):
        if p.is_dir():
            return p
    raise FileNotFoundError("Brak folderu web/")


# ---------------- kolejka zadań ----------------

class _Direct(Exception):
    """Odpowiedź czatu złożona bez modelu (moment z transkrypcji)."""

class Job:
    def __init__(self, jid: str, source: str, label: str, opt: Options, upload: Path | None):
        self.id, self.source, self.label, self.opt, self.upload = jid, source, label, opt, upload
        self.status = "w_kolejce"     # w_kolejce | trwa | gotowe | blad
        self.log: list[str] = []
        self.out: Path | None = None
        self.error: str | None = None
        self.created = time.time()
        self.started: float | None = None
        self.finished: float | None = None
        self.stage = ""                 # np. "2/4 kadry"
        self.stage_extra = ""           # po analizie: "tlumaczenie" (wynik już gotowy)
        self.partial: dict = {}         # gotowe etapy w trakcie analizy (podgląd): transkrypcja, napisy, kadry…
        self.settings: dict = {}        # ustawienia w chwili dodania (do zapisu kolejki i ponowienia)

    def card(self) -> dict:
        """Dane do karty w Bibliotece (z analiza.json, w pamięci podręcznej)."""
        if getattr(self, "_card", None) is not None or self.status != "gotowe" or not self.out:
            return getattr(self, "_card", None) or {}
        try:
            r = json.loads((self.out / "analiza.json").read_text(encoding="utf-8"))
        except Exception:
            self._card = {}
            return self._card
        d = ((r.get("streszczenie") or {}).get("dane") or {})
        z = r.get("zrodlo", {})
        self._card = {"tytul": d.get("tytul") or z.get("tytul") or z.get("plik"), "akcent": d.get("tytul_akcent", ""),
                      "teza": d.get("teza", ""), "typ": d.get("typ", ""), "dlugosc": z.get("dlugosc_s"),
                      "autor": z.get("autor"), "miniatura": (r.get("kadry") or [{}])[0].get("file"),
                      "czas_analizy": (r.get("czasy") or {}).get("razem_s"), "utworzono": r.get("utworzono")}
        return self._card

    def eta(self) -> float | None:
        """Prognoza czasu CAŁEJ analizy tego filmu (s) — gdy znamy już jego długość (0.12.0, vidsum/eta.py)."""
        dur = (self.partial.get("meta") or {}).get("dlugosc_s")
        if self.status != "trwa" or not dur:
            return None
        if getattr(self, "_eta", None) is None:
            try:
                from . import eta
                self._eta = eta.predict(self.opt.out_root, getattr(self.opt, "mode", "pelna"), float(dur))["razem_s"]
            except Exception:
                self._eta = 0.0
        return self._eta or None

    def to_dict(self) -> dict:
        end = self.finished or time.time()
        return {"id": self.id, "label": self.label, "status": self.status, "log": self.log[-400:], "eta_s": self.eta(),
                "tryb": getattr(self.opt, "mode", "pelna"),
                "error": self.error, "out": str(self.out) if self.out else None, "created": self.created,
                "stage": self.stage, "etap_po": self.stage_extra, "czesciowe": list(self.partial) if self.status == "trwa" else [],
                "elapsed": round(end - self.started, 1) if self.started else None, "card": self.card()}


class Worker:
    """Kolejka filmów: jeden wątek, zadania po kolei — dwa filmy naraz nie zmieściłyby się w 8 GB VRAM
    (modele mowy i obrazu na tej samej karcie), a ffmpeg i Whisper i tak biorą wszystkie rdzenie.

    0.11.0: kolejność, usuwanie, pauza/wznowienie, ponawianie, bez dubli, zapis do kolejka.json
    (po ponownym uruchomieniu kolejka wraca wstrzymana — wznawiasz ją sam)."""

    def __init__(self, state_file: Path | None = None, make_options=None, after=None):
        self.after = after                                  # po udanej analizie (np. tłumaczenie wyniku)
        self.jobs: dict[str, Job] = {}
        self.pending: list[Job] = []
        self.current: Job | None = None
        self.paused = False
        self.accepting = True
        self.cv = threading.Condition()
        self.lock = self.cv                                 # zgodność: dawny self.lock
        self.state_file = state_file
        self.make_options = make_options                    # ustawienia (słownik) → Options — przy odtwarzaniu kolejki
        self.restored = 0
        if state_file:
            self._restore()
        threading.Thread(target=self._loop, daemon=True).start()

    # --- operacje ---
    def find_duplicate(self, source: str) -> Job | None:
        key = _source_key(source)
        with self.cv:
            for j in ([self.current] if self.current else []) + self.pending:
                if _source_key(j.source) == key:
                    return j
        return None

    def submit(self, job: Job) -> Job:
        """Dodaje film na koniec kolejki. Ten sam film już czeka albo trwa → zwraca tamto zadanie (bez dubla)."""
        if not self.accepting:
            raise RuntimeError("Program się zamyka — nie przyjmuję nowych filmów.")
        dup = self.find_duplicate(job.source)
        if dup:
            return dup
        with self.cv:
            self.jobs[job.id] = job
            job.status = "w_kolejce"
            self.pending.append(job)
            self._save()
            self.cv.notify_all()
        return job

    def remove(self, jid: str) -> bool:
        """Usuwa oczekujący film z kolejki (trwającego nie — najpierw musiałby się skończyć)."""
        with self.cv:
            job = next((j for j in self.pending if j.id == jid), None)
            if not job:
                return False
            self.pending.remove(job)
            self.jobs.pop(jid, None)
            self._save()
        if job.upload:
            shutil.rmtree(job.upload.parent, ignore_errors=True)
        return True

    def move(self, jid: str, to: int) -> bool:
        """Zmienia miejsce oczekującego filmu (0 = następny)."""
        with self.cv:
            job = next((j for j in self.pending if j.id == jid), None)
            if not job:
                return False
            self.pending.remove(job)
            self.pending.insert(max(0, min(int(to), len(self.pending))), job)
            self._save()
        return True

    def retry(self, jid: str) -> Job | None:
        """Ponawia film zakończony błędem albo przerwany — wraca na koniec kolejki z tymi samymi ustawieniami."""
        with self.cv:
            job = self.jobs.get(jid)
            if not job or job.status not in ("blad", "przerwane"):
                return None
            if job.upload and not job.upload.exists():
                job.error = "Plik źródłowy już nie istnieje — dodaj film jeszcze raz."
                return None
            job.status, job.error, job.log, job.partial = "w_kolejce", None, [], {}
            job.started = job.finished = None
            job.stage, job.out = "", None
            self.pending.append(job)
            self._save()
            self.cv.notify_all()
        return job

    def set_paused(self, paused: bool) -> None:
        with self.cv:
            self.paused = bool(paused)
            self._save()
            self.cv.notify_all()

    def state(self) -> dict:
        with self.cv:
            return {"wstrzymana": self.paused, "trwa": self.current.id if self.current else None,
                    "oczekuje": [j.id for j in self.pending], "odtworzone": self.restored}

    def stop_for_exit(self) -> Job | None:
        """Zamykanie programu: nie przyjmuj nowych, zapisz kolejkę razem z trwającym filmem (wróci jako pierwszy)."""
        with self.cv:
            self.accepting = False
            cur = self.current
            self._save(include_current=True)
            return cur

    # --- zapis / odczyt ---
    def _save(self, include_current: bool = False) -> None:
        if not self.state_file:
            return
        items = ([self.current] if include_current and self.current else []) + self.pending
        data = {"wersja": 1, "wstrzymana": self.paused or (include_current and bool(self.current)),
                "zadania": [{"id": j.id, "zrodlo": j.source, "nazwa": j.label,
                             "wyslany": str(j.upload) if j.upload else None, "ustawienia": j.settings,
                             "przerwane": j is self.current} for j in items]}
        try:
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.state_file)               # zapis atomowy — przerwany zapis nie psuje kolejki
        except OSError:
            pass

    def _restore(self) -> None:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return
        for it in data.get("zadania") or []:
            up = Path(it["wyslany"]) if it.get("wyslany") else None
            if up and not up.exists():
                continue                                    # wysłany plik zniknął — nie ma czego analizować
            sett = it.get("ustawienia") or {}
            opt = self.make_options(sett) if (self.make_options and sett) else Options()
            if up:
                opt.move_source = True
            job = Job(it.get("id") or secrets.token_hex(4), it["zrodlo"], it.get("nazwa") or it["zrodlo"], opt, up)
            job.settings = sett
            if it.get("przerwane"):
                job.log = ["↻ Analiza została przerwana przy zamykaniu programu — zacznie się od nowa po wznowieniu."]
            self.jobs[job.id] = job
            self.pending.append(job)
        self.restored = len(self.pending)
        self.paused = bool(self.pending) and bool(data.get("wstrzymana", True) or self.restored)

    # --- wątek ---
    def _loop(self) -> None:
        while True:
            with self.cv:
                while self.paused or not self.pending or not self.accepting:
                    self.cv.wait()
                job = self.pending.pop(0)
                self.current = job
                job.status = "trwa"
                job.started = time.time()
                self._save(include_current=False)
            job.opt.on_partial = job.partial.__setitem__

            def log(msg: str, job=job) -> None:
                for line in str(msg).splitlines():
                    job.log.append(line)
                    if line.strip().startswith("wyniki:"):
                        job.out = Path(line.split("wyniki:", 1)[1].strip())
                    m = re.match(r"\s*\[(\d)/4\]\s*(\S+)", line)
                    if m and int(m.group(1)) > int(job.stage or 0):     # etap tylko do przodu ([0/4] OCR, druga [1/4])
                        job.stage = m.group(1)
            try:
                job.out = analyze(job.source, job.opt, log)
                job.status = "gotowe"
                with self.cv:
                    self.current = None                     # film gotowy — przy zamykaniu nie wraca do kolejki
                if self.after and self.accepting:
                    try:
                        self.after(job)
                    except Exception:
                        traceback.print_exc()
            except Exception as e:  # pokaż błąd w interfejsie, nie zabijaj serwera
                if not self.accepting:
                    job.status, job.error = "przerwane", "przerwane przy zamykaniu programu"
                else:
                    job.status, job.error = "blad", f"{type(e).__name__}: {e}"
                    job.log.append("✖ " + job.error)
                    traceback.print_exc()
            finally:
                job.finished = time.time()
                with self.cv:
                    self.current = None
                    if self.accepting:
                        self._save()
                if job.upload and job.status == "gotowe":
                    shutil.rmtree(job.upload.parent, ignore_errors=True)


def _source_key(src: str) -> str:
    """Klucz do wykrywania dubli w kolejce: link bez śledzących parametrów, ścieżka znormalizowana."""
    s = str(src).strip().strip('"')
    if re.match(r"https?://", s, re.I):
        u = urllib.parse.urlsplit(s)
        qs = [(k, v) for k, v in urllib.parse.parse_qsl(u.query) if k in ("v", "list")]
        return f"{u.netloc.lower().removeprefix('www.')}{u.path.rstrip('/')}?{urllib.parse.urlencode(qs)}"
    try:
        return str(Path(s).resolve()).lower() if os.name == "nt" else str(Path(s).resolve())
    except OSError:
        return s


# ---------------- serwer HTTP ----------------
class App:
    def __init__(self, results: Path, token: str):
        self.results = results
        self.token = token
        self.settings_file = app_dir() / "ustawienia.json"
        self.settings = self._load_settings()
        self.translations: dict = {}          # (id zadania, język) → {"stan", "postep", "error"} — tłumaczenie całości
        self._tr_lock = threading.Lock()
        self.worker = Worker(app_dir() / "kolejka.json", self.options, self.after_analysis)
        self.cleanup_uploads()
        self.scan_library()

    def cleanup_uploads(self, max_age_s: float = 24 * 3600) -> int:
        """Wysłane filmy, których nie ma już w kolejce (np. po błędzie, który nie został ponowiony), starsze niż doba —
        usuwane przy starcie. Pliki w kolejce zostają (ponowienie / odtworzenie kolejki)."""
        root = app_dir() / "wyslane"
        keep = {j.upload.parent.resolve() for j in self.worker.jobs.values() if j.upload}
        n = 0
        for d in root.glob("*") if root.is_dir() else []:
            try:
                if d.is_dir() and d.resolve() not in keep and time.time() - d.stat().st_mtime > max_age_s:
                    shutil.rmtree(d, ignore_errors=True)
                    n += 1
            except OSError:
                pass
        return n

    def scan_library(self) -> None:
        """Biblioteka: wcześniejsze analizy z dysku (przetrwają ponowne uruchomienie programu)."""
        roots = {Path(self.settings.get("wyniki") or self.results), self.results}
        known = {j.out.resolve() for j in self.worker.jobs.values() if j.out}
        for root in roots:
            if not root.is_dir():
                continue
            for f in root.glob("*/analiza.json"):
                d = f.parent.resolve()
                if d in known:
                    continue
                jid = hashlib.sha1(str(d).encode("utf-8")).hexdigest()[:8]
                job = Job(jid, str(d), d.name, Options(), None)
                job.status, job.out, job.created = "gotowe", d, f.stat().st_mtime
                try:
                    c = json.loads(f.read_text(encoding="utf-8")).get("czasy", {})
                    job.started, job.finished = 0.0, float(c.get("razem_s") or 0.0)
                except Exception:
                    pass
                job.label = job.card().get("tytul") or d.name
                self.worker.jobs[jid] = job
    def _load_settings(self) -> dict:
        d = {"jezyk_ui": "pl", "jezyk": "auto", "whisper": "large-v3-turbo", "ocr": True, "obraz": "ollama", "model_obrazu": "qwen3-vl:4b-instruct",
             "streszczenie": "auto", "model_tekstowy": DEFAULT_TEXT_MODEL, "tlumaczenia": "pl,en", "gpu_pobieranie": True,
             "max_kadrow": None, "ciasteczka_z": "", "wyniki": str(self.results),
             "podglad": False, "tlumacz_wynik": True, "tryb_podgladu": "zawsze", "tryb": "pelna"}
        try:
            saved = json.loads(self.settings_file.read_text(encoding="utf-8"))
            if saved.get("wersja_ustawien", 0) < 2 and saved.get("whisper") == "small":
                saved["whisper"] = "large-v3-turbo"    # 0.4: dokładniejszy model jako domyślny
            d.update(saved)
        except Exception:
            pass
        d["wersja_ustawien"] = 2
        return d

    def save_settings(self, new: dict) -> dict:
        allowed = set(self._load_settings())
        self.settings.update({k: v for k, v in new.items() if k in allowed})
        self.settings_file.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.settings

    def models_needed(self) -> list[str]:
        """Modele Ollamy potrzebne przy obecnych ustawieniach (obraz + tekst; bez wyłączonych)."""
        s = self.settings
        out = []
        if s.get("obraz", "ollama") == "ollama":
            out.append(s.get("model_obrazu") or "qwen3-vl:4b-instruct")
        if s.get("streszczenie", "auto") in ("auto", "ollama"):
            out.append(s.get("model_tekstowy") or DEFAULT_TEXT_MODEL)
        return list(dict.fromkeys(out))

    def job_settings(self, preview: str | None, mode: str | None = None) -> dict:
        """Ustawienia dla nowego filmu. 0.11.5: tryb wstępnego streszczenia wybiera się przy dodawaniu filmu
        („najszybciej” / „ze wstępnym”); 0.12.0: tak samo tryb analizy (pełna / tylko mowa / mowa + szybki obraz).
        Wybór zapisuje się jako domyślny dla następnych."""
        from .modes import MODES
        new = {}
        if preview in ("zawsze", "najszybciej") and preview != self.settings.get("tryb_podgladu"):
            new["tryb_podgladu"] = preview
        if mode in MODES and mode != self.settings.get("tryb"):
            new["tryb"] = mode
        if new:
            self.save_settings(new)
        return dict(self.settings)

    def options(self, s: dict) -> Options:
        mk = s.get("max_kadrow")
        from .languages import parse_list
        try:
            tl = parse_list(s.get("tlumaczenia", "pl,en"))
        except ValueError:
            tl = ["pl", "en"]
        return Options(out_root=Path(s.get("wyniki") or self.results),
                       language=None if s.get("jezyk") in (None, "", "auto") else s["jezyk"],
                       whisper_model=s.get("whisper") or "large-v3-turbo", ocr=bool(s.get("ocr", True)),
                       whisper_root=str(app_dir() / "modele"),
                       vision=s.get("obraz", "ollama"), vision_model=s.get("model_obrazu") or "qwen3-vl:4b-instruct",
                       summary=s.get("streszczenie") or "auto", max_frames=int(mk) if mk else None,
                       text_model=s.get("model_tekstowy") or DEFAULT_TEXT_MODEL, translate=tl,
                       cuda_download=bool(s.get("gpu_pobieranie", True)),
                       cookies_from_browser=s.get("ciasteczka_z") or None,
                       # 0.11.4: „zawsze” = wstępne streszczenie po ~20 s (całość ~1:28 na Twojej karcie, bo modele mowy/obrazu
                       # i tekstu nie mieszczą się naraz w 8 GB); „najszybciej” = tylko gdy nic nie kosztuje (całość ~1:15)
                       preview=None if s.get("tryb_podgladu") == "najszybciej" else True,
                       mode=s.get("tryb") or "pelna")

    def translate_result(self, p: Path, lang: str, st: dict | None = None) -> dict:
        """Tłumaczy wynik (analiza.json) na `lang`: tylko teksty nowe albo zmienione od poprzedniego tłumaczenia
        (pamięć oryginał → tłumaczenie), zapis z odciskiem oryginału. Oryginał zostaje źródłem prawdy."""
        from .translate_all import translate_analysis
        st = st if st is not None else {}
        st.update(stan="trwa", postep="start")
        try:
            eng = Ollama(self.settings.get("model_tekstowy") or DEFAULT_TEXT_MODEL)
            eng.ensure(lambda m: None)
            r = json.loads(p.read_text(encoding="utf-8"))
            old = ((r.get("tlumaczenie_calosci") or {}).get(lang) or {}).get("pamiec") or {}
            res = translate_analysis(eng, r, lang, progress=lambda m: st.update(postep=m), cache=old)
            with self._tr_lock:                       # zapis do analiza.json (bez gubienia innych zmian)
                r = json.loads(p.read_text(encoding="utf-8"))
                r.setdefault("tlumaczenie_calosci", {})[lang] = res
                p.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
            st.update(stan="gotowe", postep="", nieprzetlumaczone=res["nieprzetlumaczone"], czas_s=res["czas_s"])
        except Exception as e:                        # Ollama nie działa itp.
            st.update(stan="blad", error=str(e)[:300])
        return st

    def after_analysis(self, job: "Job") -> None:
        """Po streszczeniu (w wątku kolejki, zanim ruszy następny film — karta graficzna po kolei): tłumaczenie wyniku
        na drugi język programu (PL ↔ EN), gdy włączone w Ustawieniach. Wynik jest już widoczny; to dochodzi w tle."""
        if not self.settings.get("tlumacz_wynik", True) or not job.out:
            return
        p = job.out / "analiza.json"
        if not p.is_file():
            return
        from .translate_all import is_current
        r = json.loads(p.read_text(encoding="utf-8"))
        if (r.get("streszczenie") or {}).get("silnik") in (None, "brak"):
            return                                    # bez streszczenia nie ma czego tłumaczyć
        lang = "en"                                   # streszczenie powstaje po polsku → druga wersja: angielska
        if is_current(r, lang):
            return
        job.stage_extra = "tlumaczenie"
        st = self.translations[(job.id, lang)] = {"stan": "trwa", "postep": "start", "auto": True}
        self.translate_result(p, lang, st)
        job.stage_extra = ""

    def shutdown(self, reason: str = "") -> dict:
        """Porządne zamknięcie (0.11.0), w tej kolejności:
        1) nie przyjmuj nowych filmów, 2) zapisz kolejkę razem z trwającym filmem (po starcie wróci, wstrzymana),
        3) zakończ własne procesy potomne (ffmpeg/ffprobe), 4) zwolnij z karty modele, których używała przerwana
        analiza — samą Ollamę zostawiamy (to usługa użytkownika, nie nasz proces). Serwer zamyka wołający."""
        from . import procs
        procs.closing.set()
        cur = self.worker.stop_for_exit()
        killed = procs.kill_all()
        unloaded = []
        models = set()
        if cur is not None:
            if cur.opt.vision == "ollama":
                models.add(cur.opt.vision_model)
            if cur.opt.summary in ("auto", "ollama"):
                models.add(cur.opt.summary_model or cur.opt.text_model)
        for m in models:
            try:
                Ollama(m, cur.opt.ollama_host, timeout=3).unload()
                unloaded.append(m)
            except Exception:
                pass
        info = {"powod": reason, "przerwany_film": cur.label if cur else None, "zakonczone_procesy": killed,
                "zwolnione_modele": unloaded, "czas": time.strftime("%Y-%m-%d %H:%M:%S")}
        try:
            (app_dir() / "zamkniecie.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
        return info

    def status(self) -> dict:
        st: dict = {"wersja": __version__}
        try:
            from .update import can_swap_code, token_get
            st["klucz_github"] = bool(token_get())
            st["aktualizacja_kodu"] = can_swap_code()
        except Exception:
            st["klucz_github"] = False
        # „Silnik wideo” w interfejsie = ffmpeg + ffprobe (wycinanie dźwięku i kadrów, odczyt formatu filmu)
        try:
            ff = find_tool("ffmpeg")
            find_tool("ffprobe")
            st["ffmpeg"], st["ffmpeg_sciezka"] = True, str(ff)
            st["ffmpeg_wersja"] = _ffmpeg_version(str(ff))
        except ToolError:
            st["ffmpeg"] = False
        st["folder_danych"] = str(app_dir())
        model = self.settings.get("model_obrazu") or "qwen3-vl:4b-instruct"
        try:
            Ollama(model).check()
            st["ollama"], st["ollama_info"] = True, model
        except LLMError as e:
            st["ollama"], st["ollama_info"] = False, str(e)
        tm = self.settings.get("model_tekstowy") or DEFAULT_TEXT_MODEL
        try:
            st["model_tekstowy"], st["model_tekstowy_pobrany"] = tm, Ollama(tm).has_model()
        except LLMError:
            st["model_tekstowy"], st["model_tekstowy_pobrany"] = tm, False
        from . import cuda
        st["gpu_nvidia"], st["cuda_pobrana"] = cuda.gpu_count() > 0, cuda.installed()
        # 0.12.0: profil sprzętu — jaka karta i jaki tryb analizy ma na niej sens (propozycja; wybór należy do użytkownika)
        try:
            from .modes import suggest_mode
            snap = cuda.gpu_snapshot_name() if st["gpu_nvidia"] else None
            st["karta"], st["karta_pamiec_mb"] = (snap or (None, None))
            st["tryb_proponowany"], st["tryb_powod"] = suggest_mode(0, st["karta_pamiec_mb"])
        except Exception:
            st["karta"], st["karta_pamiec_mb"], st["tryb_proponowany"], st["tryb_powod"] = None, None, "pelna", ""
        try:
            ClaudeCode().check()
            st["claude"], st["claude_info"] = True, "Claude Code"
        except LLMError as e:
            st["claude"], st["claude_info"] = False, str(e)
        return st


_FF_VER: dict = {}


def _ffmpeg_version(exe: str) -> str:
    """Pierwsza linia `ffmpeg -version` (np. „7.1”), raz na uruchomienie programu."""
    if exe not in _FF_VER:
        try:
            from .tools import run
            line = run([exe, "-version"], check=False, timeout=10).stdout_text.splitlines()[0]
            m = re.search(r"version\s+(\S+)", line)
            _FF_VER[exe] = m.group(1) if m else line[:40]
        except Exception:
            _FF_VER[exe] = ""
    return _FF_VER[exe]


_SAFE_UPLOAD = re.compile(r"[^\w.\- ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")


def make_handler(app: App):
    web = web_dir()

    class H(BaseHTTPRequestHandler):
        server_version = f"Vidsumly/{__version__}"

        def log_message(self, *a):  # cicho w konsoli
            pass

        # --- pomocnicze ---
        def _json(self, obj, code=200):
            b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b)

        def _file(self, p: Path):
            if not p.is_file():
                return self._json({"error": "nie znaleziono"}, 404)
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/json", "application/javascript"):
                ctype += "; charset=utf-8"
            data = p.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authed(self, qs: dict) -> bool:
            tok = self.headers.get("X-Token") or (qs.get("t") or [""])[0]
            if not secrets.compare_digest(tok, app.token):
                self._json({"error": "brak tokenu"}, 403)
                return False
            return True

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

        def _job_file(self, jid: str, rel: str) -> Path | None:
            job = app.worker.jobs.get(jid)
            if not job or not job.out:
                return None
            root = job.out.resolve()
            p = (root / rel).resolve()
            return p if p.is_relative_to(root) else None   # bez wychodzenia poza folder wyników

        def _video(self, jid: str):
            """Film do odtwarzacza, z obsługą Range (przewijanie w <video>)."""
            p = self._job_file(jid, "analiza.json")
            if not p or not p.is_file():
                return self._json({"error": "brak"}, 404)
            ref = json.loads(p.read_text(encoding="utf-8")).get("zrodlo", {}).get("film")
            if not ref:
                return self._json({"error": "brak filmu"}, 404)
            f = Path(ref) if Path(ref).is_absolute() else p.parent / ref
            if not f.is_file():
                return self._json({"error": "film przeniesiony lub usunięty"}, 404)
            size = f.stat().st_size
            ctype = mimetypes.guess_type(f.name)[0] or "video/mp4"
            rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
            start, end = 0, size - 1
            if rng and (rng.group(1) or rng.group(2)):
                if rng.group(1):
                    start = int(rng.group(1))
                    end = int(rng.group(2)) if rng.group(2) else size - 1
                else:
                    start = max(0, size - int(rng.group(2)))
                end = min(end, size - 1)
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            with open(f, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                try:
                    while left > 0:
                        chunk = fh.read(min(1 << 20, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass            # przeglądarka przerwała (przewinięcie) — normalne

        def _ask(self, jid: str, question: str):
            p = self._job_file(jid, "analiza.json")
            if not p or not p.is_file():
                return self._json({"error": "brak wyników"}, 404)
            if not question:
                return self._json({"error": "puste pytanie"}, 400)
            from .summary import build_chat_prompt
            analysis = json.loads(p.read_text(encoding="utf-8"))
            hist_file = p.parent / "czat.json"
            history = json.loads(hist_file.read_text(encoding="utf-8")) if hist_file.is_file() else []
            prompt = build_chat_prompt(analysis, question, history)
            from .summary import answer_moment
            direct = answer_moment(analysis, question)      # „co robi w 0:47?” — z transkrypcji, bez modelu (0.11.8)
            try:
                if direct:
                    raise _Direct(direct)
                # samodzielnie: lokalny model tekstowy; Claude tylko gdy użytkownik wybrał go w ustawieniach
                if app.settings.get("streszczenie") == "claude":
                    eng, silnik = ClaudeCode(), "claude-code"
                else:
                    eng = Ollama(app.settings.get("model_tekstowy") or DEFAULT_TEXT_MODEL)
                    eng.ensure(lambda m: None)
                    silnik = f"ollama:{eng.model}"
                from .summary import check_chat_answer
                answer = check_chat_answer(eng.complete(prompt).strip(), analysis)
            except _Direct as d:
                answer, silnik = str(d), "transkrypcja"
            except Exception as e:
                return self._json({"error": f"Nie udało się odpowiedzieć: {e}"}, 400)
            now = time.strftime("%Y-%m-%dT%H:%M:%S")
            history += [{"rola": "user", "tekst": question, "czas": now},
                        {"rola": "asystent", "tekst": answer, "czas": now, "silnik": silnik}]
            hist_file.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")
            return self._json({"odpowiedz": answer, "historia": history})

        def _comments(self, jid: str, fetch: bool):
            """Komentarze widzów (0.10.0) — tylko dla linków, na żądanie; zapis w komentarze.json.
            GET = zapisane (albo pusto), POST = pobierz przez yt-dlp (bez pobierania filmu)."""
            p = self._job_file(jid, "analiza.json")
            if not p or not p.is_file():
                return self._json({"error": "brak wyników"}, 404)
            cache = p.parent / "komentarze.json"
            if cache.is_file() and not fetch:
                return self._json(json.loads(cache.read_text(encoding="utf-8")))
            z = json.loads(p.read_text(encoding="utf-8")).get("zrodlo") or {}
            url = z.get("url") if z.get("rodzaj") == "link" else None
            if not fetch:
                return self._json({"stan": "brak", "dostepne": bool(url)})
            if not url:
                return self._json({"error": "komentarze są tylko dla filmów z linku"}, 400)
            from .fetch import fetch_comments
            try:
                items = fetch_comments(url, cookies_from_browser=app.settings.get("ciasteczka_z") or None)
            except Exception as e:
                return self._json({"error": f"nie udało się pobrać komentarzy: {str(e)[:300]}"}, 400)
            out = {"stan": "gotowe", "dostepne": True, "url": url, "pobrano": time.strftime("%Y-%m-%d %H:%M"),
                   "komentarze": items}
            cache.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            return self._json(out)

        def _translate_all(self, jid: str, lang: str, start: bool):
            """Tłumaczenie całej analizy w tle; GET = stan, POST = start (gdy brak albo nieaktualne i nie trwa)."""
            from .translate_all import LANGS, is_current
            p = self._job_file(jid, "analiza.json")
            if not p or not p.is_file():
                return self._json({"error": "brak wyników"}, 404)
            if lang not in LANGS:
                return self._json({"error": "obsługiwane języki: pl, en"}, 400)
            key = (jid, lang)
            with app._tr_lock:
                st = app.translations.get(key)
                done = is_current(json.loads(p.read_text(encoding="utf-8")), lang)
                if done and not (st and st["stan"] == "trwa"):
                    return self._json({"stan": "gotowe"})
                if not start or (st and st["stan"] == "trwa"):
                    return self._json(st or {"stan": "nieaktualne" if not done and lang in (json.loads(
                        p.read_text(encoding="utf-8")).get("tlumaczenie_calosci") or {}) else "brak"})
                st = app.translations[key] = {"stan": "trwa", "postep": "start"}
            threading.Thread(target=app.translate_result, args=(p, lang, st), daemon=True).start()
            return self._json(st, 202)

        # --- GET ---
        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(u.query)
            if u.path in ("/", "/index.html"):
                return self._file(web / "index.html")
            if u.path in ("/favicon.ico", "/icon.svg"):       # ikona programu (bez tokenu — to tylko obrazek)
                return self._file(web / ("vidsum.ico" if u.path.endswith(".ico") else "icon.svg"))
            if not self._authed(qs):
                return
            if u.path == "/api/status":
                return self._json(app.status())
            if u.path == "/api/aktualizacja":
                from .update import UpdateError, check
                try:
                    app.update_info = check()
                except UpdateError as e:
                    return self._json({"error": str(e)}, 400)
                return self._json({k: v for k, v in app.update_info.items() if not k.startswith("_")})
            if u.path == "/api/ustawienia":
                return self._json(app.settings)
            if u.path == "/api/ollama":                  # 0.12.0: pierwsze uruchomienie bez PowerShella
                from . import ollama_setup
                return self._json(ollama_setup.state(app.models_needed()))
            if u.path == "/api/kolejka":
                return self._json(app.worker.state())
            if u.path == "/api/zadania":
                if qs.get("skanuj"):
                    app.scan_library()
                jobs = sorted(app.worker.jobs.values(), key=lambda j: -j.created)
                return self._json([j.to_dict() for j in jobs])
            m = re.fullmatch(r"/api/zadania/(\w+)/film", u.path)
            if m:
                return self._video(m.group(1))
            m = re.fullmatch(r"/api/zadania/(\w+)/czesciowe", u.path)
            if m:
                job = app.worker.jobs.get(m.group(1))
                return self._json(job.partial if job else {}, 200 if job else 404)
            m = re.fullmatch(r"/api/zadania/(\w+)/tlumacz", u.path)
            if m:
                return self._translate_all(m.group(1), (qs.get("jezyk") or [""])[0], start=False)
            m = re.fullmatch(r"/api/zadania/(\w+)/komentarze", u.path)
            if m:
                return self._comments(m.group(1), fetch=False)
            m = re.fullmatch(r"/api/zadania/(\w+)/czat", u.path)
            if m:
                p = self._job_file(m.group(1), "czat.json")
                return self._json(json.loads(p.read_text(encoding="utf-8")) if p and p.is_file() else [])
            m = re.fullmatch(r"/api/zadania/(\w+)/notatka", u.path)
            if m:
                p = self._job_file(m.group(1), "raport.md")
                if not p or not p.is_file():
                    return self._json({"error": "nie znaleziono"}, 404)
                from .note import note_text
                b = note_text(p.read_text(encoding="utf-8")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Cache-Control", "no-store")
                if qs.get("pobierz"):
                    self.send_header("Content-Disposition", "attachment; filename*=UTF-8''notatka.md")
                self.end_headers()
                self.wfile.write(b)
                return
            m = re.fullmatch(r"/api/zadania/(\w+)/plik/(.+)", u.path)
            if m:
                p = self._job_file(m.group(1), urllib.parse.unquote(m.group(2)))
                return self._file(p) if p else self._json({"error": "nie znaleziono"}, 404)
            return self._json({"error": "nie znaleziono"}, 404)

        # --- POST ---
        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(u.query)
            if not self._authed(qs):
                return
            if u.path == "/api/ustawienia":
                return self._json(app.save_settings(self._body()))
            if u.path == "/api/ollama":
                from . import ollama_setup as osu
                act = str(self._body().get("akcja") or "")
                jobs = {"zainstaluj": ("instalacja", osu.install), "modele": ("modele", osu.pull, app.models_needed()),
                        "rownolegle": ("rownolegle", osu.enable_parallel),
                        "uruchom": ("uruchomienie", lambda task: (task.set(etap="Uruchamiam Ollamę…"), osu.start(),
                                                                  task.set(etap="Ollama działa.", procent=100)))}
                if act not in jobs:
                    return self._json({"error": "nieznana akcja"}, 400)
                if not osu.TASK.run(*jobs[act]):
                    return self._json({"error": "Poprzedni krok jeszcze trwa."}, 409)
                return self._json(osu.state(app.models_needed()))
            if u.path == "/api/przegladarka":            # z okna programu: to samo w zwykłej przeglądarce
                h = str(self._body().get("hash") or "")
                h = h if re.fullmatch(r"#/[\w/.-]*", h) else ""
                port = self.server.server_address[1]
                webbrowser.open(f"http://127.0.0.1:{port}/?t={app.token}{h}")
                return self._json({"ok": True})
            if u.path == "/api/aktualizacja/klucz":
                from .update import UpdateError, token_delete, token_set
                body = self._body()
                try:
                    if body.get("usun"):
                        token_delete()
                    else:
                        token_set(str(body.get("klucz") or ""))
                except UpdateError as e:
                    return self._json({"error": str(e)}, 400)
                return self._json({"ok": True})
            if u.path == "/api/aktualizacja":
                from .update import UpdateError, apply, restart_ui
                if any(j.status == "trwa" for j in app.worker.jobs.values()):
                    return self._json({"error": "Trwa analiza — zaktualizuj po jej zakończeniu."}, 409)
                info = getattr(app, "update_info", None)
                if not info or not info.get("jest_nowsza") or not info.get("rodzaj"):
                    return self._json({"error": "Najpierw sprawdź aktualizacje."}, 400)
                try:
                    kind = apply(info, log=lambda m: None)
                except UpdateError as e:
                    return self._json({"error": str(e)}, 400)
                self._json({"ok": True, "rodzaj": kind, "wersja": info["najnowsza"]})
                if kind == "kod":                      # nowy kod na miejscu — uruchom ponownie
                    restart_ui()
                    threading.Timer(0.5, lambda: os._exit(0)).start()
                return
            if u.path == "/api/otworz-wyniki":
                p = Path(app.settings.get("wyniki") or app.results)
                p.mkdir(parents=True, exist_ok=True)
                try:
                    if os.name == "nt":
                        os.startfile(str(p))  # type: ignore[attr-defined]
                    else:
                        subprocess.Popen(["xdg-open", str(p)])
                except OSError as e:
                    return self._json({"error": f"nie udało się otworzyć folderu: {e}"}, 400)
                return self._json({"ok": True})
            if u.path == "/api/zakoncz":
                # zamknięcie z interfejsu (Ustawienia → Zamknij program) albo przez nowszą wersję
                info = app.shutdown("przycisk")
                self._json({"ok": True, **info})
                threading.Timer(0.3, lambda: os._exit(0)).start()
                return
            if u.path == "/api/wyslij":
                # surowe bajty pliku w treści żądania (strumieniowo na dysk — filmy 40 min mają setki MB)
                name = urllib.parse.unquote(self.headers.get("X-Filename") or "film.mp4")
                name = _SAFE_UPLOAD.sub("_", Path(name).name)[:120] or "film.mp4"
                n = int(self.headers.get("Content-Length") or 0)
                d = app_dir() / "wyslane" / secrets.token_hex(6)
                d.mkdir(parents=True, exist_ok=True)
                dst = d / name
                with open(dst, "wb") as f:
                    left = n
                    while left > 0:
                        chunk = self.rfile.read(min(1 << 20, left))
                        if not chunk:
                            break
                        f.write(chunk)
                        left -= len(chunk)
                sett = app.job_settings(self.headers.get("X-Preview"), self.headers.get("X-Mode"))
                opt = app.options(sett)
                opt.move_source = True          # film zostaje w folderze wyników — do odtwarzacza
                job = Job(secrets.token_hex(4), str(dst), name, opt, dst)
                job.settings = sett
                try:
                    job = app.worker.submit(job)
                except RuntimeError as e:
                    return self._json({"error": str(e)}, 409)
                return self._json(job.to_dict())
            if u.path == "/api/link":
                b = self._body()
                src = (b.get("zrodlo") or "").strip().strip('"')
                if not src:
                    return self._json({"error": "pusty link"}, 400)
                sett = app.job_settings(b.get("tryb_podgladu"), b.get("tryb"))
                job = Job(secrets.token_hex(4), src, src, app.options(sett), None)
                job.settings = sett
                try:
                    dup = app.worker.find_duplicate(src)
                    job = app.worker.submit(job)
                except RuntimeError as e:
                    return self._json({"error": str(e)}, 409)
                return self._json({**job.to_dict(), "duplikat": bool(dup)})
            if u.path == "/api/kolejka":
                b = self._body()
                act, jid = b.get("akcja"), str(b.get("id") or "")
                w = app.worker
                if act in ("pauza", "wznow"):
                    w.set_paused(act == "pauza")
                elif act == "usun":
                    if not w.remove(jid):
                        return self._json({"error": "tego filmu nie ma w oczekujących"}, 400)
                elif act == "przesun":
                    if not w.move(jid, b.get("pozycja", 0)):
                        return self._json({"error": "tego filmu nie ma w oczekujących"}, 400)
                elif act == "ponow":
                    if not w.retry(jid):
                        j = w.jobs.get(jid)
                        return self._json({"error": (j.error if j else None) or "nie można ponowić"}, 400)
                else:
                    return self._json({"error": "nieznana akcja"}, 400)
                return self._json(w.state())
            m = re.fullmatch(r"/api/zadania/(\w+)/tlumacz", u.path)
            if m:
                return self._translate_all(m.group(1), str(self._body().get("jezyk") or ""), start=True)
            m = re.fullmatch(r"/api/zadania/(\w+)/komentarze", u.path)
            if m:
                return self._comments(m.group(1), fetch=True)
            m = re.fullmatch(r"/api/zadania/(\w+)/pytanie", u.path)
            if m:
                return self._ask(m.group(1), (self._body().get("pytanie") or "").strip())
            m = re.fullmatch(r"/api/zadania/(\w+)/claude", u.path)
            if m:
                job = app.worker.jobs.get(m.group(1))
                p = self._job_file(m.group(1), "prompt_dla_claude.md")
                if not job or not p:
                    return self._json({"error": "brak wyników"}, 404)
                try:
                    md = ClaudeCode().complete(p.read_text(encoding="utf-8"))
                except Exception as e:
                    return self._json({"error": str(e)}, 400)
                (p.parent / "streszczenie_claude.md").write_text(md, encoding="utf-8")
                return self._json({"markdown": md})
            m = re.fullmatch(r"/api/zadania/(\w+)/otworz", u.path)
            if m:
                p = self._job_file(m.group(1), ".")
                if not p:
                    return self._json({"error": "brak folderu"}, 404)
                if os.name == "nt":
                    os.startfile(str(p))  # type: ignore[attr-defined]
                else:
                    subprocess.Popen(["xdg-open", str(p)])
                return self._json({"ok": True})
            return self._json({"error": "nie znaleziono"}, 404)

    return H


DEFAULT_PORT = 8765


def _persistent_token() -> str:
    """Stały klucz (zapisany w %LOCALAPPDATA%\\Vidsumly) — zakładki i stare karty działają po restarcie programu."""
    f = app_dir() / "token.txt"
    try:
        tok = f.read_text(encoding="utf-8").strip()
        if len(tok) >= 16:
            return tok
    except OSError:
        pass
    tok = secrets.token_urlsafe(16)
    f.write_text(tok, encoding="utf-8")
    return tok


def _running_instance(port: int) -> bool:
    """Czy pod tym portem działa już Vidsumly (drugie uruchomienie → otwórz istniejący zamiast nowego)."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as r:
            head = r.read(4096)
            return any(n in head for n in (b"VidSum", b"Vidento", b"Vidsumly"))
    except Exception:
        return False


def _replace_older(port: int, token: str) -> bool:
    """Działa INNA wersja Vidsumly (np. stara po aktualizacji) i nic nie analizuje → zamknij ją, żeby otworzyła się ta.

    Na komputerze testowym „Vidsumly Start” z nowej wersji otwierał stronę starej, która dalej działała w tle."""
    import json as _json
    import urllib.request
    base = f"http://127.0.0.1:{port}"

    def get(path: str):
        req = urllib.request.Request(base + path, headers={"X-Token": token})
        with urllib.request.urlopen(req, timeout=20) as r:
            return _json.loads(r.read().decode("utf-8"))
    try:
        if get("/api/status").get("wersja") == __version__:
            return False
        if any(j.get("status") == "trwa" for j in get("/api/zadania")):
            print("Działa starsza wersja Vidsumly i właśnie analizuje — zostawiam ją (zamknij ją po analizie).")
            return False
        req = urllib.request.Request(base + "/api/zakoncz", data=b"{}", method="POST",
                                     headers={"X-Token": token, "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        return False
    for _ in range(50):                    # do 5 s na zwolnienie portu
        time.sleep(0.1)
        if not _running_instance(port):
            print("Zamknięto starszą wersję Vidsumly.")
            return True
    return False


def _edge_exe() -> str | None:
    """Edge jest w każdym Windows 10/11 — z niego robimy osobne okno programu."""
    if os.name != "nt":
        return None
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.exists():
                return str(p)
    return shutil.which("msedge")


def open_window(url: str) -> None:
    """Vidsumly we własnym oknie (bez kart i paska adresu, własna ikona na pasku zadań) — Edge w trybie aplikacji,
    z osobnym profilem i BEZ przyspieszania sprzętowego: okno nie zabiera pamięci karty modelom (pomiar: przeglądarki
    i inne programy brały ~850 MB karty i analiza trwała 3:40 zamiast ~1:40). Bez Edge / VIDSUM_PRZEGLADARKA=1 →
    domyślna przeglądarka, jak dotąd."""
    edge = None if os.environ.get("VIDSUM_PRZEGLADARKA") == "1" else _edge_exe()
    if not edge:
        webbrowser.open(url)
        return
    prof = app_dir() / "okno"
    args = [edge, f"--app={url}", f"--user-data-dir={prof}", "--disable-gpu", "--window-size=1400,900",
            "--no-first-run", "--no-default-browser-check"]
    try:
        from .procs import popen_detached
        popen_detached(args, close_fds=True)          # okno Edge nie należy do programu — nie znika z nim
    except OSError:
        webbrowser.open(url)


def fix_shortcut_icons() -> None:
    """Skróty z instalatora < 0.8.1 mają ikonę Pythona; aktualizacja samego kodu ich nie zmienia — poprawiamy je raz."""
    if os.name != "nt":
        return
    ico = Path(__file__).parent / "web" / "vidsum.ico"
    mark = app_dir() / "ikony_skrotow.txt"
    # znacznik = ścieżka + rozmiar ikony: nowa ikona (0.10.0) → skróty odświeżane jeszcze raz
    sig = f"{ico}|{ico.stat().st_size}" if ico.exists() else ""
    if not ico.exists() or (mark.exists() and mark.read_text(encoding="utf-8").strip() == sig):
        return
    ps = ("$s=New-Object -ComObject WScript.Shell;"
          "$p=@(\"$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\Vidsumly\\Vidsumly.lnk\","
          "\"$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\Vidento\\Vidento.lnk\","
          "\"$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\Vidsumly\\Vidsumly.lnk\","
          "(Join-Path ([Environment]::GetFolderPath('Desktop')) 'Vidento.lnk'),"
          "(Join-Path ([Environment]::GetFolderPath('Desktop')) 'Vidsumly.lnk'),"
          "(Join-Path ([Environment]::GetFolderPath('Desktop')) 'Vidsumly.lnk'));"
          "foreach($f in $p){ if(Test-Path $f){ $l=$s.CreateShortcut($f);"
          f" if($l.Arguments -like '*vidsum*'){{ $l.IconLocation='{ico},0'; $l.Save() }} }} }}")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=30,
                       capture_output=True, creationflags=0x08000000)
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text(sig, encoding="utf-8")
    except (OSError, subprocess.SubprocessError):
        pass


def _set_window_icon(title: str) -> None:
    """Ikona Vidsumly na pasku tytułu i pasku zadań (pywebview na Windows bierze ikonę z pythonw.exe)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ico = str(Path(__file__).parent / "web" / "vidsum.ico")
        u = ctypes.windll.user32
        for _ in range(50):                             # okno pojawia się chwilę po starcie
            hwnd = u.FindWindowW(None, title)
            if hwnd:
                break
            time.sleep(0.1)
        if not hwnd:
            return
        for size, which in ((16, 0), (32, 1)):          # ICON_SMALL, ICON_BIG
            h = u.LoadImageW(None, ico, 1, size, size, 0x10)   # IMAGE_ICON, LR_LOADFROMFILE
            if h:
                u.SendMessageW(hwnd, 0x0080, which, h)  # WM_SETICON
        style_title_bar(hwnd)
    except Exception:
        pass


# pasek tytułu w kolorach programu (0.10.0): systemowo przez DWM, więc przeciąganie, dociąganie do krawędzi
# i zmiana rozmiaru działają jak w każdym oknie. Kolory jako COLORREF (0x00BBGGRR). Windows 10 zna tylko tryb ciemny.
TITLE_BAR = {"tlo": (13, 17, 26), "tekst": (233, 237, 245), "ramka": (61, 123, 255)}


def _colorref(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    return (b << 16) | (g << 8) | r


def style_title_bar(hwnd: int) -> list[int]:
    """Ciemny pasek tytułu (20), jego kolor (35), kolor tekstu (36) i ramki okna (34). Zwraca wyniki HRESULT
    (0 = przyjęte; Windows 10 odrzuca 34–36 — zostaje wtedy sam tryb ciemny)."""
    import ctypes
    from ctypes import wintypes
    dwm = ctypes.windll.dwmapi
    out = []
    for attr, val in ((20, 1), (35, _colorref(TITLE_BAR["tlo"])), (36, _colorref(TITLE_BAR["tekst"])),
                      (34, _colorref(TITLE_BAR["ramka"]))):
        v = wintypes.DWORD(val)
        out.append(dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v)))
    return out


CLOSE_Q = {"pl": "Trwa analiza. Zamknąć program? Film zostanie zapisany w kolejce i po ponownym uruchomieniu "
                  "przeanalizujesz go od nowa (kolejka wróci wstrzymana).",
           "en": "An analysis is running. Quit? The video stays in the queue and you can analyse it again after the "
                 "next start (the queue comes back paused)."}


def run_window(url: str, app: "App | None" = None) -> bool:
    """Prawdziwe okno programu (pywebview na WebView2 — jest w każdym Windows 10/11, także bez przeglądarki Edge).
    Działa na głównym wątku i wraca, gdy okno zostanie zamknięte. False = brak pywebview/WebView2 → stara droga.
    Okno bez przyspieszania sprzętowego: nie zabiera pamięci karty modelom (pomiar: ~850 MB i analiza 3:40 zamiast ~1:40)."""
    if os.environ.get("VIDSUM_PRZEGLADARKA") == "1":
        return False
    try:
        import webview                                  # pywebview
    except Exception as e:                              # brak biblioteki / WebView2 / .NET
        print(f"Okno programu niedostępne ({type(e).__name__}: {e}) — otwieram w przeglądarce.")
        return False
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--disable-gpu")
    if os.name == "nt":
        try:                                            # osobna pozycja na pasku zadań (nie „Python”)
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Vidsumly.Aplikacja")
        except Exception:
            pass
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True       # „Pobierz JSON” itp.
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    except Exception:
        pass
    try:
        win = webview.create_window(f"{BRAND} {__version__}", url, width=1400, height=900, min_size=(900, 600),
                                    text_select=True)

        def closing():
            if app and any(j.status == "trwa" for j in app.worker.jobs.values()):
                en = app.settings.get("jezyk_ui") == "en"
                return win.create_confirmation_dialog(BRAND, CLOSE_Q["en" if en else "pl"])
            return True
        win.events.closing += closing
        store = app_dir() / "okno"
        webview.start(_set_window_icon, (f"{BRAND} {__version__}",), private_mode=False, storage_path=str(store))
        return True
    except Exception as e:
        print(f"Okno programu nie wystartowało ({type(e).__name__}: {e}) — otwieram w przeglądarce.")
        return False


def serve(port: int = 0, open_browser: bool = True, token: str | None = None, results: Path | None = None) -> None:
    token = token or _persistent_token()
    want = port or DEFAULT_PORT
    if not port and _running_instance(want) and _replace_older(want, token):
        pass                               # stara wersja zamknięta — uruchamiamy tę
    elif not port and _running_instance(want):
        url = f"http://127.0.0.1:{want}/?t={token}"
        print(f"{BRAND} już działa — otwieram: {url}")
        if open_browser and not run_window(url):
            open_window(url)
        return
    app = App(results or default_results_dir(), token)
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", want), make_handler(app))
    except OSError:                       # port zajęty przez inny program → dowolny wolny
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    url = f"http://127.0.0.1:{srv.server_address[1]}/?t={app.token}"
    print(f"{BRAND} {__version__} — interfejs: {url}")
    print("Program działa w tle; wyłączysz go w Ustawieniach → „Zamknij program” albo zamykając okno.")
    threading.Thread(target=fix_shortcut_icons, daemon=True).start()
    from . import procs
    procs.setup_kill_on_close()                    # Windows: dzieci (ffmpeg) giną razem z programem, nawet przy awarii
    if open_browser:
        # serwer w tle, okno programu na głównym wątku; zamknięcie okna kończy program
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        if run_window(url, app):
            app.shutdown("okno")                         # kolejka zapisana, procesy potomne zakończone
            srv.shutdown()
            os._exit(0)                                  # wątki analizy (Whisper/OCR w tym procesie) kończą się razem z nim
        open_window(url)                                 # brak okna → Edge w trybie aplikacji / przeglądarka
        try:
            th.join()
        except KeyboardInterrupt:
            pass
        return
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
