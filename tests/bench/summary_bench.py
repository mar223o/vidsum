"""Pomiar streszczenia etapami na prawdziwej osi czasu (frytki, VidSum 0.7.5 na komputerze testowym): kilka powtórzeń,
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
    a = ap.parse_args()
    d = json.loads((BENCH / "data" / "frytki_076.json").read_text(encoding="utf-8"))
    tl = compact_timeline(d["os_czasu"])
    eng = Ollama(a.model, timeout=3600)
    kw = {"parallel": a.rownolegle} if "parallel" in inspect.signature(staged_summary).parameters else {}
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
             "rozdzialy": len((s or {}).get("rozdzialy", []))}
        print(json.dumps(r, ensure_ascii=False))
        runs.append(r)
        (out / f"{a.etykieta}_{i + 1}.md").write_text(md, encoding="utf-8")
        (out / f"{a.etykieta}_{i + 1}_kroki.json").write_text(json.dumps(trace, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / f"{a.etykieta}.json").write_text(json.dumps({"etykieta": a.etykieta, "model": a.model, "rownolegle": a.rownolegle,
                                                         "przebiegi": runs}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
