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
- Keep numbers, units, temperatures, quantities and proper names exactly. Never translate or adapt people's names
  (Michael stays Michael, not Michał).
- If a word looks like a speech-recognition mistake, translate what was most likely said, do not invent new facts.
- Write only in {tgt}{script}. No comments, no explanations.
{terms}{context}Answer ONLY with JSON: {{"1": "translation of line 1", "2": "..."}}

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


# ---------------- straże tłumaczenia (0.11.10) ----------------
# Pomiar 0.11.9 (dokument 24:50, gemma3:4b): „Oferтoвaнo nagrodę w wysokości 130۰۰۰ dolarów” (cyrylica i cyfry perskie),
# „Tower Bridge” → „Wieża Cytadeli”, „Chinese Student Affairs” → „Zhongshan Student Affairs”. Mały model nie przestanie
# się mylić — program sprawdza każdą linię i w razie błędu tłumaczy ją jeszcze raz; gdy dalej źle, zostaje oryginał.
_DIGITS = {**{0x0660 + i: str(i) for i in range(10)}, **{0x06F0 + i: str(i) for i in range(10)},
           **{0xFF10 + i: str(i) for i in range(10)}, **{0x0966 + i: str(i) for i in range(10)}}
_CYR = str.maketrans({"а": "a", "б": "b", "в": "w", "г": "g", "д": "d", "е": "e", "ж": "ż", "з": "z", "и": "i", "й": "j",
                      "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
                      "ф": "f", "х": "ch", "ц": "c", "ч": "cz", "ш": "sz", "ы": "y", "і": "i", "ь": "", "ъ": "",
                      "А": "A", "В": "W", "Е": "E", "К": "K", "М": "M", "Н": "N", "О": "O", "Р": "R", "С": "S", "Т": "T"})
_LATIN_TGT = ("pl", "en", "de", "fr", "es", "it", "pt", "cs", "sk", "nl")
_OTHER_SCRIPT = re.compile(r"[\u0400-\u04ff\u0590-\u05ff\u0600-\u06ff\u0900-\u097f\u0e00-\u0e7f]")
_THOUSANDS = re.compile(r"(?<!\d)\d{1,3}(?:[ ,.\u00a0\u202f]\d{3})+(?!\d)")
_WORD_NUMS = {"hundred": "100", "thousand": "1000", "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50",
              "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90", "fifteen": "15", "twelve": "12",
              "sto": "100", "stu": "100", "tysiąc": "1000", "dwadzieścia": "20", "trzydzieści": "30",
              "czterdzieści": "40", "pięćdziesiąt": "50"}
# nazwy miejsc, których się nie tłumaczy: ulica, most, plac, budynek… (nazwa = słowa z wielkiej litery przed tym słowem)
_PLACE = re.compile(r"\b((?:[A-Z][\w'’.-]+ ){1,3}(?:Street|Bridge|Road|Avenue|Square|Court|Lane|Station|Airport|Boulevard|Plaza))\b")


def clean_script(text: str, tgt: str) -> str:
    """Cyfry z innych pism → 0–9; pojedyncze litery cyrylicy wtrącone w łacińskie słowo → litery łacińskie."""
    text = re.sub(r"[\u0080-\u009f\u200b-\u200f\u2060\ufeff]", "", text.translate(_DIGITS))   # też niewidoczne znaki sterujące
    if tgt in _LATIN_TGT and re.search(r"[a-ząćęłńóśźż][\u0400-\u04ff]|[\u0400-\u04ff][a-ząćęłńóśźż]", text, re.I):
        text = text.translate(_CYR)
    return text


def numbers_in(text: str) -> set[str]:
    """Liczby zapisane cyframi, bez separatorów tysięcy („130,000” = „130 000” = „130000”)."""
    t = text.translate(_DIGITS)
    out = {re.sub(r"\D", "", m.group(0)) for m in _THOUSANDS.finditer(t)}
    t = _THOUSANDS.sub(" ", t)
    out |= set(re.findall(r"\d+", t))
    return out


def _word_numbers(text: str) -> set[str]:
    return {_WORD_NUMS[w] for w in re.findall(r"[^\W\d_]+", text.lower()) if w in _WORD_NUMS}


def line_problem(src: str, tr: str, tgt: str) -> str | None:
    """Co jest nie tak z tłumaczeniem jednej linii (None = w porządku). Sprawdzamy to, co da się sprawdzić pewnie:
    obce pismo, liczby (≥ 13 — mniejsze tłumacz często słusznie pisze słownie) i nazwy miejsc typu „Tower Bridge”."""
    if tgt in _LATIN_TGT and _OTHER_SCRIPT.search(tr):
        return "obce pismo"
    big = lambda xs: {x for x in xs if len(x) >= 3 or (len(x) == 2 and int(x) >= 13)}   # noqa: E731
    a, b = big(numbers_in(src)), big(numbers_in(tr))
    decades = {x[2:] for x in re.findall(r"\b((?:1[5-9]|20)\d0)s\b", src)}             # „1970s” → „latach 70.”
    lost = {x for x in a - b if not (x[2:] in decades and x[2:] in numbers_in(tr))}
    if lost:
        return "zgubiona liczba " + ", ".join(sorted(lost))
    added = b - a - decades - _word_numbers(src)          # „a hundred” → „100” to nie dopisana liczba
    if added:
        return "dopisana liczba " + ", ".join(sorted(added))
    for name in _PLACE.findall(src):
        if name.lower() not in tr.lower():
            return f"zmieniona nazwa „{name}”"
    return None


