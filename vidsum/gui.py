"""Interfejs w przeglądarce: lokalny serwer (tylko 127.0.0.1) + kolejka analiz.

Bez zewnętrznych bibliotek (http.server ze standardowej biblioteki). Każde żądanie API wymaga
losowego tokenu z adresu strony — inne strony otwarte w przeglądarce nie mogą wywołać API.
"""
from __future__ import annotations

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
from .llm import ClaudeCode, LLMError, Ollama
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

    def to_dict(self) -> dict:
        end = self.finished or time.time()
        return {"id": self.id, "label": self.label, "status": self.status, "log": self.log[-200:],
                "error": self.error, "out": str(self.out) if self.out else None, "created": self.created,
                "stage": self.stage,
                "elapsed": round(end - self.started, 1) if self.started else None}


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

    def _load_settings(self) -> dict:
        d = {"jezyk_ui": "pl", "jezyk": "auto", "whisper": "small", "obraz": "ollama", "model_obrazu": "qwen3-vl:4b-instruct",
             "streszczenie": "auto", "max_kadrow": None, "ciasteczka_z": "", "wyniki": str(self.results)}
        try:
            d.update(json.loads(self.settings_file.read_text(encoding="utf-8")))
        except Exception:
            pass
        return d

    def save_settings(self, new: dict) -> dict:
        allowed = set(self._load_settings())
        self.settings.update({k: v for k, v in new.items() if k in allowed})
        self.settings_file.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.settings

    def options(self, s: dict) -> Options:
        mk = s.get("max_kadrow")
        return Options(out_root=Path(s.get("wyniki") or self.results),
                       language=None if s.get("jezyk") in (None, "", "auto") else s["jezyk"],
                       whisper_model=s.get("whisper") or "small",
                       whisper_root=str(app_dir() / "modele"),
                       vision=s.get("obraz", "ollama"), vision_model=s.get("model_obrazu") or "qwen3-vl:4b-instruct",
                       summary=s.get("streszczenie") or "auto", max_frames=int(mk) if mk else None,
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
                jobs = sorted(app.worker.jobs.values(), key=lambda j: -j.created)
                return self._json([j.to_dict() for j in jobs])
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
                job = Job(secrets.token_hex(4), str(dst), name, app.options(app.settings), dst)
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


def serve(port: int = 0, open_browser: bool = True, token: str | None = None, results: Path | None = None) -> None:
    app = App(results or default_results_dir(), token or secrets.token_urlsafe(16))
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    url = f"http://127.0.0.1:{srv.server_address[1]}/?t={app.token}"
    print(f"VidSum {__version__} — interfejs: {url}")
    print("Zamknij to okno, aby wyłączyć program.")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
