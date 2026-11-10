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


def app_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    p = Path(base) / "VidSum"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_results_dir() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "VidSum"


def web_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for p in (base / "vidsum" / "web", Path(__file__).resolve().parent / "web"):
        if p.is_dir():
            return p
    raise FileNotFoundError("Brak folderu web/")


# ---------------- kolejka zadań ----------------
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
        self.partial: dict = {}         # gotowe etapy w trakcie analizy (podgląd): transkrypcja, napisy, kadry…

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

    def to_dict(self) -> dict:
        end = self.finished or time.time()
        return {"id": self.id, "label": self.label, "status": self.status, "log": self.log[-400:],
                "error": self.error, "out": str(self.out) if self.out else None, "created": self.created,
                "stage": self.stage, "czesciowe": list(self.partial) if self.status == "trwa" else [],
                "elapsed": round(end - self.started, 1) if self.started else None, "card": self.card()}


class Worker:
    """Jeden wątek, zadania po kolei — dwa filmy naraz nie zmieściłyby się w 8 GB VRAM."""

    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.q: queue.Queue[Job] = queue.Queue()
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, job: Job) -> None:
        with self.lock:
            self.jobs[job.id] = job
        self.q.put(job)

    def _loop(self) -> None:
        while True:
            job = self.q.get()
            job.status = "trwa"
            job.started = time.time()
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
            except Exception as e:  # pokaż błąd w interfejsie, nie zabijaj serwera
                job.status, job.error = "blad", f"{type(e).__name__}: {e}"
                job.log.append("✖ " + job.error)
                traceback.print_exc()
            finally:
                job.finished = time.time()
                if job.upload:
                    shutil.rmtree(job.upload.parent, ignore_errors=True)


# ---------------- serwer HTTP ----------------
class App:
    def __init__(self, results: Path, token: str):
        self.results = results
        self.token = token
        self.worker = Worker()
        self.settings_file = app_dir() / "ustawienia.json"
        self.settings = self._load_settings()
        self.translations: dict = {}          # (id zadania, język) → {"stan", "postep", "error"} — tłumaczenie całości
        self._tr_lock = threading.Lock()
        self.scan_library()

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
             "podglad": False}
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
                       preview=None)          # 0.10.0: podgląd zawsze automatycznie (bez osobnego trybu)

    def status(self) -> dict:
        st: dict = {"wersja": __version__}
        try:
            from .update import can_swap_code, token_get
            st["klucz_github"] = bool(token_get())
            st["aktualizacja_kodu"] = can_swap_code()
        except Exception:
            st["klucz_github"] = False
        try:
            find_tool("ffmpeg")
            find_tool("ffprobe")
            st["ffmpeg"] = True
        except ToolError:
            st["ffmpeg"] = False
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
        try:
            ClaudeCode().check()
            st["claude"], st["claude_info"] = True, "Claude Code"
        except LLMError as e:
            st["claude"], st["claude_info"] = False, str(e)
        return st


_SAFE_UPLOAD = re.compile(r"[^\w.\- ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")


