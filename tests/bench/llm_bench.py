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
from vidsum.summary import parse_summary, staged_summary  # noqa: E402
from vidsum.translate import translate_segments  # noqa: E402

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


class Recorder:
    def __init__(self, eng):
        self.eng, self.last = eng, ""

    def complete(self, prompt, as_json=False, max_tokens=None):
        self.last = self.eng.complete(prompt, as_json=as_json, max_tokens=max_tokens)
        return self.last


def polish_speech(eng, tl: str) -> str:
    """MOWA w osi czasu → polskie tłumaczenie (jak pipeline przed streszczeniem lokalnym)."""
    rows = tl.splitlines()
    idx, segs = [], []
    for i, r in enumerate(rows):
        m = re.search(r"MOWA: (.*?)(?: \| |$)", r)
        if m:
            idx.append(i)
            segs.append({"start": i, "end": i + 1, "text": m.group(1)})
    out, _ = translate_segments(eng, segs, "en", "pl")
    for i, o, x in zip(idx, segs, out):
        if x["text"]:
            rows[i] = rows[i].replace("MOWA: " + o["text"], "MOWA: " + x["text"], 1)
    return "\n".join(rows)


def compact_from_prompt(prompt: str) -> str:
    """Oś czasu z zapisanego promptu (stary format) → zwięzły format etapowy (jak compact_timeline)."""
    tl = prompt.split("OŚ CZASU:", 1)[1]
    out = []
    for m in re.finditer(r"\[(\d+):(\d+)–[^\]]*\] OBRAZ: (.*?)\n(?:    NAPISY: (.*?)\n)?    MOWA: (.*?)(?:\n|$)", tl):
        t = int(m.group(1)) * 60 + int(m.group(2))
        obraz, napisy, mowa = m.group(3), m.group(4), m.group(5)
        fields = dict(f.split(": ", 1) for f in obraz.split("; ")[1:] if ": " in f)
        scene = obraz.split("; ")[0]
        caps = napisy or fields.get("napisy w filmie")
        parts = []
        if mowa and mowa != "—":
            parts.append(f"MOWA: {mowa}")
        if caps:
            parts.append(f"NAPISY: {caps}")
        seen = scene + (f" ({fields['czynności']})" if fields.get("czynności") else "")
        if not scene.startswith("{"):
            parts.append(f"OBRAZ: {seen}")
        out.append(f"[{t}s] " + " | ".join(parts))
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--wyniki", default="bench_llm")
    ap.add_argument("--host")
    ap.add_argument("--tryb", choices=["jeden", "etapy", "etapy_pl", "oba", "wszystkie"], default="oba",
                    help="jeden = jeden duży prompt; etapy = fakty, potem opis; etapy_pl = jak w programie: najpierw "
                         "tłumaczenie MOWY na polski, potem etapy; oba = etapy + etapy_pl")
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
    modes = {"oba": ["etapy", "etapy_pl"], "wszystkie": ["jeden", "etapy", "etapy_pl"]}.get(a.tryb, [a.tryb])
    for mode in modes:
        t = time.time()
        if mode == "jeden":
            raw = eng.complete(prompt, as_json=True)
            d = parse_summary(raw, 58.0)
        else:
            meta = re.search(r"^Metadane: (.*)$", prompt, re.M).group(1)
            trace: list = []
            tl = compact_from_prompt(prompt)
            if mode == "etapy_pl":
                tl = polish_speech(eng, tl)
                trace.append(tl)
                meta += "; MOWA poniżej to polskie tłumaczenie maszynowe z oryginału"
            d = staged_summary(eng, tl, meta, 58.0, print, trace=trace)
            raw = "\n\n=====\n\n".join(trace)
        key = {"jeden": "streszczenie", "etapy": "streszczenie_etapy", "etapy_pl": "streszczenie_etapy_pl"}[mode]
        res[key + "_s"] = round(time.time() - t, 1)
        if raw:
            (out / f"{safe}_{mode}_surowe.txt").write_text(raw, encoding="utf-8")
        if d:
            (out / f"{safe}_{mode}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        res[key] = score_summary(d, raw)
        print(f"{key}:", res[key], f"{res[key + '_s']} s", flush=True)

    res["tlumaczenia"] = []
    for task in json.loads((DATA / "tlumaczenia.json").read_text(encoding="utf-8")):
        t = time.time()
        rec = Recorder(eng)
        try:
            # jak w programie: porcje po 20 linii, przy złej odpowiedzi ponowna próba i mniejsze porcje
            segs, failed = translate_segments(rec, [{"start": i, "end": i + 1, "text": t} for i, t in enumerate(task["lines"])],
                                              task["src"], task["tgt"])
            hyp = [x["text"] or "" for x in segs]
            row_failed = failed
        except Exception as e:  # noqa: BLE001
            hyp, err, row_failed = None, str(e)[:200], None
        else:
            err = None
        dt = round(time.time() - t, 1)
        row = {"zadanie": task["nazwa"], "s": dt, "linie_ok": bool(hyp) and not row_failed, "blad": err,
               "nieprzetlumaczone": row_failed if hyp else None}
        if not row["linie_ok"]:
            row["surowe"] = rec.last[:1500]          # do diagnozy: co model zwrócił
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
