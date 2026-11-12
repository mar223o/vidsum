"""Pierwsze uruchomienie bez PowerShella (0.12.0): Ollama i modele z poziomu programu.

Do 0.11.9 instrukcja (`packaging/CZYTAJ_MNIE.txt`) kazała wpisać w PowerShellu `winget install Ollama.Ollama`,
`ollama pull …` i dwa razy `setx`. Teraz program sam sprawdza, czego brakuje, i prowadzi przez to przyciskami:

1. Ollama nie jest zainstalowana → pobranie oficjalnego instalatora (`https://ollama.com/download/OllamaSetup.exe`)
   i uruchomienie go. Instalator jest OKNEM Ollamy — użytkownik klika w nim „Install” (dokumentacja Ollamy opisuje tylko
   flagę `/DIR`, cichej instalacji nie obiecuje, więc jej nie używamy). Instalacja nie wymaga uprawnień administratora
   (źródło: https://docs.ollama.com/windows).
2. Ollama jest, ale nie działa → uruchomienie `ollama serve` w tle z `OLLAMA_NUM_PARALLEL=2` i
   `OLLAMA_MAX_LOADED_MODELS=1` (bez tego Ollama obsługuje 1 zapytanie naraz — domyślna wartość wg
   https://docs.ollama.com/faq; dwa naraz skracały opis kadrów w pomiarach 0.11.x).
3. Brakuje modeli → pobranie przez API Ollamy z paskiem postępu.
4. Ollama działa, ale bez dwóch zapytań naraz → jeden przycisk: zapis zmiennych dla konta (`setx`) i ponowne uruchomienie.

Czego NIE przetestowano: prawdziwej instalacji na Windows (testy sprawdzają logikę na atrapach; runner CI nie instaluje
Ollamy). Każdy krok ma więc komunikat „co zrobić ręcznie”, gdyby przycisk zawiódł.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

DOWNLOAD_URL = "https://ollama.com/download/OllamaSetup.exe"
DOWNLOAD_PAGE = "https://ollama.com/download"
SERVE_ENV = {"OLLAMA_NUM_PARALLEL": "2", "OLLAMA_MAX_LOADED_MODELS": "1"}
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def host_url(host: str | None = None) -> str:
    h = (host or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    return h if h.startswith("http") else "http://" + h


def find_exe() -> Path | None:
    """Plik `ollama.exe` / `ollama`: z PATH albo z domyślnych miejsc instalacji na Windows."""
    w = shutil.which("ollama")
    if w:
        return Path(w)
    cands = []
    for var, sub in (("LOCALAPPDATA", r"Programs\Ollama\ollama.exe"), ("ProgramFiles", r"Ollama\ollama.exe")):
        base = os.environ.get(var)
        if base:
            cands.append(Path(base) / sub)
    return next((p for p in cands if p.is_file()), None)


def installed_models(host: str | None = None, timeout: float = 3) -> list[str] | None:
    """Lista modeli w Ollamie albo None, gdy Ollama nie odpowiada."""
    try:
        with urllib.request.urlopen(host_url(host) + "/api/tags", timeout=timeout) as r:
            return [m["name"] for m in json.loads(r.read().decode("utf-8")).get("models", [])]
    except Exception:
        return None


def _has(names: list[str], model: str) -> bool:
    want = model if ":" in model else model + ":latest"
    return want in names


class Task:
    """Jedno zadanie w tle (instalacja albo pobieranie modeli) — interfejs odpytuje `snapshot()`."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.data: dict = {"co": "", "etap": "", "procent": None, "blad": "", "trwa": False}
        self.thread: threading.Thread | None = None

    def set(self, **kw) -> None:
        with self.lock:
            self.data.update(kw)

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.data)

    def run(self, what: str, fn, *args) -> bool:
        """Startuje `fn(task, *args)` w wątku; False, gdy inne zadanie jeszcze trwa."""
        with self.lock:
            if self.data["trwa"]:
                return False
            self.data = {"co": what, "etap": "", "procent": None, "blad": "", "trwa": True}

        def job() -> None:
            try:
                fn(self, *args)
            except Exception as e:                          # komunikat dla użytkownika zamiast cichej porażki
                self.set(blad=str(e)[:300])
            finally:
                self.set(trwa=False)

        self.thread = threading.Thread(target=job, daemon=True)
        self.thread.start()
        return True


TASK = Task()


def state(models: list[str], host: str | None = None) -> dict:
    """Stan pierwszego uruchomienia → co jest, czego brakuje i jaki jest następny krok.

    krok: "zainstaluj" (nie ma Ollamy) | "uruchom" (jest, nie działa) | "pobierz" (brakuje modeli) | "gotowe"."""
    names = installed_models(host)
    exe = find_exe()
    mods = [{"nazwa": m, "pobrany": bool(names is not None and _has(names, m))} for m in dict.fromkeys(models) if m]
    if names is None:
        step = "uruchom" if exe else "zainstaluj"
    elif not all(m["pobrany"] for m in mods):
        step = "pobierz"
    else:
        step = "gotowe"
    try:
        par = int(os.environ.get("OLLAMA_NUM_PARALLEL") or 1)
    except ValueError:
        par = 1
    return {"dziala": names is not None, "zainstalowana": bool(exe) or names is not None, "sciezka": str(exe) if exe else None,
            "modele": mods, "krok": step, "rownolegle": par, "windows": sys.platform == "win32",
            "strona": DOWNLOAD_PAGE, "zadanie": TASK.snapshot()}


