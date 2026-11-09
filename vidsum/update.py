"""Aktualizacje z (prywatnego) repozytorium GitHub.

Klucz GitHub (tylko odczyt, tylko repozytorium VidSum) trzymamy w Menedżerze poświadczeń Windows — nigdy w pliku
ani w logu. Zwykła aktualizacja pobiera sam kod (kilka MB) i podmienia folder `vidsum`; gdy zmieniły się biblioteki
(inny `zaleznosci` w _build.json), pobierany jest pełny instalator.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from . import __version__

REPO = "mar223o/vidsum"
CRED_TARGET = "VidSum/github"
API = "https://api.github.com"
PKG = Path(__file__).resolve().parent          # folder `vidsum` (kod programu)
ROOT = PKG.parent                              # folder instalacji


class UpdateError(RuntimeError):
    pass


# ---------------- Menedżer poświadczeń Windows (advapi32, bez dodatkowych bibliotek) ----------------

def _cred_api():
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    adv.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    adv.CredWriteW.restype = wintypes.BOOL
    adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    adv.CredReadW.restype = wintypes.BOOL
    adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    adv.CredDeleteW.restype = wintypes.BOOL
    adv.CredFree.argtypes = [ctypes.c_void_p]
    return ctypes, CREDENTIAL, adv


CRED_TYPE_GENERIC, CRED_PERSIST_LOCAL_MACHINE = 1, 2


def token_get() -> str | None:
    api = _cred_api()
    if not api:
        return None
    ctypes, CREDENTIAL, adv = api
    p = ctypes.POINTER(CREDENTIAL)()
    if not adv.CredReadW(CRED_TARGET, CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
        return None
    try:
        c = p.contents
        return bytes(c.CredentialBlob[:c.CredentialBlobSize]).decode("utf-16-le") or None
    finally:
        adv.CredFree(p)


def token_set(token: str) -> None:
    token = (token or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{20,255}", token):
        raise UpdateError("To nie wygląda na klucz GitHub (zaczyna się zwykle od „github_pat_”).")
    api = _cred_api()
    if not api:
        raise UpdateError("Zapis klucza działa tylko w Windows (Menedżer poświadczeń).")
    ctypes, CREDENTIAL, adv = api
    blob = token.encode("utf-16-le")
    buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    c = CREDENTIAL(Type=CRED_TYPE_GENERIC, TargetName=CRED_TARGET, CredentialBlobSize=len(blob),
                   CredentialBlob=ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)),
                   Persist=CRED_PERSIST_LOCAL_MACHINE, UserName="vidsum")
    if not adv.CredWriteW(ctypes.byref(c), 0):
        raise UpdateError(f"Nie udało się zapisać klucza w Menedżerze poświadczeń (błąd {ctypes.get_last_error()}).")


def token_delete() -> None:
    api = _cred_api()
    if api:
        api[2].CredDeleteW(CRED_TARGET, CRED_TYPE_GENERIC, 0)


# ---------------- GitHub ----------------

class _NoAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """Pobieranie plików wydania przekierowuje na inny serwer — klucza GitHub NIE wysyłamy dalej."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlparse(newurl).hostname != urllib.parse.urlparse(req.full_url).hostname:
            for h in ("Authorization", "authorization"):
                new.headers.pop(h, None)
                new.unredirected_hdrs.pop(h, None)
        return new


def _open(url: str, token: str | None, accept: str = "application/vnd.github+json", timeout: float = 60):
    """Zapytanie do GitHuba. Repozytorium jest publiczne (od 0.7.8) — klucz niepotrzebny; jeśli zapisany, idzie dalej
    (prywatne repozytorium / wyższy limit zapytań)."""
    h = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "VidSum-aktualizacje"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=h)
    opener = urllib.request.build_opener(_NoAuthOnRedirect)
    try:
        return opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 401 or (e.code == 403 and token):
            raise UpdateError("GitHub odrzucił klucz (wygasł albo nie ma dostępu do repozytorium VidSum). "
                              "Usuń go w Ustawieniach → Aktualizacje — przy publicznym repozytorium nie jest potrzebny.") from e
        if e.code == 403:
            raise UpdateError("GitHub chwilowo ogranicza zapytania (limit na godzinę) — spróbuj za chwilę.") from e
        if e.code == 404:
            raise UpdateError("Brak wydań" + (" albo klucz nie ma dostępu do repozytorium VidSum." if token else
                              " albo repozytorium jest prywatne — wtedy wklej klucz w Ustawieniach → Aktualizacje.")) from e
        raise UpdateError(f"GitHub: błąd {e.code}.") from e
    except urllib.error.URLError as e:
        raise UpdateError(f"Brak połączenia z GitHubem ({e.reason}).") from e


def _ver(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4])


def build_info() -> dict:
    """Co jest zainstalowane: wersja i odcisk bibliotek (zapisywany przy budowie paczki)."""
    f = PKG / "_build.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def can_swap_code() -> bool:
    """Podmiana samego kodu działa w wersji z instalatora / -python (zwykłe pliki .py), nie w .exe (kod w środku)."""
    return not getattr(sys, "frozen", False) and os.access(ROOT, os.W_OK) and (PKG / "__init__.py").is_file()


