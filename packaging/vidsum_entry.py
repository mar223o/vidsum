"""Punkt wejścia dla PyInstaller: bez argumentów → interfejs, z argumentami → wiersz poleceń."""
import multiprocessing

from vidsum.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
