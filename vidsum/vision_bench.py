"""Pomiar opisu kadrów na komputerze użytkownika (karta graficzna): te same kadry z gotowej analizy opisane
trzema sposobami — do decyzji, czy szybszy sposób daje te same opisy.

    Vidsumly.exe --pomiar-kadrow "C:\\...\\Dokumenty\\Vidsumly\\<folder analizy>"

Sposoby:
  teraz   — jak w programie (JSON, 1 kadr na zapytanie),
  schemat — JSON ze schematem (limit długości list: koniec z „przyrząd kuchenny” ×4), 1 kadr na zapytanie,
  2w1     — 2 kadry w jednym zapytaniu (ten sam schemat dla każdego).
Wynik: pomiar_kadrow.md i pomiar_kadrow.json w folderze analizy (czas, tokeny, opisy obok siebie, zgodność słów).
"""
from __future__ import annotations

import base64
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .llm import FRAME_SCHEMA, VISION_CTX, VISION_PROMPT, Ollama, _clean_vision, salvage_json

PAIR_SCHEMA = {"type": "object", "properties": {"kadr_1": FRAME_SCHEMA, "kadr_2": FRAME_SCHEMA},
               "required": ["kadr_1", "kadr_2"]}
PAIR_PROMPT = ("Dostajesz DWA osobne kadry z filmu: obraz 1 (czas {t1}) i obraz 2 (czas {t2}). Opisz każdy osobno — "
               "nie mieszaj ich ze sobą. Odpowiedz JSON-em {{\"kadr_1\": {{...}}, \"kadr_2\": {{...}}}}, gdzie każdy "
               "opis ma klucze jak niżej.\n\n")


def _b64(p: Path) -> str:
    return base64.b64encode(p.read_bytes()).decode("ascii")


def _parse(txt: str) -> dict:
    try:
        d = json.loads(txt)
    except json.JSONDecodeError:
        d = salvage_json(txt)
    return d if isinstance(d, dict) else {}


def _words(v: dict) -> set:
    t = " ".join([v.get("scena", "")] + v.get("czynnosci", []) + v.get("obiekty", []))
    return set(re.findall(r"\w{3,}", t.lower()))


