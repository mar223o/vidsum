"""Wiersz poleceń:  vidsum <plik.mp4|link> [więcej…] [opcje]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .pipeline import Options, analyze


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):  # polskie znaki w konsoli Windows
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="vidsum", description="Analiza filmu: mowa + obraz -> streszczenie ze źródłami.")
    ap.add_argument("wejscie", nargs="+", help="plik(i) MP4 albo link(i) (YouTube/Instagram/TikTok)")
    ap.add_argument("-o", "--wyniki", default="vidsum_wyniki", help="folder na wyniki")
    ap.add_argument("--jezyk", choices=["auto", "pl", "en"], default="auto")
    ap.add_argument("--whisper", default="small", help="model Whisper: tiny/base/small/medium/large-v3")
    ap.add_argument("--whisper-urzadzenie", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--whisper-folder", default=None, help="gdzie trzymać pobrane modele Whisper")
    ap.add_argument("--napisy", default=None, help="gotowa transkrypcja .srt/.json zamiast Whispera")
    ap.add_argument("--obraz", choices=["ollama", "brak"], default="ollama")
    ap.add_argument("--model-obrazu", default="qwen3-vl:4b-instruct")
    ap.add_argument("--streszczenie", choices=["auto", "ollama", "claude", "brak"], default="auto",
                    help="auto = Claude Code (Pro), jeśli zainstalowany, inaczej Ollama; claude = `claude -p`")
    ap.add_argument("--model-streszczenia", default=None)
    ap.add_argument("--ollama", default=None, help="adres Ollamy (domyślnie http://127.0.0.1:11434)")
    ap.add_argument("--max-kadrow", type=int, default=None)
    ap.add_argument("--ciasteczka-z", default=None, metavar="PRZEGLĄDARKA",
                    help="dla Instagrama/TikToka: chrome / edge / firefox")
    ap.add_argument("--allow-api-key", action="store_true", help="pozwól Claude Code użyć ANTHROPIC_API_KEY (płatne)")
    ap.add_argument("--version", action="version", version=f"VidSum {__version__}")
    a = ap.parse_args(argv)

    opt = Options(out_root=Path(a.wyniki), language=None if a.jezyk == "auto" else a.jezyk,
                  whisper_model=a.whisper, whisper_device=a.whisper_urzadzenie, whisper_root=a.whisper_folder,
                  transcript_file=Path(a.napisy) if a.napisy else None, vision=a.obraz,
                  vision_model=a.model_obrazu, summary=a.streszczenie, summary_model=a.model_streszczenia,
                  ollama_host=a.ollama, max_frames=a.max_kadrow, cookies_from_browser=a.ciasteczka_z,
                  allow_api_key=a.allow_api_key)
    failed = 0
    for inp in a.wejscie:
        try:
            analyze(inp, opt)
        except Exception as e:  # jeden zły plik nie zatrzymuje całej paczki
            failed += 1
            print(f"✖ {inp}: {e}", file=sys.stderr)
    if len(a.wejscie) > 1:
        print(f"Zakończono: {len(a.wejscie) - failed}/{len(a.wejscie)} OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
