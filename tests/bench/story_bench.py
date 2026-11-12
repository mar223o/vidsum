"""Pomiar streszczania na PRAWDZIWYM modelu dla filmów z komputera użytkownika (0.11.9): tortilla (PL), pancake touch
(sport), reel modowy (inne), dokument 24:50. Dane: tests/data/filmy_0119/*.json (transkrypcja, napisy z ekranu, sceny).

Przebieg jak w programie: streszczenie (tłumaczenie jeszcze niegotowe) → tłumaczenie linii → fakty po polsku z tłumaczenia
→ kontrola jakości (vidsum/quality.py). Wynik: <film>.md (raport + kontrola), <film>.json (dane, ślad zapytań, czasy).

python tests/bench/story_bench.py gemma3:4b --film dokument_ambasada --wyniki wyniki
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from vidsum import quality  # noqa: E402
from vidsum.llm import Ollama  # noqa: E402
from vidsum.story import localize  # noqa: E402
from vidsum.summary import SPORT_TERMS, staged_summary, tidy, to_markdown, type_from_content, verify_quotes  # noqa: E402
from vidsum.translate import translate_segments  # noqa: E402

DATA = ROOT / "tests" / "data" / "filmy_0119"


def beats_from(d: dict) -> list[dict]:
    """Oś czasu jak w programie: odcinek = od kadru do następnego kadru; w nim mowa, napisy z ekranu i scena."""
    dur = float(d["zrodlo"]["dlugosc_s"])
    frames = sorted(d.get("kadry") or [], key=lambda k: k["t"]) or [{"t": 0.0, "scena": ""}]
    cuts = [0.0] + [(a["t"] + b["t"]) / 2 for a, b in zip(frames, frames[1:])] + [dur]
    beats = []
    for i, fr in enumerate(frames):
        a, b = cuts[i], cuts[i + 1]
        heard = " ".join(s["text"] for s in d["segmenty"] if a <= s["start"] < b)
        seen: list[str] = []
        for o in d.get("napisy_ekranowe") or []:
            if a <= o["start"] < b and o["text"] not in seen:
                seen.append(o["text"])
        beats.append({"start": round(a, 2), "end": round(b, 2), "kadr": "", "napisy": " | ".join(seen),
                      "widac": {"zrodlo": "obraz", "scena": fr.get("scena") or "", "czynnosci": [], "obiekty": []},
                      "slychac": {"zrodlo": "mowa" if heard else "brak_danych", "tekst": heard}})
    return beats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--film", required=True)
    ap.add_argument("--wyniki", default="wyniki")
    ap.add_argument("--bez-tlumaczenia", action="store_true")
    a = ap.parse_args()
    from vidsum.summary import compact_timeline
    d = json.loads((DATA / f"{a.film}.json").read_text(encoding="utf-8"))
    # jak w programie: długie zdania z przecinkami dzielone przed streszczeniem (tłumaczenie z 0.11.9 wtedy nie pasuje)
    from vidsum.transcribe import Segment, split_long_segments
    split = [{"start": x.start, "end": x.end, "text": x.text} for x in split_long_segments([Segment(**x) for x in d["segmenty"]])]
    if len(split) != len(d["segmenty"]):
        print(f"długie zdania podzielone: {len(d['segmenty'])} → {len(split)} linii", flush=True)
        d["segmenty"], d["pl"] = split, None
    out = Path(a.wyniki)
    out.mkdir(parents=True, exist_ok=True)
    eng = Ollama(a.model, timeout=3600)
    eng.ensure(print)
    dur = float(d["zrodlo"]["dlugosc_s"])
    beats = beats_from(d)
    tl = compact_timeline(beats)
    meta = "; ".join(f"{k}: {v}" for k, v in (("tytuł", d["zrodlo"].get("tytul")), ("autor", d["zrodlo"].get("autor"))) if v)
    trace: list = []
    log: list[str] = []

    def say(x: str) -> None:
        log.append(x)
        print(x, flush=True)

    t0 = time.time()
    s = staged_summary(eng, tl, meta, dur, say, trace=trace, segments=d["segmenty"], ocr=d.get("napisy_ekranowe") or [])
    t_sum = round(time.time() - t0, 1)
    pl_segs, failed, t_tr = None, 0, 0.0
    if not a.bez_tlumaczenia and d.get("jezyk") and d["jezyk"] != "pl":
        t1 = time.time()
        text = " ".join(x["text"] for x in d["segmenty"]) + " " + (d["zrodlo"].get("tytul") or "")
        sport = type_from_content("", text) == "sport"
        pl_segs, failed = translate_segments(eng, d["segmenty"], d["jezyk"], "pl", say, terms=SPORT_TERMS if sport else "")
        t_tr = round(time.time() - t1, 1)
    if s:
        verify_quotes(s, d["segmenty"])
        tidy(s, dur, max_quotes=4 if dur < 600 else 8, max_chapters=max(6, min(12, round(dur / 300))))
        if pl_segs:
            say(f"fakty i cytaty po polsku z tłumaczenia linii: {localize(s, d['segmenty'], pl_segs)}")
    analysis = {"zrodlo": d["zrodlo"], "os_czasu": beats, "napisy_ekranowe": d.get("napisy_ekranowe") or [],
                "transkrypcja": {"jezyk": d.get("jezyk"), "segmenty": d["segmenty"],
                                 "tlumaczenia": {"pl": {"segmenty": pl_segs}} if pl_segs else {}},
                "streszczenie": {"dane": s} if s else None}
    issues = quality.check(analysis)
    md = (f"# {a.film} — {a.model}\n\nStreszczenie: {t_sum} s ({len(trace)} zapytań), tłumaczenie: {t_tr} s "
          f"({failed} linii bez tłumaczenia). Runner bez karty graficznej — czasy NIE są czasami użytkownika.\n\n"
          + quality.to_markdown("Kontrola jakości", issues) + "\n" + (to_markdown(s) if s else "_brak streszczenia_\n"))
    if pl_segs:
        md += "\n## Tłumaczenie (pierwsze 60 linii)\n" + "\n".join(
            f"- {x['text']}  \n  → {p['text']}" for x, p in list(zip(d["segmenty"], pl_segs))[:60]) + "\n"
    (out / f"{a.film}.md").write_text(md, encoding="utf-8")
    (out / f"{a.film}.json").write_text(json.dumps(
        {"film": a.film, "model": a.model, "czas_streszczenia_s": t_sum, "czas_tlumaczenia_s": t_tr, "zapytan": len(trace),
         "bez_tlumaczenia": failed, "kontrola": issues, "wynik": quality.score(issues), "streszczenie": s, "slad": trace,
         "dziennik": log, "pl": pl_segs}, ensure_ascii=False, indent=1), encoding="utf-8")
    # artefaktów nie da się pobrać z każdego miejsca — cały raport i ślad zapytań także do dziennika zadania
    print("=====RAPORT=====")
    print(md)
    print("=====SLAD=====")
    for x in trace:
        print(f"--- {x['etap']} (prompt {x['prompt_znakow']} zn.)\n{x['odpowiedz'][:2500]}")
    print("=====KONIEC=====")
    print(quality.to_markdown(a.film, issues))


if __name__ == "__main__":
    main()
