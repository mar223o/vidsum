"""Narzędzia kontroli (0.12.0): sprawdzenie gotowych analiz, ponowne streszczenie bez pobierania i opisu kadrów,
raport z całego zestawu filmów — jeden plik zamiast siedmiu załączników na film.

  Vidsumly.exe --kontrola "folder analizy albo folder z wieloma analizami"
  Vidsumly.exe --streszcz-ponownie "folder analizy" [model]
  Vidsumly.exe --zestaw lista.txt -o "folder wyników"        (lista: link albo ścieżka w każdej linii, # = komentarz)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import quality
from .analysis import ts


def _load(folder: Path) -> dict:
    return json.loads((folder / "analiza.json").read_text(encoding="utf-8"))


def _folders(path: Path) -> list[Path]:
    if (path / "analiza.json").exists():
        return [path]
    return sorted((p.parent for p in path.glob("*/analiza.json")), key=lambda p: p.stat().st_mtime)


def _stage_times(c: dict) -> str:
    from .pipeline import _STAGES, _dur
    return " · ".join(f"{lab} {_dur(c[k])}" for k, lab in _STAGES if c.get(k, 0) >= 0.05)


def set_report(folders: list[Path], out: Path, failed: list[tuple[str, str]] | None = None) -> Path:
    """Jeden plik z całego zestawu: tabela (film, typ, długość, czas analizy, wynik kontroli) + uwagi do każdego filmu."""
    from .pipeline import _dur
    rows, details, data = [], [], []
    for f in folders:
        try:
            a = _load(f)
        except (OSError, ValueError) as e:
            details.append(f"### {f.name}\nNie da się odczytać analiza.json: {e}\n")
            continue
        issues = quality.check(a)
        z, c = a.get("zrodlo") or {}, a.get("czasy") or {}
        s = (a.get("streszczenie") or {}).get("dane") or {}
        dur, total = float(z.get("dlugosc_s") or 0), float(c.get("razem_s") or 0)
        mode = (a.get("ustawienia") or {}).get("tryb") or "pelna"
        title = (z.get("tytul") or f.name)[:60]
        rows.append(f"| {title} | {s.get('typ', '—')} | {mode} | {ts(dur)} | {_dur(total) if total else '—'} | "
                    f"{(total / dur):.2f}× | {quality.score(issues)} | "
                    f"{sum(1 for i in issues if i['poziom'] == 'blad')} / {sum(1 for i in issues if i['poziom'] == 'uwaga')} |")
        details.append(f"### {title}\n- folder: `{f.name}` · wersja {(a.get('narzedzie') or {}).get('wersja', '?')} · "
                       f"metoda: {s.get('metoda', '—')}\n- etapy: {_stage_times(c) or '—'}\n"
                       + quality.to_markdown("kontrola", issues))
        data.append({"folder": f.name, "tytul": z.get("tytul"), "typ": s.get("typ"), "tryb": mode, "dlugosc_s": dur,
                     "czasy": c, "wynik": quality.score(issues), "kontrola": issues,
                     "wersja": (a.get("narzedzie") or {}).get("wersja")})
    L = ["# Vidsumly — raport z zestawu filmów", "",
         f"Utworzono: {time.strftime('%Y-%m-%d %H:%M')} · filmów: {len(rows)}"
         + (f" · nieudanych: {len(failed)}" if failed else ""), "",
         "| Film | Typ | Tryb | Długość | Czas analizy | Czas / długość | Kontrola (0–100) | Błędy / uwagi |",
         "|---|---|---|---|---|---|---|---|"] + rows + [""]
    if failed:
        L += ["## Nie udało się"] + [f"- `{inp}` — {why}" for inp, why in failed] + [""]
    L += ["## Szczegóły", ""] + details
    L += ["", "_Kontrola jest automatyczna: sprawdza szablon, pokrycie filmu rozdziałami, liczby spoza filmu, obcy język, "
          "reklamy w treści, cytaty i tłumaczenie. Nie ocenia, czy streszczenie jest ciekawe — to trzeba przeczytać._"]
    out.mkdir(parents=True, exist_ok=True)
    md = out / "zestaw_wynik.md"
    md.write_text("\n".join(L) + "\n", encoding="utf-8")
    (out / "zestaw_wynik.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return md


def check_path(path: Path) -> Path:
    folders = _folders(path)
    if not folders:
        raise ValueError(f"W „{path}” nie ma żadnej analizy (pliku analiza.json).")
    return set_report(folders, path)


def read_list(file: Path) -> list[str]:
    out = []
    for line in file.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip().strip('"')
        if line and not line.startswith("#"):
            out.append(line)
    return out


def resummarize(folder: Path, model: str | None = None, log=print, engine=None) -> Path:
    """Streszczenie jeszcze raz z ZAPISANEJ analizy (transkrypcja, napisy, oś czasu) — bez pobierania, Whispera i opisu
    kadrów. Do szybkiego sprawdzania zmian w streszczaniu na tym samym filmie. Niczego nie nadpisuje:
    wynik trafia do `streszczenie_ponowne.md` / `.json` obok analizy."""
    from .llm import DEFAULT_TEXT_MODEL, Ollama
    from .story import localize
    from .summary import compact_timeline, staged_summary, tidy, to_markdown, verify_quotes
    a = _load(folder)
    z, tr = a.get("zrodlo") or {}, a.get("transkrypcja") or {}
    segs = tr.get("segmenty") or []
    dur = float(z.get("dlugosc_s") or 0)
    if engine is None:
        used = str((a.get("ustawienia") or {}).get("streszczenie") or "")
        engine = Ollama(model or (used.split(":", 1)[1] if used.startswith("ollama:") else DEFAULT_TEXT_MODEL))
        engine.ensure(lambda m: None)
    meta = "; ".join(f"{k}: {v}" for k, v in (("tytuł", z.get("tytul")), ("autor", z.get("autor")),
                                              ("długość", ts(dur))) if v)
    pl = ((tr.get("tlumaczenia") or {}).get("pl") or {}).get("segmenty")
    pl_ok = bool(pl) and len(pl) == len(segs) and all(x.get("text") for x in pl)
    trace: list = []
    t0 = time.time()
    s = staged_summary(engine, compact_timeline(a.get("os_czasu") or []), meta, dur, log, trace=trace, segments=segs,
                       ocr=a.get("napisy_ekranowe") or [], polish=[x["text"] for x in pl] if pl_ok else None)
    sec = round(time.time() - t0, 1)
    if s is None:
        raise ValueError("Model nie zwrócił poprawnego streszczenia.")
    verify_quotes(s, segs)
    tidy(s, dur, max_quotes=4 if dur < 600 else 8, max_chapters=max(6, min(12, round(dur / 300))))
    if pl:
        localize(s, segs, pl)
    new = {**a, "streszczenie": {"silnik": getattr(engine, "model", "?"), "dane": s}}
    issues = quality.check(new)
    old = quality.check(a)
    md = (f"# {z.get('tytul') or folder.name} — ponowne streszczenie\n\n"
          f"Model: {getattr(engine, 'model', '?')} · czas: {sec} s · zapytań: {len(trace)} · metoda: {s.get('metoda')}\n\n"
          + quality.to_markdown("Kontrola — nowe streszczenie", issues) + "\n"
          + quality.to_markdown("Kontrola — streszczenie zapisane w analizie", old) + "\n" + to_markdown(s))
    out = folder / "streszczenie_ponowne.md"
    out.write_text(md, encoding="utf-8")
    (folder / "streszczenie_ponowne.json").write_text(json.dumps(
        {"czas_s": sec, "kontrola": issues, "streszczenie": s, "slad": trace}, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
