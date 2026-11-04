"""Pomiar lokalnych modeli tekstowych (Ollama): streszczenie JSON + tłumaczenia.

Uruchomienie:  python tests/bench/llm_bench.py qwen3:8b [--wyniki katalog]
Dane: prawdziwy film o frytkach (oś czasu z VidSum) i krótkie teksty do tłumaczenia z wzorcami.
Ocena streszczenia: fakty z filmu (+1 każdy) i zmyślenia (−2 każde), poprawność JSON, struktura.
Ocena tłumaczeń: chrF (0–100, podobieństwo znakowe do wzorca), liczba linii, liczby/nazwy zachowane.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from vidsum.llm import Ollama  # noqa: E402
from vidsum.summary import parse_summary  # noqa: E402
from vidsum.translate import translate_lines  # noqa: E402

DATA = Path(__file__).parent / "data"

FACTS = {  # co MUSI być w dobrym streszczeniu filmu o frytkach (z mowy i napisów)
    "140 stopni": r"\b140\b", "190 stopni": r"\b190\b", "soda": r"\bsod[aąyę]\b|sodą",
    "sól": r"\bsól\b|\bsoli\b|\bsolą\b", "zimna woda": r"zimn\w* wod",
    "płukanie do czystej wody": r"przejrzyst|przezroczyst|klarown|czyst\w* wod",
    "skrobia ziemniaczana (panierka)": r"(mąk|skrobi)\w* ziemniaczan",
    "dużo skrobi w odmianie": r"skrobi", "tłuszcz z kaczki": r"kacz",
    "1 cm": r"\b1 ?cm\b|centymetr", "lodówka/zamrażarka": r"lodów|zamra",
    "dwa smażenia / blanszowanie": r"blansz|dwukrotn|dwa razy|drugi\w* smaż|ostateczn\w* smaż|końcow\w* smaż|wstępn\w* smaż|podsmaż",
    "gotowanie do miękkości": r"miękk", "mieszanie (postrzępione brzegi)": r"miesza",
}
HALLUCINATIONS = {  # błędy z wcześniejszego słabego streszczenia lokalnego + typowe zmyślenia
    "bakterie": r"bakteri", "czekolada": r"czekolad", "węglowodany": r"węglowodan",
    "grill": r"grill", "piekarnik": r"piekarnik", "ocet": r"\bocet|\boctem",
}


def chrf(hyp: str, ref: str, n: int = 6, beta: float = 2.0) -> float:
    h, r = re.sub(r"\s+", "", hyp.lower()), re.sub(r"\s+", "", ref.lower())
    ps, rs = [], []
    for k in range(1, n + 1):
        hc = Counter(h[i:i + k] for i in range(len(h) - k + 1))
        rc = Counter(r[i:i + k] for i in range(len(r) - k + 1))
        if not hc or not rc:
            continue
        m = sum((hc & rc).values())
        ps.append(m / sum(hc.values()))
        rs.append(m / sum(rc.values()))
    if not ps:
        return 0.0
    p, rr = sum(ps) / len(ps), sum(rs) / len(rs)
    return 0.0 if p + rr == 0 else 100 * (1 + beta ** 2) * p * rr / (beta ** 2 * p + rr)


def score_summary(d: dict | None, raw: str) -> dict:
    if not d:
        return {"json_ok": False, "fakty": 0, "zmyslenia": [], "wynik": -99, "brakuje": list(FACTS)}
    txt = json.dumps(d, ensure_ascii=False).lower()
    hit = [k for k, rx in FACTS.items() if re.search(rx, txt)]
    bad = [k for k, rx in HALLUCINATIONS.items() if re.search(rx, txt)]
    kroki = d.get("co_masz_zrobic", {}).get("kroki", [])
    times = [k.get("t") for k in kroki if isinstance(k.get("t"), (int, float))]
    return {"json_ok": True, "typ": d.get("typ"), "fakty": len(hit), "fakty_z": len(FACTS),
            "brakuje": [k for k in FACTS if k not in hit], "zmyslenia": bad, "kroki": len(kroki),
            "kroki_z_czasem": len(times), "rozdzialy": len(d.get("rozdzialy", [])),
            "wynik": len(hit) - 2 * len(bad)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--wyniki", default="bench_llm")
    ap.add_argument("--host")
    a = ap.parse_args()
    out = Path(a.wyniki)
    out.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.-]+", "_", a.model)
    eng = Ollama(a.model, a.host, timeout=3600)
    t = time.time()
    eng.ensure(print)
    res: dict = {"model": a.model, "pobieranie_s": round(time.time() - t, 1)}

    # rozgrzewka (wczytanie modelu do pamięci) — żeby czasy niżej mierzyły samo generowanie
    t = time.time()
    eng.complete("Odpowiedz jednym słowem: tak.", max_tokens=5)
    res["ladowanie_s"] = round(time.time() - t, 1)

    prompt = (DATA / "frytki_prompt.txt").read_text(encoding="utf-8")
    t = time.time()
    raw = eng.complete(prompt, as_json=True)
    res["streszczenie_s"] = round(time.time() - t, 1)
    (out / f"{safe}_streszczenie_surowe.txt").write_text(raw, encoding="utf-8")
    d = parse_summary(raw, 58.0)
    if d:
        (out / f"{safe}_streszczenie.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    res["streszczenie"] = score_summary(d, raw)
    print("streszczenie:", res["streszczenie"], f"{res['streszczenie_s']} s", flush=True)

    res["tlumaczenia"] = []
    for task in json.loads((DATA / "tlumaczenia.json").read_text(encoding="utf-8")):
        t = time.time()
        try:
            hyp = translate_lines(eng, task["lines"], task["src"], task["tgt"])
        except Exception as e:  # noqa: BLE001
            hyp, err = None, str(e)[:200]
        else:
            err = None
        dt = round(time.time() - t, 1)
        row = {"zadanie": task["nazwa"], "s": dt, "linie_ok": hyp is not None, "blad": err}
        if hyp:
            row["chrf"] = round(sum(chrf(h, r) for h, r in zip(hyp, task["ref"])) / len(hyp), 1)
            joined = " ".join(hyp).lower()
            row["fakty"] = sum(1 for f in task["fakty"] if re.search(f, joined))
            row["fakty_z"] = len(task["fakty"])
            row["tekst"] = hyp
        res["tlumaczenia"].append(row)
        print(task["nazwa"], {k: v for k, v in row.items() if k != "tekst"}, flush=True)

    ok = [r for r in res["tlumaczenia"] if r.get("chrf") is not None]
    res["tlumaczenia_chrf_srednio"] = round(sum(r["chrf"] for r in ok) / len(ok), 1) if ok else 0
    (out / f"{safe}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
