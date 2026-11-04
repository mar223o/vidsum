"""Pakiet CUDA dla Whispera na GPU NVIDIA (Windows): cuBLAS 12 + cuDNN 9.

CTranslate2 (silnik Whispera) ma kod GPU w sobie, ale potrzebuje bibliotek NVIDIA cuBLAS i cuDNN,
których sterownik karty nie zawiera. Pobieramy je JEDNORAZOWO z oficjalnych pakietów NVIDIA na PyPI
(te same, które zaleca dokumentacja faster-whisper), sprawdzamy sumy SHA-256 i rozpakowujemy same pliki
.dll do %LOCALAPPDATA%\\VidSum\\cuda. Nic nie jest instalowane w systemie; usunięcie folderu = odinstalowanie.

Wersje dobrane do CTranslate2 4.8 (zbudowany z CUDA 12.8 i cuDNN 9.10).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

PACK = [
    {"pakiet": "nvidia-cublas-cu12", "wersja": "12.8.4.1", "rozmiar": 567544208,
     "sha256": "47e9b82132fa8d2b4944e708049229601448aaad7e6f296f630f2d1a32de35af",
     "url": "https://files.pythonhosted.org/packages/70/61/7d7b3c70186fb651d0fbd35b01dbfc8e755f69fd58f817f3d0f642df20c3/"
            "nvidia_cublas_cu12-12.8.4.1-py3-none-win_amd64.whl",
     "katalog": "nvidia/cublas/bin/"},
    {"pakiet": "nvidia-cudnn-cu12", "wersja": "9.10.2.21", "rozmiar": 692992268,
     "sha256": "c6288de7d63e6cf62988f0923f96dc339cea362decb1bf5b3141883392a7d65e",
     "url": "https://files.pythonhosted.org/packages/3d/90/0bd6e586701b3a890fd38aa71c387dab4883d619d6e5ad912ccbd05bfd67/"
            "nvidia_cudnn_cu12-9.10.2.21-py3-none-win_amd64.whl",
     "katalog": "nvidia/cudnn/bin/"},
]
MARKER = "gotowe.json"
Log = Callable[[str], None]


class CudaError(RuntimeError):
    pass


def default_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "VidSum" / "cuda"


def pack_size_gb(pack: list[dict] | None = None) -> float:
    return sum(p["rozmiar"] for p in (pack or PACK)) / 1e9


def installed(d: Path | None = None, pack: list[dict] | None = None) -> bool:
    d = Path(d or default_dir())
    try:
        m = json.loads((d / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    want = {p["pakiet"]: p["wersja"] for p in (pack or PACK)}
    return m.get("wersje") == want and all((d / f).is_file() for f in m.get("pliki", []))


_activated: set[str] = set()


def activate(d: Path | None = None, pack: list[dict] | None = None) -> bool:
    """Udostępnia pobrane biblioteki bieżącemu procesowi (przed pierwszym użyciem GPU). Idempotentne."""
    d = Path(d or default_dir())
    if not installed(d, pack):
        return False
    key = str(d.resolve())
    if key in _activated:
        return True
    # PATH: biblioteki ładowane „leniwie” przez CTranslate2 i cuDNN (LoadLibrary) szukają w PATH;
    # add_dll_directory: dla ctypes i zależności ładowanych z bezpiecznym wyszukiwaniem
    os.environ["PATH"] = key + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(key)  # type: ignore[attr-defined]
        except OSError:
            pass
    _activated.add(key)
    return True


def _download(url: str, dst: Path, size: int, sha: str, log: Log, label: str) -> None:
    h = hashlib.sha256()
    done, last = 0, -10
    tmp = dst.with_suffix(".part")
    req = urllib.request.Request(url, headers={"User-Agent": "VidSum"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            pct = int(100 * done / size) if size else 0
            if pct >= last + 10:
                last = pct
                log(f"        {label}: {pct}% z {size / 1e9:.2f} GB")
    if h.hexdigest() != sha:
        tmp.unlink(missing_ok=True)
        raise CudaError(f"Zła suma kontrolna pobranego pliku {label} — plik usunięty, spróbuj ponownie.")
    tmp.replace(dst)


def ensure(log: Log = print, d: Path | None = None, pack: list[dict] | None = None,
           force_platform: bool = False) -> Path:
    """Pobiera i rozpakowuje pakiet CUDA (jednorazowo, ~1,3 GB). Zwraca folder z bibliotekami."""
    pack = pack or PACK
    d = Path(d or default_dir())
    if installed(d, pack):
        return d
    if os.name != "nt" and not force_platform:
        raise CudaError("Automatyczne pobieranie bibliotek CUDA działa tylko na Windows "
                        "(na Linuksie zainstaluj cuBLAS 12 i cuDNN 9 z menedżera pakietów).")
    d.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(d).free
    need = int(pack_size_gb(pack) * 1e9 * 2.6)          # paczki + rozpakowane biblioteki
    if free < need:
        raise CudaError(f"Za mało miejsca na dysku na biblioteki CUDA: potrzeba ~{need / 1e9:.1f} GB, "
                        f"wolne {free / 1e9:.1f} GB.")
    log(f"        pobieram biblioteki NVIDIA dla Whispera na GPU (jednorazowo, {pack_size_gb(pack):.1f} GB)…")
    files: list[str] = []
    tmpdir = d / "_pobieranie"
    tmpdir.mkdir(exist_ok=True)
    for p in pack:
        whl = tmpdir / Path(p["url"]).name
        if not whl.is_file():
            _download(p["url"], whl, p["rozmiar"], p["sha256"], log, p["pakiet"])
        with zipfile.ZipFile(whl) as z:
            for info in z.infolist():
                name = info.filename
                if name.startswith(p["katalog"]) and name.lower().endswith(".dll") and not info.is_dir():
                    target = d / Path(name).name           # płasko, bez podkatalogów
                    with z.open(info) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out, 1 << 20)
                    files.append(target.name)
        whl.unlink(missing_ok=True)                       # paczka niepotrzebna po rozpakowaniu
    shutil.rmtree(tmpdir, ignore_errors=True)
    if not files:
        raise CudaError("W pobranych pakietach nie znaleziono bibliotek .dll.")
    (d / MARKER).write_text(json.dumps({"wersje": {p["pakiet"]: p["wersja"] for p in pack}, "pliki": sorted(files)},
                                       indent=1), encoding="utf-8")
    log(f"        biblioteki CUDA gotowe ({len(files)} plików) w {d}")
    return d


def gpu_count() -> int:
    """Liczba kart NVIDIA widocznych przez sterownik (do tego NIE są potrzebne cuBLAS/cuDNN)."""
    try:
        import ctranslate2
        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0
