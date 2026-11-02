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
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        args, capture_output=True, input=input_text.encode("utf-8") if input_text else None,
        timeout=timeout, creationflags=flags,
    )
    proc.stdout_text = proc.stdout.decode("utf-8", errors="replace")  # type: ignore[attr-defined]
    proc.stderr_text = proc.stderr.decode("utf-8", errors="replace")  # type: ignore[attr-defined]
    if check and proc.returncode != 0:
        tail = proc.stderr_text.strip().splitlines()[-5:]  # type: ignore[attr-defined]
        raise ToolError(f"Polecenie {Path(args[0]).name} zakończone kodem {proc.returncode}:\n" + "\n".join(tail))
    return proc
