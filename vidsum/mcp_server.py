"""Serwer MCP (stdio, JSON-RPC 2.0) — Claude Desktop / Claude Code wywołuje VidSum na tym komputerze.

Uruchomienie: VidSum.exe --mcp   (albo VidSum.cmd --mcp, python -m vidsum --mcp)
Bez zewnętrznych bibliotek. Na stdout idą WYŁĄCZNIE wiadomości protokołu; logi analizy → stderr.

Narzędzia:
- analizuj_film(zrodlo, jezyk?) — pełna analiza lokalnie (OCR + Whisper + kadry + model obrazu), zwraca oś czasu,
  transkrypcję i napisy z ekranu; streszczenie pisze sam Claude na tej podstawie (bez zagnieżdżonego wywołania).
- lista_analiz() — analizy zapisane na dysku (Biblioteka).
- pobierz_analize(folder) — oś czasu + streszczenie zapisanej analizy.
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from . import __version__
from .analysis import beats_as_text, ts

PROTOCOL = "2025-06-18"

TOOLS = [
    {"name": "analizuj_film",
     "description": ("Analizuje film lokalnie programem VidSum (plik na tym komputerze albo link YouTube/Instagram/TikTok): "
                     "napisy z ekranu (OCR), mowa (Whisper large-v3-turbo), kadry i ich opisy. Zwraca oś czasu ze źródłami "
                     "(MOWA / NAPISY / OBRAZ). Trwa od ~1 min (krótki film) do kilkunastu minut (40 min)."),
     "inputSchema": {"type": "object", "properties": {
         "zrodlo": {"type": "string", "description": "Pełna ścieżka do pliku wideo albo link"},
         "jezyk": {"type": "string", "enum": ["auto", "pl", "en"], "default": "auto"}},
         "required": ["zrodlo"]}},
    {"name": "lista_analiz",
     "description": "Lista analiz zapisanych przez VidSum na tym komputerze (tytuł, typ, długość, folder).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "pobierz_analize",
     "description": "Zwraca oś czasu, transkrypcję i streszczenie zapisanej analizy (folder z lista_analiz).",
     "inputSchema": {"type": "object", "properties": {"folder": {"type": "string"}}, "required": ["folder"]}},
]


def _results_root() -> Path:
    """Folder wyników taki sam jak w interfejsie (ustawienie „Folder wyników”)."""
    from .gui import app_dir, default_results_dir
    try:
        saved = json.loads((app_dir() / "ustawienia.json").read_text(encoding="utf-8"))
        return Path(saved.get("wyniki") or default_results_dir())
    except Exception:
        return default_results_dir()


def _describe(folder: Path, full: bool = True) -> str:
    r = json.loads((folder / "analiza.json").read_text(encoding="utf-8"))
    z = r["zrodlo"]
    st = r.get("streszczenie") or {}
    head = [f"Folder: {folder}", f"Tytuł: {z.get('tytul') or z.get('plik')}", f"Długość: {ts(z.get('dlugosc_s', 0))}",
            f"Język mowy: {r['transkrypcja'].get('jezyk')}", f"Silniki: {r['ustawienia'].get('whisper')} · {r['ustawienia'].get('obraz')}",
            "Ograniczenia: " + ("; ".join(r.get("luki", [])) or "—")]
    if not full:
        return "\n".join(head)
    parts = ["\n".join(head)]
    if st.get("markdown"):
        parts.append("STRESZCZENIE (zapisane):\n" + st["markdown"])
    parts.append("OŚ CZASU (MOWA = transkrypcja, NAPISY = OCR z ekranu, OBRAZ = opis kadru małym modelem):\n"
                 + beats_as_text(r.get("os_czasu", [])))
    return "\n\n".join(parts)


def _call(name: str, args: dict) -> str:
    if name == "lista_analiz":
        root = _results_root()
        rows = []
        for f in sorted(root.glob("*/analiza.json"), key=lambda p: -p.stat().st_mtime)[:100]:
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
                d = ((r.get("streszczenie") or {}).get("dane") or {})
                rows.append(f"- {d.get('tytul') or r['zrodlo'].get('tytul') or r['zrodlo'].get('plik')} "
                            f"[{d.get('typ', '?')}, {ts(r['zrodlo'].get('dlugosc_s', 0))}] — {f.parent}")
            except Exception:
                continue
        return f"Folder wyników: {root}\n" + ("\n".join(rows) or "Brak zapisanych analiz.")
    if name == "pobierz_analize":
        folder = Path(args["folder"]).expanduser()
        if not (folder / "analiza.json").is_file():
            raise ValueError(f"Brak analiza.json w {folder}")
        return _describe(folder)
    if name == "analizuj_film":
        from .pipeline import Options, analyze
        from .gui import app_dir
        # streszczenie i tłumaczenie robi Claude (to on wywołuje narzędzie) — lokalnie tylko mowa, obraz, napisy
        opt = Options(out_root=_results_root(), language=None if args.get("jezyk", "auto") == "auto" else args["jezyk"],
                      whisper_root=str(app_dir() / "modele"), summary="brak", translate=[])
        from .llm import LLMError, Ollama
        try:
            Ollama(opt.vision_model).check()
        except LLMError:
            opt.vision = "brak"     # bez Ollamy: mowa + napisy z ekranu; brak opisu kadrów trafi do luk
        out = analyze(args["zrodlo"], opt, log=lambda m: print(m, file=sys.stderr, flush=True))
        return _describe(out) + ("\n\nNapisz teraz streszczenie według procedury VidSum: typ filmu, co masz zrobić "
                                 "(przepis/trening/kroki z mm:ss), najważniejsze, rozdziały, cytaty, szczera ocena, "
                                 "czego nie wiadomo; źródło przy każdej informacji.")
    raise ValueError(f"Nieznane narzędzie: {name}")


def handle(msg: dict) -> dict | None:
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:                                    # powiadomienie (np. notifications/initialized)
        return None
    try:
        if method == "initialize":
            ver = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL
            res = {"protocolVersion": ver, "capabilities": {"tools": {}},
                   "serverInfo": {"name": "vidsum", "version": __version__}}
        elif method == "tools/list":
            res = {"tools": TOOLS}
        elif method == "tools/call":
            p = msg.get("params") or {}
            try:
                res = {"content": [{"type": "text", "text": _call(p.get("name"), p.get("arguments") or {})}], "isError": False}
            except Exception as e:                     # błąd narzędzia → wynik z isError (Claude go zobaczy)
                traceback.print_exc(file=sys.stderr)
                res = {"content": [{"type": "text", "text": f"Błąd: {type(e).__name__}: {e}"}], "isError": True}
        elif method == "ping":
            res = {}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": mid, "result": res}
    except Exception as e:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}}


def serve_stdio() -> int:
    out = sys.stdout
    try:
        sys.stdin.reconfigure(encoding="utf-8")     # type: ignore[attr-defined]
        out.reconfigure(encoding="utf-8")           # type: ignore[attr-defined]
    except Exception:
        pass
    sys.stdout = sys.stderr                         # każdy przypadkowy print trafia do logów, nie do protokołu
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            out.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}) + "\n")
            out.flush()
            continue
        reply = handle(msg)
        if reply is not None:
            out.write(json.dumps(reply, ensure_ascii=False) + "\n")
            out.flush()
    return 0
