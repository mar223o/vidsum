"""Pomiar streszczenia etapami na prawdziwej osi czasu (frytki, Vidsumly 0.7.5 na komputerze testowym): kilka powtórzeń,
fakty (+1) i zmyślenia (−2) jak w llm_bench.py, czas. Do porównania wersji kodu (stara/nowa) i trybów.

python tests/bench/summary_bench.py gemma3:4b --powtorzen 3 --rownolegle 3 --wyniki wyniki --etykieta nowa
"""
from __future__ import annotations

import argparse
import inspect
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(sys.argv[sys.argv.index("--kod") + 1]) if "--kod" in sys.argv else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from vidsum.llm import Ollama  # noqa: E402
from vidsum.summary import compact_timeline, staged_summary, to_markdown, verify_quotes  # noqa: E402

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))
from llm_bench import FACTS, HALLUCINATIONS  # noqa: E402

# zmyślenia z wyników z komputera testowego (0.7.7, frytki)
HALLUCINATIONS = {**HALLUCINATIONS, "świeżo zmielona sól": r"świeżo zmielon", "papierowy ręcznik": r"papierow",
                  "wyciśnij skrobię": r"wyciśn", "proszek do pieczenia": r"proszek do pieczenia",
                  "kacze pióro": r"pióra", "nie przesadzaj z solą": r"przesadz", "kociołek z wodą przy smażeniu": r"kociołk"}


def placement(steps: list) -> dict:
    """Liczby w dobrych krokach: 140 przy pierwszym smażeniu (ok. 0:39–0:46), 190 przy drugim (ok. 0:50–0:55);
    osobne kroki: smażenie na złoto i posypanie solą Maldon."""
    def at(rx):
        return [k.get("t", -1) for k in steps if re.search(rx, str(k.get("tekst", "")).lower())]
    return {"140_w_dobrym_miejscu": bool(at(r"\b140\b")) and all(38 <= t <= 47 for t in at(r"\b140\b")),
            "190_w_dobrym_miejscu": bool(at(r"\b190\b")) and all(49 <= t <= 56 for t in at(r"\b190\b")),
            "krok_zloto": bool(at(r"złot")), "krok_maldon": bool(at(r"maldon"))}


FACTS = {**FACTS, "sól Maldon": r"maldon", "odmiana Agria": r"agri",
         "płukanie do czystej wody": FACTS["płukanie do czystej wody"] + r"|wod\w*[^.\n]{0,30}czyst"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--powtorzen", type=int, default=3)
    ap.add_argument("--rownolegle", type=int, default=1)
    ap.add_argument("--wyniki", default="wyniki")
    ap.add_argument("--etykieta", default="nowa")
    ap.add_argument("--kod", default=None)
    ap.add_argument("--z-tlumaczeniem", action="store_true")
    ap.add_argument("--dane", default="frytki_077.json", help="plik w tests/bench/data (0.7.7 na komputerze testowym, z tłumaczeniem PL)")
    a = ap.parse_args()
    d = json.loads((BENCH / "data" / a.dane).read_text(encoding="utf-8"))
    tl = compact_timeline(d["os_czasu"])
    eng = Ollama(a.model, timeout=3600)
    sig = inspect.signature(staged_summary).parameters
    kw = {"parallel": a.rownolegle} if "parallel" in sig else {}
    if "segments" in sig:                         # 0.7.8: kroki z linii mowy + napisy z ekranu
        kw.update(segments=d["segmenty"], ocr=d.get("napisy") or [])
    ap_pl = "--z-tlumaczeniem" in sys.argv          # w programie tłumaczenie zwykle nie jest jeszcze gotowe
    if "polish" in sig and d.get("pl") and ap_pl:
        kw["polish"] = d["pl"]
    out = Path(a.wyniki)
    out.mkdir(parents=True, exist_ok=True)
    runs = []
    for i in range(a.powtorzen):
        t = time.time()
        trace: list = []
        s = staged_summary(eng, tl, d["meta"], d["dlugosc"], print, trace=trace, **kw)
        sec = round(time.time() - t, 1)
        if s:
            verify_quotes(s, d["segmenty"])
        md = to_markdown(s) if s else ""
        low = md.lower()
        steps_txt = json.dumps((s or {}).get("co_masz_zrobic", {}).get("kroki", []), ensure_ascii=False).lower()
        got = [k for k, rx in FACTS.items() if re.search(rx, low)]
        got_steps = [k for k, rx in FACTS.items() if re.search(rx, steps_txt)]
        bad = [k for k, rx in HALLUCINATIONS.items() if re.search(rx, low)]
        r = {"powtorzenie": i + 1, "czas_s": sec, "fakty": len(got), "z": len(FACTS), "fakty_w_krokach": len(got_steps),
             "brak": [k for k in FACTS if k not in got], "zmyslenia": bad, "wynik": len(got) - 2 * len(bad),
             "kroki": len((s or {}).get("co_masz_zrobic", {}).get("kroki", [])),
             "rozdzialy": len((s or {}).get("rozdzialy", [])),
             "miejsca": placement((s or {}).get("co_masz_zrobic", {}).get("kroki", [])),
             "czytanie_s": (s or {}).get("czas_czytania_s")}
        print(json.dumps(r, ensure_ascii=False))
        runs.append(r)
        (out / f"{a.etykieta}_{i + 1}.md").write_text(md, encoding="utf-8")
        (out / f"{a.etykieta}_{i + 1}_kroki.json").write_text(json.dumps(trace, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / f"{a.etykieta}.json").write_text(json.dumps({"etykieta": a.etykieta, "model": a.model, "rownolegle": a.rownolegle,
                                                         "przebiegi": runs}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
