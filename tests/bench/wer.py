"""Pomiar dokładności transkrypcji: WER (odsetek błędnych słów) względem znanego tekstu.

Użycie: python wer.py <folder_bench> <konfiguracja>[,<konfiguracja>...] [--models DIR]
Konfiguracje: small-b1, small-b5, turbo-b5, turbo-b5-hot (hot = podpowiedzi słów z tytułu/OCR)
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from pathlib import Path

from num2words import num2words

from vidsum.media import extract_audio
from vidsum.transcribe import WhisperEngine


def normalize(text: str, lang: str) -> list[str]:
    text = text.lower().replace("’", "'")
    text = re.sub(r"\d+", lambda m: " " + num2words(int(m.group()), lang=lang) + " ", text)
    text = re.sub(r"[^\w\s']", " ", text)
    text = text.replace(" and ", " ") if lang == "en" else text      # „one hundred and forty” = „140”
    text = re.sub(r"[-]", " ", text)
    units = {"pl": {"g": "gramów", "ml": "mililitrów", "kg": "kilogramów"}, "en": {"centimeter": "centimetre"}}[lang]
    text = " ".join(units.get(w, w) for w in text.split())
    return [w for w in unicodedata.normalize("NFC", text).split() if w and w != "and" or lang != "en" and w]


def wer(ref: list[str], hyp: list[str]) -> tuple[float, int]:
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
            prev, d[j] = d[j], cur
    return d[len(hyp)] / max(1, len(ref)), d[len(hyp)]


def diff_words(ref: list[str], hyp: list[str]) -> list[str]:
    import difflib
    out = []
    for op, a0, a1, b0, b1 in difflib.SequenceMatcher(a=ref, b=hyp).get_opcodes():
        if op != "equal":
            out.append(f"{' '.join(ref[a0:a1]) or '∅'} → {' '.join(hyp[b0:b1]) or '∅'}")
    return out


CONFIGS = {
    "small-b1": dict(model="small", beam_size=1),
    "small-b5": dict(model="small", beam_size=5),
    "turbo-b5": dict(model="large-v3-turbo", beam_size=5),
    "turbo-b5-hot": dict(model="large-v3-turbo", beam_size=5, hot=True),
    "small-b5-hot": dict(model="small", beam_size=5, hot=True),
}


def main(bench: Path, configs: list[str], models: str | None):
    rows = []
    for lang in ("en", "pl"):
        video = bench / f"bench_{lang}.mp4"
        truth = json.loads((bench / f"bench_{lang}.truth.json").read_text(encoding="utf-8"))
        ref_text = " ".join(s["text"] for s in truth["segments"])
        ref = normalize(ref_text, lang)
        wav = extract_audio(video, bench / f"_{lang}.wav")
        hot_file = bench / f"bench_{lang}.hot.txt"
        for name in configs:
            c = CONFIGS[name]
            hot = hot_file.read_text(encoding="utf-8") if c.get("hot") and hot_file.exists() else None
            eng = WhisperEngine(c["model"], "cpu", download_root=models, beam_size=c["beam_size"], hotwords=hot)
            t = time.time()
            tr = eng.transcribe(wav, lang)
            dt = time.time() - t
            hyp = normalize(" ".join(s.text for s in tr.segments), lang)
            w, n = wer(ref, hyp)
            rows.append((lang, name, round(100 * w, 1), n, len(ref), round(dt, 1), diff_words(ref, hyp)))
            print(f"{lang} {name:14s} WER {100 * w:5.1f}%  ({n}/{len(ref)} słów)  {dt:6.1f}s", flush=True)
            for x in rows[-1][-1]:
                print("      ", x, flush=True)
    (bench / "wyniki_wer.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    args = sys.argv[1:]
    models = None
    if "--models" in args:
        i = args.index("--models")
        models = args[i + 1]
        del args[i:i + 2]
    main(Path(args[0]), args[1].split(","), models)
