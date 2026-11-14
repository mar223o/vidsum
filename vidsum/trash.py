"""Usuwanie analiz z biblioteki (0.13.2) — do Kosza, nie na zawsze.

Windows: SHFileOperationW z FO_DELETE i FOF_ALLOWUNDO, czyli zwykłe „Usuń” z Eksploratora — folder trafia do Kosza
i da się go przywrócić. Na dysku bez Kosza (np. pendrive, dysk sieciowy) Windows usuwa na stałe; dlatego interfejs
mówi „do Kosza”, a program sprawdza ten przypadek przed usunięciem i wtedy przenosi folder do własnego kosza Vidsumly
(`<folder danych>\\kosz`), żeby nic nie znikało bez śladu.
Inne systemy (testy, Linux): przeniesienie do `<folder danych>/kosz`.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

FO_DELETE = 3
FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400


def own_trash() -> Path:
    from .paths import app_dir
    return app_dir() / "kosz"


def _move_to_own(path: Path) -> str:
    dst_root = own_trash()
    dst_root.mkdir(parents=True, exist_ok=True)
    dst = dst_root / f"{path.name}_{time.strftime('%Y%m%d-%H%M%S')}"
    n = 1
    while dst.exists():
        n += 1
        dst = dst_root / f"{path.name}_{time.strftime('%Y%m%d-%H%M%S')}_{n}"
    shutil.move(str(path), str(dst))
    return "kosz_vidsumly"


def _has_recycle_bin(path: Path) -> bool:
    """Dysk lokalny (stały) ma Kosz; wymienny i sieciowy — zwykle nie (GetDriveTypeW: 3 = DRIVE_FIXED)."""
    import ctypes
    root = os.path.splitdrive(str(path.resolve()))[0] + "\\"
    return ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) == 3


def _windows_recycle(path: Path) -> None:
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    op = SHFILEOPSTRUCTW(None, FO_DELETE, str(path.resolve()) + "\0", None,
                         FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI, False, None, None)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0 or op.fAnyOperationsAborted:
        raise OSError(f"SHFileOperationW: kod {rc:#x}")


def to_trash(path: Path) -> str:
    """Folder → Kosz Windows ("kosz") albo kosz Vidsumly ("kosz_vidsumly"). Błąd → OSError (nic nie usunięte)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    if os.name == "nt":
        if _has_recycle_bin(path):
            _windows_recycle(path)
            if path.exists():
                raise OSError("folder nadal istnieje (otwarty w innym programie?)")
            return "kosz"
    return _move_to_own(path)