def keep_names(lines: list[str]) -> str:
    names = sorted({n for ln in lines for n in _PLACE.findall(ln)})
    return ("Names to keep exactly as written (do not translate them): " + "; ".join(names) + ".\n") if names else ""


def translate_lines(engine: Engine, lines: list[str], src: str | None, tgt: str,
                    context: list[str] | None = None, terms: str = "") -> list[str] | None:
    """Jedna porcja linii → lista tłumaczeń tej samej długości albo None (nie udało się)."""
    ctx = ""
    if context:
        ctx = ("Previous lines (context only, do NOT translate them):\n" +
               "\n".join(f"- {c}" for c in context) + "\n")
    extra = (terms.strip() + "\n" if terms.strip() else "") + keep_names(lines)
    prompt = PROMPT.format(src=name_en(src) if src else "the original language", tgt=name_en(tgt),
                           script=_script_hint(tgt), context=ctx, terms=extra,
                           lines="\n".join(f"{i}. {t}" for i, t in enumerate(lines, 1)))
    raw = engine.complete(prompt, as_json=True)
    res = _parse(raw, len(lines))
    if res is None:
        return None
    res = [clean_script(x, tgt) for x in res]
    if _bad(res, lines, tgt):
        return None
    return res


def translate_segments(engine: Engine, segments: list[dict], src: str | None, tgt: str,
                       log: Callable[[str], None] = lambda s: None, chunk: int = 20,
                       terms: str = "") -> tuple[list[dict], int]:
    """Tłumaczy segmenty porcjami. Zwraca (segmenty z tymi samymi czasami, liczba linii bez tłumaczenia).

    Każda linia przechodzi kontrolę (`line_problem`): przy błędzie jest tłumaczona jeszcze raz, sama; gdy dalej jest
    błędna, zostaje bez tłumaczenia ("text": null → w wyniku widać oryginał) — nie pokazujemy przekręconej liczby."""
    texts = [s["text"] for s in segments]
    out: list[str | None] = [None] * len(texts)

    def run(lo: int, hi: int, size: int) -> None:
        for a in range(lo, hi, size):
            b = min(hi, a + size)
            ctx = texts[max(0, a - 2):a]
            res = None
            for _ in (1, 2):                          # jedna ponowna próba z tą samą porcją
                try:
                    res = translate_lines(engine, texts[a:b], src, tgt, ctx, terms)
                except LLMError as e:
                    log(f"        ! tłumaczenie {tgt}: {str(e)[:80]}")
                    if "repeat" not in str(e).lower():   # Ollama nie działa itp. — przerwij ten język
                        raise
                    res = None                            # przerwana odpowiedź — jak zła odpowiedź
                if res is not None:
                    break
            if res is not None:
                out[a:b] = res
            elif b - a > 1:                           # porcja nie przeszła — mniejsze kawałki
                run(a, b, max(1, (b - a) // 4))

    run(0, len(texts), chunk)
    # kontrola linia po linii: błędna linia → jedna ponowna próba (sama, z kontekstem) → dalej błędna = bez tłumaczenia
    fixed = dropped = 0
    for i, tr in enumerate(out):
        why = line_problem(texts[i], tr, tgt) if tr else None
        if not why:
            continue
        again = None
        try:
            again = translate_lines(engine, [texts[i]], src, tgt, texts[max(0, i - 2):i], terms)
        except LLMError as e:
            if "repeat" not in str(e).lower():
                raise
        if again and not line_problem(texts[i], again[0], tgt):
            out[i] = again[0]
            fixed += 1
        else:
            out[i] = None
            dropped += 1
            log(f"        tłumaczenie {tgt}, linia {i + 1}: {why} — zostaje oryginał")
    if fixed or dropped:
        log(f"        kontrola tłumaczenia {tgt}: poprawiono {fixed}, bez tłumaczenia {dropped}")
    if tgt == "pl":                               # baking soda → „soda oczyszczona”, nie „proszek do pieczenia”
        from .summary import fix_terms
        out = [fix_terms(x, s) if x else x for x, s in zip(out, texts)]
    failed = sum(1 for x in out if x is None)
    segs = [{"start": s["start"], "end": s["end"], "text": t} for s, t in zip(segments, out)]
    return segs, failed
