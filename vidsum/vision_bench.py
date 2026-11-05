"""Pomiar opisu kadrów na komputerze użytkownika (karta graficzna): te same kadry z gotowej analizy opisane
trzema sposobami — do decyzji, czy szybszy sposób daje te same opisy.

    VidSum.exe --pomiar-kadrow "C:\\...\\Dokumenty\\VidSum\\<folder analizy>"

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

from .llm import VISION_CTX, VISION_PROMPT, Ollama, _clean_vision, salvage_json

_ARR = lambda n: {"type": "array", "items": {"type": "string"}, "maxItems": n}  # noqa: E731
FRAME_SCHEMA = {"type": "object", "properties": {
    "scena": {"type": "string"}, "czynnosci": _ARR(4), "obiekty": _ARR(6), "tekst_na_ekranie": _ARR(4),
    "napisy_na_przedmiotach": _ARR(3), "cialo": {"type": "string"},
    "pewnosc": {"type": "string", "enum": ["wysoka", "srednia", "niska"]}},
    "required": ["scena", "czynnosci", "obiekty", "tekst_na_ekranie", "napisy_na_przedmiotach", "cialo", "pewnosc"]}
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
        body = {"model": model, "stream": False, "keep_alive": "10m", "format": FRAME_SCHEMA if schema else "json",
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
