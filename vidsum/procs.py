"""Procesy potomne programu (0.11.0): nic nie zostaje po zamknięciu okna.

- Windows: cały program jest w obiekcie zadania (Job Object) z „zabij przy zamknięciu”. Gdy proces programu się
  kończy (także twardo, przez Menedżera zadań), Windows kończy wszystkie jego procesy potomne: ffmpeg, ffprobe,
  ffmpeg uruchomiony przez yt-dlp. Usługi, których program nie uruchomił (Ollama), nie są w tym zadaniu.
- Wszędzie: rejestr procesów uruchomionych przez `tools.run` — przy zamykaniu kończone jawnie, zanim program wyjdzie.
- Procesy, które MAJĄ przeżyć program (nowa instancja po aktualizacji, instalator, okno Edge, Eksplorator), startują
  z `DETACHED` — poza obiektem zadania.
"""
from __future__ import annotations

import os
import subprocess
import threading

_lock = threading.Lock()
_children: set[subprocess.Popen] = set()
_job_handle = None
closing = threading.Event()          # program się zamyka: nowe procesy nie startują

# CREATE_BREAKAWAY_FROM_JOB — proces poza obiektem zadania (przeżyje zamknięcie programu)
DETACHED = 0x01000000 if os.name == "nt" else 0


def popen_detached(args, creationflags: int = 0, **kw) -> subprocess.Popen:
    """Proces, który ma przeżyć program (poza obiektem zadania); gdy system nie pozwala — zwykły start."""
    if DETACHED:
        try:
            return subprocess.Popen(args, creationflags=creationflags | DETACHED, **kw)
        except OSError:
            pass
    return subprocess.Popen(args, creationflags=creationflags, **kw)


def register(p: subprocess.Popen) -> None:
    with _lock:
        _children.add(p)


def unregister(p: subprocess.Popen) -> None:
    with _lock:
        _children.discard(p)


def running() -> list[subprocess.Popen]:
    with _lock:
        return [p for p in _children if p.poll() is None]


def kill_all(timeout: float = 3.0) -> int:
    """Kończy wszystkie zarejestrowane procesy potomne: najpierw grzecznie, po `timeout` s twardo. Zwraca ich liczbę."""
    procs = running()
    for p in procs:
        try:
            p.terminate()
        except OSError:
            pass
    for p in procs:
        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                p.kill()
                p.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
    return len(procs)


def setup_kill_on_close() -> bool:
    """Windows: przypisuje bieżący proces do obiektu zadania z JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x2000)
    i BREAKAWAY_OK (0x800). Uchwyt trzymamy do końca życia programu — jego zamknięcie przez system kończy dzieci."""
    global _job_handle
    if os.name != "nt" or _job_handle:
        return bool(_job_handle)
    try:
        import ctypes
        from ctypes import wintypes

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class EXT(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        h = k32.CreateJobObjectW(None, None)
        if not h:
            return False
        info = EXT()
        info.Basic.LimitFlags = 0x2000 | 0x800          # KILL_ON_JOB_CLOSE | BREAKAWAY_OK
        if not k32.SetInformationJobObject(h, 9, ctypes.byref(info), ctypes.sizeof(info)):   # ExtendedLimitInformation
            return False
        if not k32.AssignProcessToJobObject(h, k32.GetCurrentProcess()):
            return False
        _job_handle = h
        return True
    except Exception:
        return False