def _wait_api(host: str | None, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if installed_models(host, timeout=2) is not None:
            return True
        time.sleep(1.0)
    return False


def start(host: str | None = None, wait: float = 25.0) -> bool:
    """Uruchamia `ollama serve` w tle z ustawieniami szybkości. True, gdy API odpowiada."""
    if installed_models(host, timeout=2) is not None:
        return True
    exe = find_exe()
    if not exe:
        raise RuntimeError("Nie znalazłem programu Ollama na tym komputerze — najpierw go zainstaluj.")
    env = {**os.environ, **SERVE_ENV}
    os.environ.update(SERVE_ENV)                           # program wysyła wtedy 2 zapytania naraz (llm.ollama_parallel)
    subprocess.Popen([str(exe), "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW | _DETACHED, close_fds=True)
    if not _wait_api(host, wait):
        raise RuntimeError("Ollama została uruchomiona, ale nie odpowiada. Otwórz ją z menu Start i spróbuj ponownie.")
    return True


def _download(url: str, dest: Path, task: Task) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Vidsumly"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            task.set(procent=int(100 * done / total) if total else None,
                     etap=f"Pobieram instalator Ollamy ({done / 1e6:.0f} MB" + (f" z {total / 1e6:.0f} MB)" if total else ")"))
    if done < 1_000_000:
        raise RuntimeError("Pobrany plik instalatora jest za mały — pobierz Ollamę ręcznie ze strony ollama.com/download.")


def install(task: Task, host: str | None = None, wait_minutes: float = 15.0) -> None:
    """Pobiera oficjalny instalator i otwiera go; czeka, aż Ollama zacznie odpowiadać (użytkownik klika „Install”)."""
    if sys.platform != "win32":
        raise RuntimeError("Instalacja z programu działa tylko w Windows. Pobierz Ollamę ze strony ollama.com/download.")
    dest = Path(tempfile.gettempdir()) / "OllamaSetup.exe"
    task.set(etap="Pobieram instalator Ollamy…", procent=0)
    try:
        _download(DOWNLOAD_URL, dest, task)
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"Nie udało się pobrać instalatora ({e}). Pobierz Ollamę ręcznie ze strony ollama.com/download.") from e
    task.set(etap="Otworzyłem instalator Ollamy — kliknij w nim „Install”. Czekam, aż skończy…", procent=None)
    os.environ.update(SERVE_ENV)                           # instalator startuje Ollamę jako proces potomny tego programu
    subprocess.Popen([str(dest)], env={**os.environ, **SERVE_ENV}, close_fds=True)
    if not _wait_api(host, wait_minutes * 60):
        if find_exe():                                     # zainstalowana, ale sama się nie uruchomiła
            task.set(etap="Uruchamiam Ollamę…")
            start(host)
        else:
            raise RuntimeError("Instalator nie skończył pracy. Dokończ instalację w jego oknie i kliknij „Sprawdź ponownie”.")
    task.set(etap="Ollama zainstalowana i działa.", procent=100)


def pull(task: Task, models: list[str], host: str | None = None) -> None:
    """Pobiera brakujące modele po kolei; postęp (procent całości bieżącego modelu) do zadania."""
    names = installed_models(host)
    if names is None:
        raise RuntimeError("Ollama nie odpowiada — najpierw ją uruchom.")
    todo = [m for m in dict.fromkeys(models) if m and not _has(names, m)]
    for i, model in enumerate(todo, 1):
        label = f"Pobieram model {model} ({i} z {len(todo)})"
        task.set(etap=label + "…", procent=0)
        req = urllib.request.Request(host_url(host) + "/api/pull", data=json.dumps({"model": model}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3600) as r:
                for line in r:
                    if not line.strip():
                        continue
                    d = json.loads(line.decode("utf-8"))
                    if d.get("error"):
                        raise RuntimeError(f"Pobieranie modelu {model}: {d['error']}")
                    if d.get("total") and d.get("completed") is not None:
                        task.set(procent=int(100 * d["completed"] / d["total"]),
                                 etap=f"{label}: {d['completed'] / 1e9:.1f} z {d['total'] / 1e9:.1f} GB")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise RuntimeError(f"Przerwane pobieranie modelu {model} ({e}). Kliknij ponownie — pobieranie zacznie od miejsca przerwania.") from e
    task.set(etap="Modele pobrane." if todo else "Modele są już pobrane.", procent=100)


def enable_parallel(task: Task, host: str | None = None) -> None:
    """Dwa zapytania naraz na stałe: zmienne dla konta użytkownika (`setx`) + ponowne uruchomienie Ollamy z nimi."""
    if sys.platform != "win32":
        raise RuntimeError("Ta opcja działa tylko w Windows.")
    exe = find_exe()
    if not exe:
        raise RuntimeError("Nie znalazłem programu Ollama — nie mogę uruchomić go ponownie z nowymi ustawieniami.")
    task.set(etap="Zapisuję ustawienia Ollamy dla Twojego konta…")
    for k, v in SERVE_ENV.items():
        subprocess.run(["setx", k, v], capture_output=True, timeout=30, creationflags=_NO_WINDOW)
    os.environ.update(SERVE_ENV)
    task.set(etap="Uruchamiam Ollamę ponownie…")
    for image in ("ollama app.exe", "ollama.exe"):
        subprocess.run(["taskkill", "/IM", image, "/F"], capture_output=True, timeout=30, creationflags=_NO_WINDOW)
    time.sleep(1.5)
    start(host)
    task.set(etap="Gotowe: Ollama obsługuje 2 zapytania naraz.", procent=100)
