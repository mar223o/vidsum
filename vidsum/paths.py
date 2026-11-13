"""Foldery programu i danych — nazwa „Vidsumly” (0.13.0; wcześniej „VidSum”).

Do 0.12.0 program trzymał dane w `%LOCALAPPDATA%\\VidSum` (ustawienia, kolejka, modele Whisper, biblioteki CUDA, klucz
okna) i wyniki w `Dokumenty\\VidSum`. Od 0.13.0 foldery nazywają się `Vidsumly`. Przy pierwszym uruchomieniu stary folder
jest PRZENOSZONY (zmiana nazwy na tym samym dysku — trwa ułamek sekundy, nic nie jest kopiowane ani kasowane). Gdy
przeniesienie się nie uda (plik zajęty przez starą wersję programu), program dalej używa starego folderu i spróbuje przy
następnym uruchomieniu — żadne dane nie giną.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

NAME = "Vidsumly"
OLD_NAME = "VidSum"


def _base() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share"))


def migrate(old: Path, new: Path) -> Path:
    """Folder do użycia: nowy; stary przeniesiony pod nową nazwę, jeśli jest, a nowego jeszcze nie ma."""
    if new.exists() or not old.is_dir():
        return new
    try:
        old.rename(new)
        return new
    except OSError:                                    # zajęty (działa stara wersja) — zostajemy przy starym
        return old


def app_dir() -> Path:
    p = migrate(_base() / OLD_NAME, _base() / NAME)
    p.mkdir(parents=True, exist_ok=True)
    return p


def documents() -> Path:
    docs = Path.home() / "Documents"
    return docs if docs.is_dir() else Path.home()


def default_results_dir() -> Path:
    old, new = documents() / OLD_NAME, documents() / NAME
    got = migrate(old, new)
    if got == new and not old.exists():
        fix_saved_paths(app_dir(), old, new)
    return got


def fix_saved_paths(app: Path, old: Path, new: Path) -> int:
    """Po przeniesieniu wyników: ścieżki do starego folderu w ustawieniach i kolejce → nowy folder. Zwraca liczbę plików."""
    n = 0
    for name in ("ustawienia.json", "kolejka.json"):
        f = app / name
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        # ścieżki w JSON są zapisane z podwójnym „\\” — podmieniamy obie postacie
        new_text = text
        for o, nw in ((str(old), str(new)), (json.dumps(str(old))[1:-1], json.dumps(str(new))[1:-1])):
            new_text = new_text.replace(o, nw)
        if new_text != text:
            f.write_text(new_text, encoding="utf-8")
            n += 1
    return n
