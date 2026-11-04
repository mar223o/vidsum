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

from . import __version__
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
        return {"id": self.id, "label": self.label, "status": self.status, "log": self.log[-200:],
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
                    if m:
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
             "max_kadrow": None, "ciasteczka_z": "", "wyniki": str(self.results)}
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
                       cookies_from_browser=s.get("ciasteczka_z") or None)

    def status(self) -> dict:
        st: dict = {"wersja": __version__}
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
                answer = eng.complete(prompt)
            except Exception as e:
                return self._json({"error": f"Nie udało się odpowiedzieć: {e}"}, 400)
            now = time.strftime("%Y-%m-%dT%H:%M:%S")
            history += [{"rola": "user", "tekst": question, "czas": now},
                        {"rola": "asystent", "tekst": answer, "czas": now, "silnik": silnik}]
            hist_file.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")
            return self._json({"odpowiedz": answer, "historia": history})

        # --- GET ---
        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(u.query)
            if u.path in ("/", "/index.html"):
                return self._file(web / "index.html")
            if u.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if not self._authed(qs):
                return
            if u.path == "/api/status":
                return self._json(app.status())
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
            return b"VidSum" in r.read(4096)
    except Exception:
        return False


def serve(port: int = 0, open_browser: bool = True, token: str | None = None, results: Path | None = None) -> None:
    token = token or _persistent_token()
    want = port or DEFAULT_PORT
    if not port and _running_instance(want):
        url = f"http://127.0.0.1:{want}/?t={token}"
        print(f"VidSum już działa — otwieram: {url}")
        if open_browser:
            webbrowser.open(url)
        return
    app = App(results or default_results_dir(), token)
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", want), make_handler(app))
    except OSError:                       # port zajęty przez inny program → dowolny wolny
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    url = f"http://127.0.0.1:{srv.server_address[1]}/?t={app.token}"
    print(f"VidSum {__version__} — interfejs: {url}")
    print("Program działa w tle; wyłączysz go przyciskiem „Zakończ” w interfejsie.")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
