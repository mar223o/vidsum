"""Tłumaczenie transkrypcji lokalnym modelem tekstowym (albo dowolnym silnikiem z metodą complete()).

Zasady: oryginał zostaje nietknięty; tłumaczenie ma DOKŁADNIE te same segmenty i czasy co oryginał
(można je pokazać obok siebie albo jako napisy). Linia, której nie udało się przetłumaczyć, ma
"text": null — nigdy nie wstawiamy zgadywanego tekstu.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Protocol

from .languages import name_en
from .llm import LLMError, _FOREIGN

PROMPT = """You translate lines of an automatic video transcript from {src} into {tgt}.
Rules:
- Translate every numbered line separately. Keep the SAME numbers. Do not merge, split, skip or add lines.
- Lines can be sentence fragments — translate them as fragments.
- Keep numbers, units, temperatures, quantities and proper names exactly.
- If a word looks like a speech-recognition mistake, translate what was most likely said, do not invent new facts.
- Write only in {tgt}{script}. No comments, no explanations.
{context}Answer ONLY with JSON: {{"1": "translation of line 1", "2": "..."}}

LINES:
{lines}"""

_CJK_OK = {"zh", "ja", "ko", "yue"}


class Engine(Protocol):
    def complete(self, prompt: str, as_json: bool = False) -> str: ...


def _script_hint(tgt: str) -> str:
    return " (Latin alphabet only)" if tgt in ("pl", "en", "de", "fr", "es", "it", "pt", "cs", "sk", "nl") else ""


def _parse(raw: str, n: int) -> list[str] | None:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            d = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if isinstance(d, list):                      # model zwrócił listę zamiast słownika
        d = {str(i + 1): v for i, v in enumerate(d)}
    if not isinstance(d, dict):
        return None
    if "translations" in d and isinstance(d["translations"], (dict, list)):
        return _parse(json.dumps(d["translations"]), n)
    out = []
    for i in range(1, n + 1):
        v = d.get(str(i))
        if isinstance(v, dict):
            v = v.get("text") or v.get("translation")
        if not isinstance(v, str) or not v.strip():
            return None
        out.append(v.strip())
    return out


def _bad(texts: list[str], srcs: list[str], tgt: str) -> bool:
    if tgt not in _CJK_OK and any(_FOREIGN.search(t) for t in texts):
        return True               # model „zgubił” język docelowy
    same = sum(1 for a, b in zip(texts, srcs) if a.strip().lower() == b.strip().lower() and len(b.split()) > 2)
    return same > max(1, len(srcs) // 2)    # większość linii nieprzetłumaczona


def translate_lines(engine: Engine, lines: list[str], src: str | None, tgt: str,
                    context: list[str] | None = None) -> list[str] | None:
    """Jedna porcja linii → lista tłumaczeń tej samej długości albo None (nie udało się)."""
    ctx = ""
    if context:
        ctx = ("Previous lines (context only, do NOT translate them):\n" +
               "\n".join(f"- {c}" for c in context) + "\n")
    prompt = PROMPT.format(src=name_en(src) if src else "the original language", tgt=name_en(tgt),
                           script=_script_hint(tgt), context=ctx,
                           lines="\n".join(f"{i}. {t}" for i, t in enumerate(lines, 1)))
    raw = engine.complete(prompt, as_json=True)
    res = _parse(raw, len(lines))
    if res is None or _bad(res, lines, tgt):
        return None
    return res


def translate_segments(engine: Engine, segments: list[dict], src: str | None, tgt: str,
                       log: Callable[[str], None] = lambda s: None, chunk: int = 20) -> tuple[list[dict], int]:
    """Tłumaczy segmenty porcjami. Zwraca (segmenty z tymi samymi czasami, liczba linii bez tłumaczenia)."""
    texts = [s["text"] for s in segments]
    out: list[str | None] = [None] * len(texts)

    def run(lo: int, hi: int, size: int) -> None:
        for a in range(lo, hi, size):
            b = min(hi, a + size)
            ctx = texts[max(0, a - 2):a]
            res = None
            for _ in (1, 2):                          # jedna ponowna próba z tą samą porcją
                try:
                    res = translate_lines(engine, texts[a:b], src, tgt, ctx)
                except LLMError as e:
                    log(f"        ! tłumaczenie {tgt}: {str(e)[:80]}")
                    raise
                if res is not None:
                    break
            if res is not None:
                out[a:b] = res
            elif b - a > 1:                           # porcja nie przeszła — mniejsze kawałki
                run(a, b, max(1, (b - a) // 4))

    run(0, len(texts), chunk)
    failed = sum(1 for x in out if x is None)
    segs = [{"start": s["start"], "end": s["end"], "text": t} for s, t in zip(segments, out)]
    return segs, failed
