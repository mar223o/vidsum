"""Wiersz poleceń:  vidsum <plik.mp4|link> [więcej…] [opcje]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .languages import normalize, parse_list
from .llm import DEFAULT_TEXT_MODEL
from .pipeline import Options, analyze


def _models_dir() -> str:
    from .gui import app_dir
    return str(app_dir() / "modele")


def main(argv: list[str] | None = None) -> int:
    if sys.stdout is None or sys.stderr is None:
        # uruchomienie bez okna (Vidsumly Start.exe / pythonw): komunikaty do pliku dziennika zamiast konsoli
        from .gui import app_dir
        logf = open(app_dir() / "vidsumly.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or logf
        sys.stderr = sys.stderr or logf
    from .tools import disable_power_throttling
    disable_power_throttling()           # program w tle nie może być spowalniany przez Windows
    for s in (sys.stdout, sys.stderr):  # polskie znaki w konsoli Windows
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["--mcp"]:                   # serwer MCP dla Claude Desktop / Claude Code
        from .mcp_server import serve_stdio
        return serve_stdio()
    if args[:1] == ["--pobierz-cuda"]:          # biblioteki NVIDIA dla Whispera na GPU (jednorazowo)
        from . import cuda
        try:
            d = cuda.ensure(print)
        except Exception as e:
            print(f"✖ {e}", file=sys.stderr)
            return 1
        cuda.activate(d)
        from .transcribe import _missing_cuda_libs
        miss = _missing_cuda_libs()
        print("✔ biblioteki CUDA załadowane" if not miss else f"✖ nie da się załadować: {', '.join(miss)}")
        print(f"  karty NVIDIA widoczne: {cuda.gpu_count()}")
        return 1 if miss else 0
    if args[:1] == ["--porownaj-modele-obrazu"]:   # te same kadry: qwen vs gemma (czas + trafność według wzorca)
        from .vision_bench import compare_models
        if len(args) < 2:
            print("Użycie: Vidsumly.exe --porownaj-modele-obrazu \"folder analizy\" [model1,model2]", file=sys.stderr)
            return 2
        models = (args[2] if len(args) > 2 else "qwen3-vl:4b-instruct@lekki,qwen3-vl:4b-instruct,gemma3:4b").split(",")
        try:
            compare_models(Path(args[1]), [m.strip() for m in models if m.strip()])
        except Exception as e:
            print(f"✖ {e}", file=sys.stderr)
            return 1
        return 0
    if args[:1] == ["--pomiar-kadrow"]:        # pomiar sposobów opisu kadrów na tej karcie graficznej
        from .vision_bench import run as bench
        if len(args) < 2:
            print("Użycie: Vidsumly.exe --pomiar-kadrow \"folder analizy\"", file=sys.stderr)
            return 2
        try:
            bench(Path(args[1]))
        except Exception as e:
            print(f"✖ {e}", file=sys.stderr)
            return 1
        return 0
    if args[:1] == ["--zmierz-czasy"]:          # 0.11.9: gdzie da się odzyskać czas — Whisper, równoległość, model tekstowy
        if len(args) < 2:
            print('Użycie: Vidsumly.exe --zmierz-czasy "folder analizy"', file=sys.stderr)
            return 2
        from .speed_bench import run as _bench
        try:
            out = _bench(Path(args[1]))
        except (OSError, ValueError, RuntimeError) as e:
            print(f"✖ {e}", file=sys.stderr)
            return 1
        print(f"✔ wynik: {out}")
        return 0
    if args[:1] == ["--kontrola"]:              # 0.12.0: automatyczna kontrola jakości gotowych analiz → jeden plik
        if len(args) < 2:
            print('Użycie: Vidsumly.exe --kontrola "folder analizy albo folder z wieloma analizami"', file=sys.stderr)
            return 2
        from .control import check_path
        try:
            out = check_path(Path(args[1]))
        except (OSError, ValueError) as e:
            print(f"✖ {e}", file=sys.stderr)
            return 1
        print(f"✔ wynik: {out}")
        return 0
    if args[:1] == ["--streszcz-ponownie"]:     # 0.12.0: samo streszczenie z zapisanej analizy (bez pobierania i kadrów)
        if len(args) < 2:
            print('Użycie: Vidsumly.exe --streszcz-ponownie "folder analizy" [model]', file=sys.stderr)
            return 2
        from .control import resummarize
        from .llm import LLMError
        try:
            out = resummarize(Path(args[1]), args[2] if len(args) > 2 else None)
        except (OSError, ValueError, LLMError) as e:
            print(f"✖ {e}", file=sys.stderr)
            return 1
        print(f"✔ wynik: {out}")
        return 0
    if args[:1] == ["--zapytaj"]:               # 0.11.5: pytanie do czatu o gotową analizę (pomiar modelu czatu)
        if len(args) < 3:
            print('Użycie: Vidsumly.exe --zapytaj "folder analizy" "pytanie" [model]', file=sys.stderr)
            return 2
        import json as _json
        import time as _time
        from .llm import LLMError, Ollama
        from .summary import build_chat_prompt, check_chat_answer
        try:
            analysis = _json.loads((Path(args[1]) / "analiza.json").read_text(encoding="utf-8"))
            eng = Ollama(args[3] if len(args) > 3 else DEFAULT_TEXT_MODEL)
            eng.ensure(lambda m: None)
            t0 = _time.time()
            from .summary import answer_moment
            ans = answer_moment(analysis, args[2]) or check_chat_answer(
                eng.complete(build_chat_prompt(analysis, args[2], [])).strip(), analysis)
        except (OSError, ValueError, LLMError) as e:
            print(f"✖ {e}", file=sys.stderr)
            return 1
        print(ans)
        print(f"\n({eng.model}, {_time.time() - t0:.1f} s)")
        return 0
    if args[:1] == ["--pobierz-model"]:         # lokalny model tekstowy do Ollamy (jednorazowo)
        from .llm import LLMError, Ollama
        try:
            Ollama(args[1] if len(args) > 1 else DEFAULT_TEXT_MODEL).ensure(print)
        except LLMError as e:
            print(f"✖ {e}", file=sys.stderr)
            return 1
        print("✔ model gotowy")
        return 0
    # Bez argumentów (dwuklik na Vidsumly.exe) albo z --ui: interfejs w przeglądarce
    if not args or args[0] == "--ui":
        try:
            from .update import cleanup_after_update
            cleanup_after_update()             # resztki po poprzedniej aktualizacji
        except Exception:
            pass
        ui = argparse.ArgumentParser(prog="vidsum --ui")
        ui.add_argument("--ui", action="store_true")
        ui.add_argument("--port", type=int, default=0)
        ui.add_argument("--bez-przegladarki", action="store_true")
        ui.add_argument("--token", default=None)
        ui.add_argument("-o", "--wyniki", default=None)
        u = ui.parse_args(args)
        from .gui import serve
        serve(u.port, not u.bez_przegladarki, u.token, Path(u.wyniki) if u.wyniki else None)
        return 0
    argv = args
    ap = argparse.ArgumentParser(prog="vidsum", description="Analiza filmu: mowa + obraz -> streszczenie ze źródłami.")
    ap.add_argument("wejscie", nargs="*", help="plik(i) wideo (MP4…) albo dźwiękowe (MP3, M4A, WAV…) albo link(i) "
                                                 "(YouTube/Instagram/TikTok)")
    ap.add_argument("--tryb", choices=["pelna", "szybki", "mowa"], default="pelna",
                    help="tryb analizy: pelna (mowa + obraz + napisy z ekranu), szybki (raport z mowy, potem wybrane kadry), "
                         "mowa (tylko mowa); plik dźwiękowy zawsze idzie trybem mowa")
    ap.add_argument("--zestaw", default=None, metavar="LISTA.txt",
                    help="plik z listą filmów (link albo ścieżka w każdej linii); po analizie powstaje zestaw_wynik.md "
                         "z czasami i kontrolą jakości wszystkich filmów")
    ap.add_argument("-o", "--wyniki", default="vidsum_wyniki", help="folder na wyniki")
    ap.add_argument("--jezyk", default="auto", help="język mowy: auto (wykryj) albo kod, np. pl, en, de, es, uk (99 języków)")
    ap.add_argument("--tlumacz", default="pl,en", help="tłumaczenia transkrypcji (oryginał zostaje zawsze): "
                    "lista kodów bez języka oryginału, domyślnie pl,en; 'brak' = bez tłumaczeń")
    ap.add_argument("--whisper", default="large-v3-turbo", help="model Whisper: small / medium / large-v3-turbo / large-v3")
    ap.add_argument("--whisper-urzadzenie", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--whisper-folder", default=None, help="gdzie trzymać pobrane modele Whisper")
    ap.add_argument("--napisy", default=None, help="gotowa transkrypcja .srt/.json zamiast Whispera")
    ap.add_argument("--obraz", choices=["ollama", "brak"], default="ollama")
    ap.add_argument("--bez-ocr", action="store_true", help="bez odczytu napisów z ekranu")
    ap.add_argument("--model-obrazu", default="qwen3-vl:4b-instruct")
    ap.add_argument("--streszczenie", choices=["auto", "ollama", "claude", "brak"], default="auto",
                    help="auto/ollama = lokalny model tekstowy (samodzielnie); claude = dodatek przez `claude -p`")
    ap.add_argument("--model-tekstowy", default=DEFAULT_TEXT_MODEL,
                    help="lokalny model do streszczenia, czatu i tłumaczeń (Ollama); pobierany przy pierwszym użyciu")
    ap.add_argument("--model-streszczenia", default=None, help=argparse.SUPPRESS)   # dawna nazwa
    ap.add_argument("--bez-pobierania-cuda", action="store_true",
                    help="nie pobieraj bibliotek NVIDIA dla Whispera na GPU (zostanie CPU)")
    ap.add_argument("--szybki-podglad", action="store_true",
                    help="wstępne streszczenie z samej mowy zaraz po transkrypcji (w programie: przełącznik obok Analizuj)")
    ap.add_argument("--ollama", default=None, help="adres Ollamy (domyślnie http://127.0.0.1:11434)")
    ap.add_argument("--max-kadrow", type=int, default=None)
    ap.add_argument("--ciasteczka-z", default=None, metavar="PRZEGLĄDARKA",
                    help="dla Instagrama/TikToka: chrome / edge / firefox")
    ap.add_argument("--allow-api-key", action="store_true", help="pozwól Claude Code użyć ANTHROPIC_API_KEY (płatne)")
    ap.add_argument("--version", action="version", version=f"Vidsumly {__version__}")
    a = ap.parse_args(argv)
    try:
        lang = normalize(a.jezyk)
        tl = parse_list(a.tlumacz)
    except ValueError as e:
        ap.error(str(e))

    opt = Options(out_root=Path(a.wyniki), language=lang, translate=tl, text_model=a.model_tekstowy,
                  cuda_download=not a.bez_pobierania_cuda, preview=a.szybki_podglad,
                  whisper_model=a.whisper, whisper_device=a.whisper_urzadzenie, whisper_root=a.whisper_folder or _models_dir(),
                  transcript_file=Path(a.napisy) if a.napisy else None, vision=a.obraz,
                  vision_model=a.model_obrazu, summary=a.streszczenie, summary_model=a.model_streszczenia,
                  ollama_host=a.ollama, max_frames=a.max_kadrow, cookies_from_browser=a.ciasteczka_z,
                  allow_api_key=a.allow_api_key, ocr=not a.bez_ocr, mode=a.tryb)
    inputs = list(a.wejscie)
    if a.zestaw:
        from .control import read_list
        try:
            inputs += read_list(Path(a.zestaw))
        except OSError as e:
            ap.error(f"nie da się odczytać listy „{a.zestaw}”: {e}")
    if not inputs:
        ap.error("podaj plik, link albo --zestaw LISTA.txt")
    failed = 0
    done: list[Path] = []
    errors: list[tuple[str, str]] = []
    for inp in inputs:
        try:
            done.append(analyze(inp, opt))
        except Exception as e:  # jeden zły plik nie zatrzymuje całej paczki
            failed += 1
            errors.append((inp, str(e)[:200]))
            print(f"✖ {inp}: {e}", file=sys.stderr)
    if len(inputs) > 1:
        print(f"Zakończono: {len(inputs) - failed}/{len(inputs)} OK")
    if a.zestaw:
        from .control import set_report
        print(f"✔ raport z zestawu: {set_report(done, Path(a.wyniki), errors)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