def make_handler(app: App):
    web = web_dir()

    class H(BaseHTTPRequestHandler):
        server_version = f"VidSum/{__version__}"

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
            try:
                # samodzielnie: lokalny model tekstowy; Claude tylko gdy użytkownik wybrał go w ustawieniach
                if app.settings.get("streszczenie") == "claude":
                    eng, silnik = ClaudeCode(), "claude-code"
                else:
                    eng = Ollama(app.settings.get("model_tekstowy") or DEFAULT_TEXT_MODEL)
                    eng.ensure(lambda m: None)
                    silnik = f"ollama:{eng.model}"
                from .summary import check_chat_answer
                answer = check_chat_answer(eng.complete(prompt).strip(), analysis)
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
            """Tłumaczenie całej analizy (0.9.0) w tle; GET = stan, POST = start (gdy jeszcze nie ma i nie trwa)."""
            from .translate_all import LANGS, translate_analysis
            p = self._job_file(jid, "analiza.json")
            if not p or not p.is_file():
                return self._json({"error": "brak wyników"}, 404)
            if lang not in LANGS:
                return self._json({"error": "obsługiwane języki: pl, en"}, 400)
            key = (jid, lang)
            with app._tr_lock:
                st = app.translations.get(key)
                done = lang in (json.loads(p.read_text(encoding="utf-8")).get("tlumaczenie_calosci") or {})
                if done and not (st and st["stan"] == "trwa"):
                    return self._json({"stan": "gotowe"})
                if not start or (st and st["stan"] == "trwa"):
                    return self._json(st or {"stan": "brak"})
                st = app.translations[key] = {"stan": "trwa", "postep": "start"}

            def job() -> None:
                try:
                    eng = Ollama(app.settings.get("model_tekstowy") or DEFAULT_TEXT_MODEL)
                    eng.ensure(lambda m: None)
                    res = translate_analysis(eng, json.loads(p.read_text(encoding="utf-8")), lang,
                                             progress=lambda m: st.update(postep=m))
                    with app._tr_lock:                       # zapis do analiza.json (bez gubienia innych zmian)
                        r = json.loads(p.read_text(encoding="utf-8"))
                        r.setdefault("tlumaczenie_calosci", {})[lang] = res
                        p.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
                    st.update(stan="gotowe", postep="", nieprzetlumaczone=res["nieprzetlumaczone"], czas_s=res["czas_s"])
                except Exception as e:                        # Ollama nie działa itp.
                    st.update(stan="blad", error=str(e)[:300])
            threading.Thread(target=job, daemon=True).start()
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
            if u.path == "/api/zakoncz":
                # program działa w tle (bez okna) — wyłącza się przyciskiem w interfejsie
                self._json({"ok": True})
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
                opt = app.options(app.settings)
                opt.move_source = True          # film zostaje w folderze wyników — do odtwarzacza
                job = Job(secrets.token_hex(4), str(dst), name, opt, dst)
                app.worker.submit(job)
                return self._json(job.to_dict())
            if u.path == "/api/link":
                b = self._body()
                src = (b.get("zrodlo") or "").strip().strip('"')
                if not src:
                    return self._json({"error": "pusty link"}, 400)
                job = Job(secrets.token_hex(4), src, src, app.options(app.settings), None)
                app.worker.submit(job)
                return self._json(job.to_dict())
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
    """Stały klucz (zapisany w %LOCALAPPDATA%\\VidSum) — zakładki i stare karty działają po restarcie programu."""
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
    """Czy pod tym portem działa już VidSum (drugie uruchomienie → otwórz istniejący zamiast nowego)."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as r:
            head = r.read(4096)
            return b"VidSum" in head or b"Vidento" in head
    except Exception:
        return False


def _replace_older(port: int, token: str) -> bool:
    """Działa INNA wersja VidSum (np. stara po aktualizacji) i nic nie analizuje → zamknij ją, żeby otworzyła się ta.

    Na komputerze testowym „VidSum Start” z nowej wersji otwierał stronę starej, która dalej działała w tle."""
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
            print("Działa starsza wersja VidSum i właśnie analizuje — zostawiam ją (zamknij ją po analizie).")
            return False
        req = urllib.request.Request(base + "/api/zakoncz", data=b"{}", method="POST",
                                     headers={"X-Token": token, "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        return False
    for _ in range(50):                    # do 5 s na zwolnienie portu
        time.sleep(0.1)
        if not _running_instance(port):
            print("Zamknięto starszą wersję VidSum.")
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
    """VidSum we własnym oknie (bez kart i paska adresu, własna ikona na pasku zadań) — Edge w trybie aplikacji,
    z osobnym profilem i BEZ przyspieszania sprzętowego: okno nie zabiera pamięci karty modelom (pomiar: przeglądarki
    i inne programy brały ~850 MB karty i analiza trwała 3:40 zamiast ~1:40). Bez Edge / VIDSUM_PRZEGLADARKA=1 →
    domyślna przeglądarka, jak dotąd."""
    edge = None if os.environ.get("VIDSUM_PRZEGLADARKA") == "1" else _edge_exe()
    if not edge:
        webbrowser.open(url)
        return
    prof = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "VidSum" / "okno"
    args = [edge, f"--app={url}", f"--user-data-dir={prof}", "--disable-gpu", "--window-size=1400,900",
            "--no-first-run", "--no-default-browser-check"]
    try:
        subprocess.Popen(args, close_fds=True)
    except OSError:
        webbrowser.open(url)


def fix_shortcut_icons() -> None:
    """Skróty z instalatora < 0.8.1 mają ikonę Pythona; aktualizacja samego kodu ich nie zmienia — poprawiamy je raz."""
    if os.name != "nt":
        return
    ico = Path(__file__).parent / "web" / "vidsum.ico"
    mark = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "VidSum" / "ikony_skrotow.txt"
    # znacznik = ścieżka + rozmiar ikony: nowa ikona (0.10.0) → skróty odświeżane jeszcze raz
    sig = f"{ico}|{ico.stat().st_size}" if ico.exists() else ""
    if not ico.exists() or (mark.exists() and mark.read_text(encoding="utf-8").strip() == sig):
        return
    ps = ("$s=New-Object -ComObject WScript.Shell;"
          "$p=@(\"$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\VidSum\\VidSum.lnk\","
          "\"$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\Vidento\\Vidento.lnk\","
          "(Join-Path ([Environment]::GetFolderPath('Desktop')) 'Vidento.lnk'),"
          "(Join-Path ([Environment]::GetFolderPath('Desktop')) 'VidSum.lnk'));"
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
    """Ikona VidSum na pasku tytułu i pasku zadań (pywebview na Windows bierze ikonę z pythonw.exe)."""
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
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VidSum.Aplikacja")
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
                return win.create_confirmation_dialog(BRAND, "Trwa analiza. Zamknąć program i ją przerwać?")
            return True
        win.events.closing += closing
        store = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "VidSum" / "okno"
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
    print("Program działa w tle; wyłączysz go przyciskiem „Zakończ” w interfejsie.")
    threading.Thread(target=fix_shortcut_icons, daemon=True).start()
    if open_browser:
        # serwer w tle, okno programu na głównym wątku; zamknięcie okna kończy program
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        if run_window(url, app):
            srv.shutdown()
            os._exit(0)                                  # także gdy trwała analiza (zamknięcie potwierdzone w oknie)
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
