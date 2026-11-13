"""Ikona Vidsumly na pasku zadań, w przypiętych skrótach i na pulpicie (Windows).

Dlaczego przypięta ikona zmieniała się w logo Pythona: program to pythonw.exe z argumentami „-m vidsum --ui”.
Okno ma własny identyfikator aplikacji (AppUserModelID „Vidsumly.Aplikacja”), ale bez właściwości „relaunch”
Windows przy przypinaniu bierze ikonę pliku wykonywalnego procesu, czyli pythonw.exe — dokumentacja Microsoftu
(System.AppUserModel.RelaunchIconResource): „If an explicit AppUserModelID is set but this property isn't, the system
looks for a shortcut with the same AppUserModelID … If none is found, the owning process's backing executable is used”.

Naprawa (0.13.1):
- oknu ustawiamy ID + RelaunchCommand + RelaunchDisplayNameResource + RelaunchIconResource (SHGetPropertyStoreForWindow),
- skróty (Menu Start, pulpit, przypięte na pasku) dostają ten sam AppUserModelID i ikonę,
- ikona leży w stałym pliku poza folderem „vidsum” ({app}\\Vidsumly.ico), bo aktualizacja kodu podmienia ten folder.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

APP_ID = "Vidsumly.Aplikacja"
ICON_NAME = "Vidsumly.ico"
DISPLAY_NAME = "Vidsumly"
# PKEY_AppUserModel_* (propkey.h): formatID 9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3
FMTID = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
PID_RELAUNCH_COMMAND, PID_RELAUNCH_ICON, PID_RELAUNCH_NAME, PID_ID = 2, 3, 4, 5

IID_IPropertyStore = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
IID_IPersistFile = "{0000010B-0000-0000-C000-000000000046}"
IID_IShellLinkW = "{000214F9-0000-0000-C000-000000000046}"
CLSID_ShellLink = "{00021401-0000-0000-C000-000000000046}"
VT_EMPTY, VT_LPWSTR = 0, 31


def package_icon() -> Path:
    return Path(__file__).resolve().parent / "web" / "vidsum.ico"


def install_root() -> Path:
    """Folder instalacji ({app}): nad pakietem „vidsum”."""
    return Path(__file__).resolve().parent.parent


def stable_icon(dirs: list[Path] | None = None) -> Path:
    """Kopia ikony poza pakietem „vidsum” (przeżywa podmianę kodu przy aktualizacji). Odświeżana, gdy ikona
    w pakiecie się zmieni. Gdy żadnego folderu nie da się zapisać — ikona z pakietu."""
    src = package_icon()
    try:
        data = src.read_bytes()
    except OSError:
        return src
    if dirs is None:
        from .paths import app_dir
        dirs = [install_root(), app_dir()]
    for d in dirs:
        dst = Path(d) / ICON_NAME
        try:
            if not dst.is_file() or dst.read_bytes() != data:
                d.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_suffix(".ico.tmp")
                tmp.write_bytes(data)
                os.replace(tmp, dst)
            return dst
        except OSError:
            continue
    return src


def launcher() -> Path:
    """pythonw.exe obok bieżącego interpretera (okno bez konsoli)."""
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.is_file() else exe


def relaunch_command(exe: Path | None = None) -> str:
    return f'"{exe or launcher()}" -m vidsum --ui'


def is_vidsum_link(target: str, args: str) -> bool:
    """Skrót do Vidsumly: argumenty z „vidsum” albo pythonw.exe z folderu, w którym obok jest pakiet vidsum
    (przypięcie okna sprzed 0.13.1 tworzyło skrót do samego pythonw.exe — bez argumentów i z ikoną Pythona)."""
    if "vidsum" in (args or "").lower():
        return True
    t = Path(target or "")
    return t.name.lower() in ("pythonw.exe", "python.exe") and (t.parent.parent / "vidsum" / "__init__.py").is_file()


# ---------------------------------------------------------------- COM przez ctypes (tylko Windows)

@lru_cache(maxsize=None)
def _com():
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort), ("d4", ctypes.c_ubyte * 8)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):       # vt + 3 × reserved + unia (16 B na x64)
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                    ("r3", ctypes.c_ushort), ("p", ctypes.c_void_p), ("p2", ctypes.c_void_p)]

    ole32 = ctypes.OleDLL("ole32")

    def guid(s: str) -> GUID:
        g = GUID()
        ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g))
        return g

    def method(ptr, idx: int, *argtypes):
        vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        fn = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtbl[idx])
        return lambda *a: fn(ptr, *a)

    def release(ptr) -> None:
        if ptr:
            vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])(ptr)

    def init() -> None:
        ctypes.windll.ole32.CoInitializeEx(None, 2)     # STA; „już zainicjowane” (S_FALSE / RPC_E_CHANGED_MODE) — ok

    return SimpleNamespace(ctypes=ctypes, PROPERTYKEY=PROPERTYKEY, PROPVARIANT=PROPVARIANT, ole32=ole32, guid=guid,
                           method=method, release=release, init=init)


def _store_set(store, values: dict[int, str]) -> None:
    c = _com()
    ctypes, PROPERTYKEY, PROPVARIANT, guid, method = c.ctypes, c.PROPERTYKEY, c.PROPVARIANT, c.guid, c.method
    set_value = method(store, 6, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))
    keep = []
    for pid, text in values.items():
        buf = ctypes.create_unicode_buffer(text)
        keep.append(buf)
        pv = PROPVARIANT(vt=VT_LPWSTR, p=ctypes.cast(buf, ctypes.c_void_p).value)
        set_value(ctypes.byref(PROPERTYKEY(guid(FMTID), pid)), ctypes.byref(pv))
    try:
        method(store, 7)()                              # Commit
    except OSError:
        pass


def _store_get(store, pid: int) -> str | None:
    c = _com()
    ctypes, PROPERTYKEY, PROPVARIANT, guid, method = c.ctypes, c.PROPERTYKEY, c.PROPVARIANT, c.guid, c.method
    ole32 = c.ole32
    pv = PROPVARIANT()
    method(store, 5, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))(
        ctypes.byref(PROPERTYKEY(guid(FMTID), pid)), ctypes.byref(pv))
    try:
        return ctypes.wstring_at(pv.p) if pv.vt == VT_LPWSTR and pv.p else None
    finally:
        ole32.PropVariantClear(ctypes.byref(pv))


def _window_store(hwnd: int):
    c = _com()
    ctypes, guid = c.ctypes, c.guid
    c.init()
    store = ctypes.c_void_p()
    ctypes.OleDLL("shell32").SHGetPropertyStoreForWindow(ctypes.c_void_p(hwnd), ctypes.byref(guid(IID_IPropertyStore)),
                                                          ctypes.byref(store))
    return store


def set_window_props(hwnd: int, icon: Path, command: str | None = None) -> None:
    """Okno: ID + dane do przypięcia (polecenie, nazwa, ikona). Kolejność jak w przykładach Microsoftu:
    najpierw właściwości „relaunch”, ID na końcu."""
    release = _com().release
    store = _window_store(hwnd)
    try:
        _store_set(store, {PID_RELAUNCH_COMMAND: command or relaunch_command(),
                           PID_RELAUNCH_NAME: DISPLAY_NAME,
                           PID_RELAUNCH_ICON: f"{icon},0",
                           PID_ID: APP_ID})
    finally:
        release(store)


def get_window_props(hwnd: int) -> dict[int, str | None]:
    release = _com().release
    store = _window_store(hwnd)
    try:
        return {pid: _store_get(store, pid) for pid in (PID_RELAUNCH_COMMAND, PID_RELAUNCH_ICON, PID_RELAUNCH_NAME, PID_ID)}
    finally:
        release(store)


def _open_link(path: Path):
    c = _com()
    ctypes, ole32, guid, method = c.ctypes, c.ole32, c.guid, c.method
    c.init()
    pf = ctypes.c_void_p()
    ole32.CoCreateInstance(ctypes.byref(guid(CLSID_ShellLink)), None, 1, ctypes.byref(guid(IID_IPersistFile)),
                           ctypes.byref(pf))
    method(pf, 5, ctypes.c_wchar_p, ctypes.c_ulong)(str(path), 2)     # IPersistFile::Load, STGM_READWRITE
    return pf


def _qi(ptr, iid: str):
    c = _com()
    ctypes, guid, method = c.ctypes, c.guid, c.method
    out = ctypes.c_void_p()
    method(ptr, 0, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(guid(iid)), ctypes.byref(out))
    return out


def read_link(path: Path) -> dict:
    """Cel, argumenty, ikona i AppUserModelID skrótu .lnk."""
    c = _com()
    ctypes, method, release = c.ctypes, c.method, c.release
    pf = _open_link(path)
    sl = store = None
    try:
        sl = _qi(pf, IID_IShellLinkW)
        buf = ctypes.create_unicode_buffer(1024)
        method(sl, 3, ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong)(buf, 1024, None, 0)  # GetPath
        target = buf.value
        method(sl, 10, ctypes.c_wchar_p, ctypes.c_int)(buf, 1024)                                        # GetArguments
        args = buf.value
        idx = ctypes.c_int()
        method(sl, 16, ctypes.c_wchar_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int))(buf, 1024, ctypes.byref(idx))
        icon = buf.value                                                                              # GetIconLocation
        store = _qi(pf, IID_IPropertyStore)
        return {"cel": target, "argumenty": args, "ikona": icon, "indeks": idx.value, "id": _store_get(store, PID_ID)}
    finally:
        release(store)
        release(sl)
        release(pf)


def fix_link(path: Path, icon: Path) -> bool:
    """Skrót Vidsumly → nasza ikona i AppUserModelID (a skrót do gołego pythonw.exe dostaje też argumenty).
    Zwraca True, gdy skrót był do Vidsumly i został zapisany."""
    c = _com()
    ctypes, method, release = c.ctypes, c.method, c.release
    pf = _open_link(path)
    sl = store = None
    try:
        sl = _qi(pf, IID_IShellLinkW)
        buf = ctypes.create_unicode_buffer(1024)
        method(sl, 3, ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong)(buf, 1024, None, 0)
        target = buf.value
        method(sl, 10, ctypes.c_wchar_p, ctypes.c_int)(buf, 1024)
        args = buf.value
        if not is_vidsum_link(target, args):
            return False
        if "vidsum" not in args.lower():
            method(sl, 11, ctypes.c_wchar_p)("-m vidsum --ui")                                # SetArguments
            method(sl, 9, ctypes.c_wchar_p)(str(Path(target).parent.parent))                 # SetWorkingDirectory
        method(sl, 17, ctypes.c_wchar_p, ctypes.c_int)(str(icon), 0)                         # SetIconLocation
        store = _qi(pf, IID_IPropertyStore)
        _store_set(store, {PID_ID: APP_ID})
        method(pf, 6, ctypes.c_wchar_p, ctypes.c_int)(None, 1)                               # IPersistFile::Save
        return True
    finally:
        release(store)
        release(sl)
        release(pf)


def shortcut_paths() -> list[Path]:
    appdata = Path(os.environ.get("APPDATA", ""))
    start = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    desk = Path.home() / "Desktop"
    pins = appdata / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned" / "TaskBar"
    out = [start / n / f"{n}.lnk" for n in ("Vidsumly", "VidSum", "Vidento")]
    out += [desk / f"{n}.lnk" for n in ("Vidsumly", "VidSum", "Vidento")]
    try:
        out += sorted(pins.glob("*.lnk"))
    except OSError:
        pass
    return [p for p in out if p.is_file()]


def fix_all(icon: Path) -> list[Path]:
    """Poprawia wszystkie znalezione skróty Vidsumly; błąd jednego skrótu nie zatrzymuje reszty."""
    done = []
    for p in shortcut_paths():
        try:
            if fix_link(p, icon):
                done.append(p)
        except OSError:
            continue
    if done:
        try:                                            # odśwież ikony w Eksploratorze (SHCNE_ASSOCCHANGED)
            import ctypes
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
        except Exception:
            pass
    return done