def run(folder: Path, model: str | None = None, host: str | None = None, log=print) -> Path:
    folder = Path(folder)
    a = json.loads((folder / "analiza.json").read_text(encoding="utf-8"))
    frames = [(f["t"], folder / f["file"]) for f in a.get("kadry", []) if (folder / f["file"]).is_file()]
    if not frames:
        raise RuntimeError(f"Brak kadrów w {folder}")
    model = model or (a["ustawienia"]["obraz"].split(":", 1)[1] if str(a["ustawienia"].get("obraz", "")).startswith("ollama:")
                      else "qwen3-vl:4b-instruct")
    eng = Ollama(model, host, timeout=900)
    eng.check()
    workers = min(2, eng.parallel)
    log(f"Pomiar opisu kadrów: {len(frames)} kadrów, model {model}, {workers} zapytania naraz (OLLAMA_NUM_PARALLEL={eng.parallel})")
    t = time.time()
    eng.preload()
    log(f"  model wczytany ({time.time() - t:.1f} s)")

    def ts(x: float) -> str:
        return f"{int(x // 60):02d}:{int(x % 60):02d}"

    def one(t_img, schema: bool):
        tt, img = t_img
        body = {"model": model, "stream": False, "keep_alive": "10m", "format": FRAME_SCHEMA if schema else "json",   # „teraz” = sposób z 0.7.6 (porównanie)
                "options": {"temperature": 0, "num_predict": 400, "num_ctx": VISION_CTX},
                "messages": [{"role": "user", "content": VISION_PROMPT.format(t=ts(tt)), "images": [_b64(img)]}]}
        r = eng._post("/api/chat", body)
        return [(tt, _clean_vision(_parse(r.get("message", {}).get("content", ""))))], r.get("eval_count", 0)

    def pair(items, _schema=True):
        (t1, i1), (t2, i2) = items if len(items) == 2 else (items[0], items[0])
        if len(items) == 1:
            return one(items[0], True)
        body = {"model": model, "stream": False, "keep_alive": "10m", "format": PAIR_SCHEMA,
                "options": {"temperature": 0, "num_predict": 800, "num_ctx": VISION_CTX + 1024},
                "messages": [{"role": "user", "content": PAIR_PROMPT.format(t1=ts(t1), t2=ts(t2)) +
                              VISION_PROMPT.split("\n", 1)[1], "images": [_b64(i1), _b64(i2)]}]}
        r = eng._post("/api/chat", body)
        d = _parse(r.get("message", {}).get("content", ""))
        return [(t1, _clean_vision(d.get("kadr_1") or {})), (t2, _clean_vision(d.get("kadr_2") or {}))], r.get("eval_count", 0)

    modes = {"teraz": (lambda x: one(x, False), [[f] for f in frames]),
             "schemat": (lambda x: one(x, True), [[f] for f in frames]),
             "2w1": (pair, [frames[i:i + 2] for i in range(0, len(frames), 2)])}
    res: dict = {}
    for name, (fn, jobs) in modes.items():
        if name == "2w1":
            eng.unload()                          # inny kontekst — świeże wczytanie, żeby nie liczyć przeładowania
            eng2 = Ollama(model, host)
            eng2._post("/api/generate", {"model": model, "keep_alive": "10m", "options": {"num_ctx": VISION_CTX + 1024}})
        t = time.time()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            outs = list(pool.map(lambda j: fn(j[0]) if name != "2w1" else fn(j), jobs))
        wall = time.time() - t
        descs = {tt: v for o, _ in outs for tt, v in o}
        toks = sum(n for _, n in outs)
        res[name] = {"czas_s": round(wall, 1), "s_na_kadr": round(wall / len(frames), 2), "tokeny": toks,
                     "opisy": {str(k): v for k, v in descs.items()}}
        log(f"  {name}: {wall:.1f} s ({wall / len(frames):.2f} s/kadr), {toks} tokenów odpowiedzi")
    eng.unload()
    base = res["teraz"]["opisy"]
    for name in ("schemat", "2w1"):
        sims = []
        for k, v in res[name]["opisy"].items():
            a_w, b_w = _words(base.get(k, {})), _words(v)
            sims.append(len(a_w & b_w) / max(1, len(a_w | b_w)))
        res[name]["zgodnosc_slow_z_teraz"] = round(sum(sims) / max(1, len(sims)), 2)
    (folder / "pomiar_kadrow.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    L = ["# Pomiar opisu kadrów", "", f"Model: {model}; kadrów: {len(frames)}; zapytań naraz: {workers}", "",
         "| Sposób | Czas | s/kadr | Tokeny odpowiedzi | Zgodność słów z „teraz” |", "|---|---|---|---|---|"]
    for name, r in res.items():
        L.append(f"| {name} | {r['czas_s']} s | {r['s_na_kadr']} | {r['tokeny']} | {r.get('zgodnosc_slow_z_teraz', '—')} |")
    L += ["", "## Opisy obok siebie (scena; czynności)", ""]
    for tt, _ in frames:
        L.append(f"### {ts(tt)}")
        for name in res:
            v = res[name]["opisy"].get(str(tt), {})
            L.append(f"- **{name}**: {v.get('scena', '—')} — {', '.join(v.get('czynnosci', []))}")
        L.append("")
    out = folder / "pomiar_kadrow.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    log(f"✔ wynik: {out}")
    return out


# ---------------- 0.11.1: porównanie modeli obrazu na tych samych kadrach, z oceną według wzorca ----------------
WZORCE = Path(__file__).parent / "wzorce"


def load_reference(a: dict) -> dict | None:
    """Wzorzec kadrów dla tego filmu (po adresie albo tytule), jeśli program go ma."""
    z = a.get("zrodlo") or {}
    key = f"{z.get('url') or ''} {z.get('wejscie') or ''} {z.get('tytul') or ''}"
    for f in WZORCE.glob("*_kadry.json"):
        ref = json.loads(f.read_text(encoding="utf-8"))
        film = ref.get("film", "")
        vid = re.search(r"v=([\w-]{11})", film)
        if (vid and vid.group(1) in key) or (film.split(" (")[0] and film.split(" (")[0] in key):
            return ref
    return None


def score_description(v: dict, ref: dict) -> dict:
    """Ocena jednego opisu kadru: ile grup ze wzorca trafione (choć jedno słowo z grupy) i jakie błędne słowa padły."""
    text = " ".join([v.get("scena", "")] + list(v.get("czynnosci", [])) + list(v.get("obiekty", []))).lower()
    hit = [any(s in text for s in grp) for grp in ref["musi"]]
    wrong = [s for s in ref.get("nie", []) if s in text]
    return {"trafione": sum(hit), "z": len(hit), "bledy": wrong}


