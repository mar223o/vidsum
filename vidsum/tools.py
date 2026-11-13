"""Wyszukiwanie ffmpeg/ffprobe i bezpieczne uruchamianie procesów (polskie znaki w ścieżkach)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


class ToolError(RuntimeError):
    pass


def _candidates(name: str) -> list[Path]:
    exe = name + (".exe" if os.name == "nt" else "")
    out: list[Path] = []
    env = os.environ.get("VIDSUM_" + name.upper())
    if env:
        out.append(Path(env))
    # Folder z programem (.exe po spakowaniu) oraz katalog projektu: ./bin/ffmpeg.exe
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    out += [base / "bin" / exe, Path(sys.executable).resolve().parent / "bin" / exe]
    found = shutil.which(name)
    if found:
        out.append(Path(found))
    return out


def find_tool(name: str) -> str:
    for p in _candidates(name):
        if p.is_file():
            return str(p)
    raise ToolError(
        f"Nie znaleziono '{name}'. Umieść {name}.exe w folderze 'bin' obok programu "
        f"albo ustaw zmienną VIDSUM_{name.upper()}."
    )


def run(args: list[str], *, check: bool = True, input_text: str | None = None,
        timeout: float | None = None) -> subprocess.CompletedProcess:
    """Uruchamia proces z listą argumentów (bez powłoki) i dekoduje wyjście jako UTF-8.

    Lista argumentów (zamiast jednego stringa) sprawia, że ścieżki z polskimi znakami
    i spacjami przechodzą bez cytowania — na Windows przez CreateProcessW.
    """
    from . import procs
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if procs.closing.is_set():
        raise ToolError("Program się zamyka — nie uruchamiam nowych procesów.")
    # Popen + rejestr (zamiast subprocess.run): przy zamykaniu programu proces jest kończony, nie zostaje sierotą
    p = subprocess.Popen(args, stdin=subprocess.PIPE if input_text else None, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, creationflags=flags)
    procs.register(p)
    try:
        out, err = p.communicate(input_text.encode("utf-8") if input_text else None, timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        raise
    finally:
        procs.unregister(p)
    proc = subprocess.CompletedProcess(args, p.returncode, out, err)
    proc.stdout_text = proc.stdout.decode("utf-8", errors="replace")  # type: ignore[attr-defined]
    proc.stderr_text = proc.stderr.decode("utf-8", errors="replace")  # type: ignore[attr-defined]
    if check and proc.returncode != 0:
        tail = proc.stderr_text.strip().splitlines()[-5:]  # type: ignore[attr-defined]
        raise ToolError(f"Polecenie {Path(args[0]).name} zakończone kodem {proc.returncode}:\n" + "\n".join(tail))
    return proc


def disable_power_throttling() -> bool:
    """Windows 11 potrafi spowalniać procesy działające w tle bez okna (EcoQoS / „power throttling”) —
    a Vidsumly Start działa właśnie tak. Wyłączamy to dla naszego procesu (dotyczy też wątków OCR/Whisper)."""
    import os
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class PPTS(ctypes.Structure):           # PROCESS_POWER_THROTTLING_STATE
            _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE            # uchwyt 64-bitowy (inaczej ucięty do int)
        k32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.SetProcessInformation.restype = wintypes.BOOL
        k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        me = k32.GetCurrentProcess()
        ok = False
        for mask in (0x1 | 0x4, 0x1):         # EXECUTION_SPEED (+ IGNORE_TIMER_RESOLUTION, Win11) → wyłączone
            state = PPTS(1, mask, 0)
            if k32.SetProcessInformation(me, 4, ctypes.byref(state), ctypes.sizeof(state)):
                ok = True
                break
        k32.SetPriorityClass(me, 0x00000020)   # NORMAL_PRIORITY_CLASS
        return ok
    except Exception:
        return False