def check(token: str | None = None) -> dict:
    token = token or token_get()                    # opcjonalny (repozytorium publiczne)
    with _open(f"{API}/repos/{REPO}/releases/latest", token) as r:
        rel = json.loads(r.read().decode("utf-8"))
    tag = rel.get("tag_name", "").lstrip("v")
    assets = {a["name"]: a for a in rel.get("assets", [])}
    out = {"aktualna": __version__, "najnowsza": tag, "jest_nowsza": bool(tag) and _ver(tag) > _ver(__version__),
           "notatki": (rel.get("body") or "")[:3000], "rodzaj": None, "strona": rel.get("html_url")}
    if not out["jest_nowsza"]:
        return out
    code, meta, setup = (f"VidSum-{tag}-aktualizacja.zip", f"VidSum-{tag}-aktualizacja.json", f"VidSum-Setup-{tag}.exe")
    deps_new = None
    if meta in assets:
        with _open(assets[meta]["url"], token, "application/octet-stream") as r:
            deps_new = json.loads(r.read().decode("utf-8")).get("zaleznosci")
    deps_now = build_info().get("zaleznosci")
    if can_swap_code() and code in assets and deps_new and deps_now == deps_new:
        out["rodzaj"], out["plik"], out["rozmiar_mb"] = "kod", code, round(assets[code]["size"] / 1e6, 1)
    elif setup in assets:
        out["rodzaj"], out["plik"], out["rozmiar_mb"] = "pelna", setup, round(assets[setup]["size"] / 1e6, 1)
    out["_assets"] = {k: v["url"] for k, v in assets.items()}
    return out


def _download(url: str, token: str, dst: Path, log) -> Path:
    with _open(url, token, "application/octet-stream", timeout=600) as r, open(dst, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, -10
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total and (pct := done * 100 // total) >= last + 10:
                last = pct
                log(f"pobieranie: {pct}%")
    return dst


def _sha_ok(path: Path, url: str | None, token: str) -> None:
    if not url:
        raise UpdateError("W wydaniu brak sumy kontrolnej — przerywam (bezpieczeństwo).")
    with _open(url, token, "application/octet-stream") as r:
        want = r.read().decode("ascii", "replace").split()[0].lower()
    have = hashlib.sha256(path.read_bytes()).hexdigest()
    if have != want:
        raise UpdateError("Suma kontrolna pobranego pliku się nie zgadza — przerywam.")


def swap_code(zip_path: Path, expect_version: str, root: Path = ROOT) -> None:
    """Kasuje stary kod i wstawia nowy (z kopią na wypadek błędu). Dane, ustawienia i modele są gdzie indziej."""
    pkg = root / "vidsum"
    stage = Path(tempfile.mkdtemp(prefix="vidsum_akt_", dir=root))
    try:
        with zipfile.ZipFile(zip_path) as z:
            for n in z.namelist():                         # bez ścieżek wychodzących poza folder
                if n.startswith(("/", "\\")) or ".." in Path(n).parts:
                    raise UpdateError("Nieprawidłowa paczka aktualizacji.")
            z.extractall(stage)
        new = stage / "vidsum"
        init = (new / "__init__.py").read_text(encoding="utf-8") if (new / "__init__.py").is_file() else ""
        if f'__version__ = "{expect_version}"' not in init:
            raise UpdateError("Paczka aktualizacji ma inną wersję niż wydanie — przerywam.")
        old = root / "vidsum.stare"
        shutil.rmtree(old, ignore_errors=True)
        pkg.rename(old)
        try:
            new.rename(pkg)
        except OSError:
            old.rename(pkg)                                # przywróć poprzednią wersję
            raise
        for f in stage.iterdir():                          # pliki uruchamiające (VidSum Start.cmd itd.)
            if f.is_file():
                shutil.copy2(f, root / f.name)
        shutil.rmtree(old, ignore_errors=True)             # stary kod usunięty (zostaje tylko, gdy plik zajęty)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def restart_ui() -> None:
    """Uruchom program ponownie (po ~2 s, gdy ten proces już się zamknie) — bez okna konsoli."""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe") if exe.name.lower() == "python.exe" else exe
    # Bez cmd /c: Python zamienia cudzysłowy w liście argumentów na \", a cmd/start dostawał wtedy ścieżkę „\\”
    # (0.7.7 → 0.7.8: „System Windows nie może odnaleźć \\”). Nowy proces sam czeka 2 s i uruchamia program.
    code = "import time, runpy, sys; time.sleep(2); sys.argv = ['vidsum', '--ui']; runpy.run_module('vidsum', run_name='__main__')"
    args = [str(pyw if os.name == "nt" else exe), "-c", code]
    flags = (0x08000000 | 0x00000008) if os.name == "nt" else 0          # CREATE_NO_WINDOW | DETACHED_PROCESS
    subprocess.Popen(args, cwd=str(ROOT), creationflags=flags, close_fds=True)


def apply(info: dict, token: str | None = None, log=print) -> str:
    """Pobiera i instaluje aktualizację. Zwraca „kod” (trzeba uruchomić ponownie) albo „pelna” (instalator uruchomiony)."""
    token = token or token_get()                    # opcjonalny (repozytorium publiczne)
    assets = info.get("_assets") or {}
    name = info.get("plik")
    if not name or name not in assets:
        raise UpdateError("Brak pliku aktualizacji w wydaniu.")
    tmp = Path(tempfile.mkdtemp(prefix="vidsum_pobrane_"))
    dst = _download(assets[name], token, tmp / name, log)
    _sha_ok(dst, assets.get(name + ".sha256"), token)
    if info["rodzaj"] == "kod":
        swap_code(dst, info["najnowsza"])
        shutil.rmtree(tmp, ignore_errors=True)
        return "kod"
    subprocess.Popen([str(dst)], cwd=str(tmp))             # instalator sam zamknie działający VidSum
    return "pelna"


def cleanup_after_update() -> None:
    """Przy starcie: resztki po aktualizacji (gdy coś było zajęte w trakcie podmiany)."""
    for d in (ROOT / "vidsum.stare", *ROOT.glob("vidsum_akt_*")):
        shutil.rmtree(d, ignore_errors=True)