def score_all(descs: dict, reference: dict, tol: float = 1.5) -> dict:
    """descs: {czas: opis}. Zwraca trafność (0–1), liczbę błędnych słów i wynik każdego kadru."""
    rows, hits, total, wrong = [], 0, 0, 0
    used: set = set()
    for r in reference["kadry"]:                   # każdy opis pasuje do najwyżej jednego kadru wzorca
        free = [k for k in descs if k not in used]
        t = min(free, key=lambda k: abs(float(k) - r["t"]), default=None)
        if t is None or abs(float(t) - r["t"]) > tol:
            continue
        used.add(t)
        s = score_description(descs[t], r)
        hits, total, wrong = hits + s["trafione"], total + s["z"], wrong + len(s["bledy"])
        rows.append({"t": r["t"], "kadr_t": t, "co_widac": r["co_widac"], "opis": descs[t].get("scena", ""), **s})
    return {"trafnosc": round(hits / total, 2) if total else None, "bledne_slowa": wrong, "kadry": rows}


def compare_models(folder: Path, models: list[str], host: str | None = None, log=print) -> Path:
    """Te same kadry opisane każdym modelem dokładnie tak jak w programie (pełny opis, 1 kadr na zapytanie):
    czas wczytania, czas opisu, a gdy jest wzorzec — trafność i błędne słowa. Wynik: porownanie_modeli_obrazu.md/json."""
    from .llm import TEXT_CTX, Ollama as _Ollama
    folder = Path(folder)
    a = json.loads((folder / "analiza.json").read_text(encoding="utf-8"))
    frames = [(f["t"], folder / f["file"]) for f in a.get("kadry", []) if (folder / f["file"]).is_file()]
    if not frames:
        raise RuntimeError(f"Brak kadrów w {folder}")
    ref = load_reference(a)
    text_model = (a.get("ustawienia") or {}).get("streszczenie", "")
    res: dict = {}
    for name in models:
        # „model@lekki” = skrócony opis (max 3 czynności, 5 obiektów), którego program używa przy włączonym OCR
        m, light = name.split("@")[0], name.endswith("@lekki")
        same = text_model.endswith(":" + m) or text_model.endswith(m)
        eng = _Ollama(m, host, timeout=900, vision_ctx=TEXT_CTX if same else VISION_CTX)
        eng.check()
        t0 = time.time()
        eng.preload()
        load_s = time.time() - t0
        t0 = time.time()
        descs = {}
        for tt, img in frames:
            descs[tt] = eng.describe_frame(img, f"{int(tt // 60):02d}:{int(tt % 60):02d}", light=light)
        wall = time.time() - t0
        eng.unload()
        res[name] = {"wczytanie_s": round(load_s, 1), "opis_s": round(wall, 1), "s_na_kadr": round(wall / len(frames), 2),
                  "opisy": {str(k): v for k, v in descs.items()},
                  "ocena": score_all(descs, ref) if ref else None}
        log(f"  {name}: wczytanie {load_s:.1f} s, opis {wall:.1f} s ({wall / len(frames):.2f} s/kadr)"
            + (f", trafność {res[name]['ocena']['trafnosc']}, błędne słowa {res[name]['ocena']['bledne_slowa']}" if ref else ""))
    (folder / "porownanie_modeli_obrazu.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    L = ["# Porównanie modeli obrazu (te same kadry)", "",
         f"Kadrów: {len(frames)}; wzorzec: {'tak — ' + ref['film'] if ref else 'brak (tylko czasy i opisy)'}", "",
         "| Model | Wczytanie | Opis kadrów | s/kadr | Trafność | Błędne słowa |", "|---|---|---|---|---|---|"]
    for m, r in res.items():
        o = r["ocena"] or {}
        L.append(f"| {m} | {r['wczytanie_s']} s | {r['opis_s']} s | {r['s_na_kadr']} | {o.get('trafnosc', '—')} | {o.get('bledne_slowa', '—')} |")
    L += ["", "## Opisy obok siebie", ""]
    for tt, _ in frames:
        L.append(f"### {int(tt // 60):02d}:{int(tt % 60):02d}")
        if ref:                                     # ten sam przydział kadr ↔ wzorzec co w ocenie (bez przesunięć)
            first = next(iter(res.values()))["ocena"] or {}
            r0 = next((r for r in first.get("kadry", []) if r.get("kadr_t") == tt), None)
            if r0:
                L.append(f"- _naprawdę_: {r0['co_widac']}")
        for m in res:
            v = res[m]["opisy"].get(str(tt), {})
            L.append(f"- **{m}**: {v.get('scena', '—')} — {', '.join(v.get('czynnosci', []))}"
                     + (f"; obiekty: {', '.join(v.get('obiekty', []))}" if v.get("obiekty") else ""))
        L.append("")
    out = folder / "porownanie_modeli_obrazu.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    log(f"✔ wynik: {out}")
    return out
