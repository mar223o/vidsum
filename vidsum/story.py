"""Streszczenie filmów „opowiadanych” (dokument, wykład, rozmowa, inne) — z linii mowy, część po części (0.11.10).

Pomiar 0.11.9 na dokumencie 24:50 („The Scariest Building in Europe”):
- opis całości dostawał oś czasu obciętą do ~2,5 min → „Najważniejsze” kończyło się na 02:31;
- fakty pisane przez model własnymi słowami przekręcały treść („10 times thinner” → „dziesięciokrotnie grubsza”,
  „uncle and aunt” → „brata i siostrę”, „several billion times” → „setki razy”);
- odpowiedź z momentami urwała się na limicie i zniknęły cytaty oraz rozdziały;
- reklama sponsora („20% rabatu na Delete Me”) trafiła do faktów i wskazówek.

Teraz: film dzielony na części (≈ 4 min); dla każdej model podaje tytuł, 2–3 zdania i NUMERY linii z faktami,
cytatem i reklamą. Tekst faktów i cytatów bierzemy z transkrypcji (po polsku — z tłumaczenia linii, gdy gotowe).
Rozdziały = części. Opis całości powstaje ze streszczeń części, więc obejmuje cały film.
"""
from __future__ import annotations

import re

from .analysis import ts

FRAG_PROMPT = """Numbered lines of an automatic transcript of one part ({a}–{b}) of a video ({typ_en}). {meta}
Answer ONLY with JSON:
{{"tytul": "2–5 words in POLISH: the topic of this part",
 "streszczenie": "2–3 sentences in POLISH: what this part says — concretely, with names, numbers and dates exactly as in the lines",
 "fakty": [at most 5 line NUMBERS: the lines with the most important concrete facts (numbers, people, dates, places, claims). Choose — do not list every line],
 "cytat": the NUMBER of the one line with the most striking sentence, or null,
 "reklama": [NUMBERS of lines that are an advertisement, a sponsor message or channel self-promotion; empty list if none]}}
Rules: use only these lines, no outside knowledge. Translate meaning exactly (thinner stays thinner, uncle stays uncle).
Never write line numbers or the word "line" inside tytul or streszczenie. Do not describe advertisements in streszczenie.
{screen}
LINES:
{lines}
"""

REDUCE_PROMPT = """Masz streszczenia kolejnych części filmu (typ: {typ}) i wybrane fakty z jego transkrypcji. {meta}
Napisz po polsku opis CAŁEGO filmu. Każde zdanie musi wynikać z poniższych części; nie dodawaj wiedzy spoza filmu
ani liczb, których tu nie ma. Pomiń reklamy i autopromocję kanału. W tekście nie używaj oznaczeń [C1], [F1].

CZĘŚCI (oznaczenie, czas, tytuł: treść):
{parts}

FAKTY (oznaczenie, czas, zdanie z filmu):
{facts}

Odpowiedz WYŁĄCZNIE JSON-em:
{{"tytul": "krótki tytuł (3–6 słów)",
 "teza": "jedno zdanie: o co chodzi i co z tego wynika",
 "streszczenie": ["akapit 1 (3–4 zdania): temat i cel filmu", "akapit 2 (4–6 zdań): najważniejsze wątki po kolei, z liczbami i nazwami", "akapit 3 (3–4 zdania): dalsze wątki do końca filmu", "akapit 4 (2–3 zdania): najważniejszy wniosek"],
 "do_zapamietania": "jedno zdanie",
 "najwazniejsze": [{{"zrodlo": "oznaczenie części albo faktu, z którego to wynika, np. C2 albo F5", "tytul": "2–5 słów", "opis": "1–2 zdania"}}],
 "wnioski": ["3–6 najważniejszych wniosków"],
 "szczera_ocena": "2–3 zdania: co wartościowe, czego brakuje, co wątpliwe",
 "czego_nie_wiadomo": ["czego film nie mówi, a widz chciałby wiedzieć"],
 "pytania": ["3–5 pytań, które widz mógłby zadać"]}}
„najwazniejsze”: 3–6 pozycji z RÓŻNYCH części, po kolei od początku do końca filmu.
Streszczenie: razem około {words} słów.
"""

# Schematy odpowiedzi (Ollama „structured outputs”): model MUSI oddać numery jako liczby i najwyżej 5 faktów.
# Pomiar na prawdziwym modelu bez schematu: „fakty” jako 20–40 pozycji (albo cała transkrypcja części jako tekst —
# odpowiedź urwana na limicie 700 tokenów), „cytat” jako tekst. Krótsza odpowiedź = krótszy czas każdej części.
FRAG_SCHEMA = {"type": "object",
               "properties": {"tytul": {"type": "string"}, "streszczenie": {"type": "string"},
                              "fakty": {"type": "array", "items": {"type": "integer"}, "maxItems": 5},
                              "cytat": {"type": ["integer", "null"]},
                              "reklama": {"type": "array", "items": {"type": "integer"}, "maxItems": 40}},
               "required": ["tytul", "streszczenie", "fakty", "cytat", "reklama"]}
_STR_LIST = {"type": "array", "items": {"type": "string"}}
REDUCE_SCHEMA = {"type": "object",
                 "properties": {"tytul": {"type": "string"}, "teza": {"type": "string"},
                                "streszczenie": {**_STR_LIST, "minItems": 3, "maxItems": 4},
                                "do_zapamietania": {"type": "string"},
                                "najwazniejsze": {"type": "array", "minItems": 3, "maxItems": 6,
                                                  "items": {"type": "object",
                                                            "properties": {"zrodlo": {"type": "string"}, "tytul": {"type": "string"},
                                                                           "opis": {"type": "string"}},
                                                            "required": ["zrodlo", "tytul", "opis"]}},
                                "wnioski": {**_STR_LIST, "maxItems": 6}, "szczera_ocena": {"type": "string"},
                                "czego_nie_wiadomo": {**_STR_LIST, "maxItems": 4}, "pytania": {**_STR_LIST, "maxItems": 5}},
                 "required": ["tytul", "teza", "streszczenie", "do_zapamietania", "najwazniejsze", "wnioski",
                              "szczera_ocena", "czego_nie_wiadomo", "pytania"]}

_TYP_EN = {"wyklad": "lecture / talk / explanation", "dokument": "documentary / report", "inne": "video",
           "trening": "workout", "sport": "sport / football training", "poradnik": "tutorial", "przepis": "recipe"}

# reklama / autopromocja — potwierdzenie dla linii wskazanych przez model (sam model bywa nadgorliwy)
_AD = re.compile(r"sponsor|promo(?:tion)? code|discount|\d+\s?% off|% rabat|use (?:the )?code|link in the description|"
                 r"link (?:is )?in the description|thanks?(?: again)? to [\w. ]{2,30} for (?:supporting|sponsoring)|"
                 r"brought to you by|sign up|subscribe|newsletter|\.com slash|\bslash \w+\b|scan (?:this|the) qr|"
                 r"kod rabatowy|link w opisie|sponsorem|zniżk\w+|subskryb\w+", re.I)
_SPONSOR = re.compile(r"(?i:thanks?(?: again)? to|sponsored by|sponsor(?:em)? (?:of this video is|tego (?:filmu|odcinka) jest))"
                      r" ([A-Z][\w.]*(?: [A-Z][\w.]*){0,2})")
_DOMAIN = re.compile(r"\b([a-z][\w-]{2,}\.(?:com|me|io|pl))\b", re.I)


def _ids(x, valid: set) -> list[int]:
    out = []
    for v in x if isinstance(x, list) else [x]:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n in valid and n not in out:
            out.append(n)
    return sorted(out)


def split_parts(lines: list[dict], duration: float, max_chars: int = 4500) -> list[list[dict]]:
    """Części po ≈ 4 min (1 część dla krótkiego filmu), nie dłuższe niż `max_chars` tekstu."""
    if not lines:
        return []
    n = max(1, min(8, round(duration / 240)))
    total = sum(len(ln["tekst"]) for ln in lines)
    n = max(n, -(-total // max_chars))
    target = total / n
    parts, cur, size = [], [], 0
    for ln in lines:
        if cur and size >= target and len(parts) < n - 1:
            parts.append(cur)
            cur, size = [], 0
        cur.append(ln)
        size += len(ln["tekst"])
    if cur:
        parts.append(cur)
    return parts


def _flat(text: str) -> str:
    return re.sub(r"[^a-z0-9ąćęłńóśźż]", "", text.lower())


def ad_spans(lines: list[dict], marked: set[int]) -> list[dict]:
    """Reklamy sponsora i autopromocja kanału → bloki {start, end, marka, linie}.

    Trzy sygnały: (1) słowa reklamy w linii („20% off”, „link in the description”, „thanks to X for supporting”),
    (2) nazwa sponsora z takiej linii powtórzona w innych liniach („Delete Me”, „Delete.me”), (3) linie wskazane przez
    model. Linie z sygnałem leżące blisko siebie (≤ 6 linii przerwy) tworzą blok; blok zostaje, gdy ma choć jedną linię
    ze słowami reklamy albo ≥ 3 linie z nazwą sponsora — samo wskazanie modelu nie wystarcza (bywa nadgorliwy)."""
    by_n = {ln["n"]: ln for ln in lines}
    trig = {ln["n"] for ln in lines if _AD.search(ln["tekst"])}
    brand = ""
    for ln in lines:
        m = _SPONSOR.search(ln["tekst"])
        if m:
            brand = m.group(1).strip(" .,")
            break
    key = _flat(brand)
    named = {ln["n"] for ln in lines if len(key) >= 4 and key in _flat(ln["tekst"])}
    signal = sorted(trig | named | (marked & set(by_n)))
    blocks: list[list[int]] = []
    for n in signal:
        if blocks and n - blocks[-1][-1] <= 6:
            blocks[-1].append(n)
        else:
            blocks.append([n])
    out = []
    for bl in blocks:
        if not (set(bl) & trig) and len(set(bl) & named) < 3:
            continue
        ns = [n for n in range(bl[0], bl[-1] + 1) if n in by_n]
        text = " ".join(by_n[n]["tekst"] for n in ns)
        name = brand if key and key in _flat(text) else ""
        if not name:
            m = _DOMAIN.search(text)
            name = m.group(1) if m else ""
        out.append({"start": by_n[ns[0]]["t"], "end": by_n[ns[-1]]["end"], "marka": name, "linie": ns})
    return out


def sentence_at(n: int, by_n: dict, limit: int = 3) -> list[int]:
    """Numery linii tworzących całe zdanie wokół linii n. Whisper tnie zdania na pauzach („In August 2025,” /
    „then Deputy Prime Minister Angela Rayner asked China…”) — fakt z samej drugiej linii zgubiłby datę."""
    ns = [n]
    while len(ns) < limit and ns[0] - 1 in by_n:
        prev = by_n[ns[0] - 1]["tekst"].strip()
        cur = by_n[ns[0]]["tekst"].strip()
        if prev.endswith((".", "?", "!", "…")) or not cur[:1].islower() and not prev.endswith(","):
            break
        ns.insert(0, ns[0] - 1)
    while len(ns) < limit and ns[-1] + 1 in by_n:
        cur = by_n[ns[-1]]["tekst"].strip()
        nxt = by_n[ns[-1] + 1]["tekst"].strip()
        if cur.endswith((".", "?", "!", "…")) or not (cur.endswith(",") or nxt[:1].islower()):
            break
        ns.append(ns[-1] + 1)
    return ns


def _join(ns: list[int], by_n: dict, field: str) -> str:
    parts = [by_n[n].get(field) or "" for n in ns]
    return " ".join(x.strip() for x in parts if x.strip()) if all(parts) else ""


def _kind(text: str) -> str:
    if re.search(r"\b(1[5-9]|20)\d\d\b", text) or re.search(r"\b(january|february|march|april|may|june|july|august|"
                                                            r"september|october|november|december|stycz|lut|mar|kwie|"
                                                            r"maj|czerw|lip|sierp|wrze|paźdz|listop|grud)\w*\b", text, re.I):
        return "data"
    if re.search(r"(?<![A-Za-z])\d", text):          # „MI6” to nazwa, nie liczba
        return "liczba"
    return "fakt"


def _spread(xs: list, k: int) -> list:
    if len(xs) <= k:
        return xs
    step = len(xs) / k
    return [xs[int(i * step)] for i in range(k)]


# ---------- wybór faktów: gęstość informacji + wskazanie modelu ----------
# Pomiar na prawdziwym modelu (gemma3:4b, gałąź 0.12.0, dokument 24:50): na prośbę o „najwyżej 5 numerów linii” model
# oddał ciągi po 20–40 kolejnych numerów (prawie każdą linię), więc „pierwsze 5” dawało pierwsze zdania części
# („Hej, nasza autorka Amanda będzie narracją tego odcinka” jako fakt). Dlatego o wyborze decyduje to, co w zdaniu
# widać: liczby, daty, kwoty, nazwy własne. Wskazanie modelu liczy się tylko wtedy, gdy naprawdę wybrał (≤ 8 linii).
_UNIT = re.compile(r"[%$£€]|\b(?:million|billion|thousand|percent|kilomet\w+|met(?:er|re)s?|miles?|years?|pounds?|dollars?|"
                   r"milion\w*|miliard\w*|tysi\w+|procent\w*|kilometr\w*|metr\w*|lat|funt\w*|dolar\w*|złot\w*)\b", re.I)
_META = re.compile(r"\b(?:episode|this video|our videos?|channel|intro\b|narrat\w+|voice ?over|writer'?s? room|sponsor\w*|"
                   r"subscrib\w+|newsletter|odcin\w+|kanał\w*|w tym filmie|subskryb\w+)\b", re.I)
_NAME = re.compile(r"(?<![.!?…] )(?<!^)\b[A-ZŻŹĆŁŚÓ][\w'’-]{2,}")


def info_score(text: str) -> float:
    """Ile konkretu jest w zdaniu: liczby, daty, jednostki, nazwy własne; minus za zdania o samym filmie i pytania."""
    sc = 0.0
    nums = [int(x) for x in re.findall(r"(?<![A-Za-z\d])\d{1,9}(?![\d])", text)]
    unit = bool(_UNIT.search(text))
    date = _kind(text) == "data"
    if nums:                                          # „it's a 10” (pomyłka Whispera) to nie fakt; 343 mln, 2018, 54 — tak
        sc += 3 if (max(nums) >= 13 or unit or date) else 1
    if date:
        sc += 1
    if unit:
        sc += 1
    sc += min(2, len(set(_NAME.findall(text))))
    if _META.search(text):
        sc -= 4
    if text.rstrip().endswith("?"):
        sc -= 2
    n = len(text.split())
    if n < 6:
        sc -= 2
    elif n >= 12:
        sc += 0.5
    return sc


def pick_facts(part: list[dict], by_n: dict, model_ids: list[int], skip: set[int], k: int = 5) -> list[list[int]]:
    """Linie-fakty jednej części → lista grup numerów linii (całe zdania), po kolei. Najwyżej k."""
    trusted = set(model_ids) if 0 < len(model_ids) <= 8 else set()
    cands = []
    for ln in part:
        ns = sentence_at(ln["n"], by_n)
        if set(ns) & skip:
            continue
        text = _join(ns, by_n, "tekst")
        sc = info_score(text) + (3 if set(ns) & trusted else 0)
        cands.append((sc, ns))
    cands.sort(key=lambda x: (-x[0], x[1][0]))
    chosen: list[list[int]] = []
    used: set[int] = set()
    for sc, ns in cands:
        if len(chosen) >= k or sc < 3:
            break
        if set(ns) & used or any(x - 1 in used or x + 1 in used for x in ns):
            continue                                  # nie dwa sąsiednie zdania — fakty mają pochodzić z całej części
        chosen.append(ns)
        used.update(ns)
    if not chosen and not trusted:                    # część bez liczb i nazw (opis techniki) — dwa najtreściwsze zdania
        for sc, ns in cands:
            if len(chosen) >= 2 or sc < 0.5:
                break
            if set(ns) & used or any(x - 1 in used or x + 1 in used for x in ns):
                continue
            chosen.append(ns)
            used.update(ns)
    if not chosen:                                    # krótki film bez liczb i nazw („Exhibit A. The Henley.”)
        for n in sorted(trusted)[:3]:
            ns = sentence_at(n, by_n)
            while len(_join(ns, by_n, "tekst").split()) < 4 and ns[0] - 1 in by_n and len(ns) < 3:
                ns.insert(0, ns[0] - 1)
            if set(ns) & (skip | used) or len(_join(ns, by_n, "tekst").split()) < 3:
                continue
            chosen.append(ns)
            used.update(ns)
    return sorted(chosen, key=lambda ns: ns[0])


def find_quote(value, part: list[dict], by_n: dict) -> list[int]:
    """Cytat wskazany przez model → numery linii. Model bywa proszony o NUMER, a oddaje TEKST zdania
    (pomiar: „cytat”: "But in practice, things are more complicated.") — wtedy szukamy tego zdania w liniach części."""
    valid = {ln["n"] for ln in part}
    ids = _ids(value, valid)
    if ids:
        return sentence_at(ids[0], by_n)
    words = re.findall(r"[^\W_]+", str(value or "").lower())
    if len(words) < 3:
        return []
    best, best_ns = 0.0, []
    for i, ln in enumerate(part):
        for width in (1, 2, 3):
            ns = [x["n"] for x in part[i:i + width]]
            got = set(re.findall(r"[^\W_]+", _join(ns, by_n, "tekst").lower()))
            hit = sum(w in got for w in words) / len(words)
            score = hit - 0.05 * (width - 1)
            if hit >= 0.8 and score > best:
                best, best_ns = score, ns
    return best_ns


_REF = re.compile(r"\s*[\(\[]\s*(?:lini[aeąę]|linie|linii|lines?|wiersz\w*)\s*\d+(?:\s*(?:,|i|and|oraz|-|–)\s*\d+)*\s*[\)\]]|\s*\[[CF]\d+\]", re.I)


def scrub(x):
    """Usuwa z tekstów modelu odwołania do numerów linii i oznaczeń („Henley (linia 8)”, „[F3]”) — to rusztowanie
    zapytania, nie treść dla widza (pomiar na prawdziwym modelu: reel o ubraniach)."""
    if isinstance(x, str):
        y = _REF.sub("", x)
        y = re.sub(r",?\s*(?:lini[aeąę]|linie|linii)\s*\d+(?:\s*(?:,|i|oraz)\s*\d+)*", "", y, flags=re.I)
        return re.sub(r"\s{2,}", " ", re.sub(r"\s+([.,;:])", r"\1", y)).strip()
    if isinstance(x, list):
        return [scrub(v) for v in x]
    if isinstance(x, dict):
        return {k: scrub(v) for k, v in x.items()}
    return x


_YOU = re.compile(r"\b(?:you|your|you've|you're|yours|ty|twoj\w*|twój|ci|ciebie)\b", re.I)


def extend_ad_back(ad: dict, by_n: dict, max_s: float = 45.0) -> dict:
    """Wstęp reklamy przed pierwszą wzmianką o sponsorze: linie zwrócone do widza („Wait, you've been shopping for
    espresso machines, haven't you?” … „They intercept your info…” … „But there's your way out…”). Początek bloku
    cofamy do najwcześniejszej linii z „you / your” (najwyżej `max_s` sekund wstecz), jeśli od niej do reklamy co
    najmniej 40% linii mówi do widza. Tylko dla dokumentu — narrator dokumentu zwykle nie mówi do widza na „ty”."""
    first = ad["linie"][0]
    t0 = by_n[first]["t"]
    back = []
    n = first - 1
    while n in by_n and t0 - by_n[n]["t"] <= max_s:
        back.insert(0, n)
        n -= 1
    best = None
    for i, n in enumerate(back):
        run = back[i:]
        if _YOU.search(by_n[n]["tekst"]) and sum(bool(_YOU.search(by_n[x]["tekst"])) for x in run) >= max(2, 0.4 * len(run)):
            best = i
            break
    if best is None:
        return ad
    run = back[best:]
    return {**ad, "start": by_n[run[0]]["t"], "linie": run + ad["linie"]}


def screen_context(part: list[dict], ocr: list[dict] | None, limit: int = 600) -> str:
    """Napisy z ekranu w tej części jako kontekst (bez napisów powtarzających mowę). Pomiar na prawdziwym modelu: reel
    o ubraniach jest odpowiedzią na komentarz widoczny tylko na ekranie („I wish men had sluttier outfit options…”) —
    bez niego model streścił żart jako poradnik o modzie."""
    if not ocr or not part:
        return ""
    from .ocr import _ocr_key, is_overlay_junk
    a, b = part[0]["t"] - 5, part[-1]["end"] + 1      # napis tuż przed pierwszym zdaniem też jest kontekstem
    speech = set(re.findall(r"[^\W_]+", " ".join(ln["tekst"] for ln in part).lower()))
    groups: dict[float, list[str]] = {}               # napisy widoczne w tej samej chwili = jedno zdanie na ekranie
    seen: set[str] = set()
    for o in ocr:
        text = (o.get("text") or "").strip()
        if not (a <= float(o.get("start", 0)) <= b) or len(text) < 4 or is_overlay_junk(text):
            continue
        w = re.findall(r"[^\W_]+", text.lower())
        key = _ocr_key(text)
        if not w or key in seen or sum(x in speech for x in w) >= 0.7 * len(w):
            continue
        seen.add(key)
        groups.setdefault(round(float(o["start"]), 1), []).append(text)
    out, size = [], 0
    for t, texts in sorted(groups.items()):
        row = f"- {ts(t)} {' '.join(texts)[:200]}"
        if size + len(row) > limit:
            break
        out.append(row)
        size += len(row)
    return ("ON-SCREEN TEXT in this part (context only — it can explain what the speaker reacts to):\n"
            + "\n".join(out) + "\n") if out else ""


def _about_ad(text: str, ads: list[dict]) -> bool:
    flat = _flat(text)
    return any(len(_flat(a.get("marka") or "")) >= 4 and _flat(a["marka"]) in flat for a in ads)


def _no_ad_sentences(text: str, ads: list[dict]) -> str:
    """Usuwa zdania wymieniające sponsora („…przez firmy takie jak Delete.me, które usunęło 247 przypadków…”)."""
    if not ads or not text:
        return text
    return " ".join(x for x in re.split(r"(?<=[.!?])\s+", text) if x and not _about_ad(x, ads)).strip()


def _stems(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[^\W_]{4,}", text.lower())}


def _sim(a: str, b: str) -> float:
    wa = {w for w in re.findall(r"[^\W_]{4,}", a.lower())}
    wb = {w[:6] for w in re.findall(r"[^\W_]{4,}", b.lower())}
    wa = {w[:6] for w in wa}
    return len(wa & wb) / len(wa) if wa else 0.0


def story_summary(engine, lines: list[dict], typ: str, meta_line: str, duration: float, words: int,
                  try_fn, loads, log=lambda s: None, record=lambda *a: None, par: int = 1,
                  ocr: list[dict] | None = None) -> dict:
    """Zwraca słownik pól streszczenia (jak opis całości) + `fakty`, `rozdzialy`, `cytaty`, `momenty`, `reklamy`."""
    from concurrent.futures import ThreadPoolExecutor
    parts = split_parts(lines, duration)
    by_n = {ln["n"]: ln for ln in lines}
    log(f"        części filmu: {len(parts)}" + (f" ({min(par, len(parts))} naraz)" if par > 1 and len(parts) > 1 else ""))
    # reklamy pewne (słowa reklamy, nazwa sponsora) znamy przed zapytaniem — model ich nie dostaje, więc ich nie streści
    pre = {n for a in ad_spans(lines, set()) for n in a["linie"]}

    def one(part: list[dict]) -> dict:
        rows, gap = [], False
        for ln in part:
            if ln["n"] in pre:
                if not gap:
                    rows.append("(an advertisement was removed here)")
                gap = True
                continue
            gap = False
            rows.append(f"[{ln['n']}] {ts(ln['t'])} {ln['tekst']}")
        if not any(r.startswith("[") for r in rows):
            return {}
        pr = FRAG_PROMPT.format(a=ts(part[0]["t"]), b=ts(part[-1]["end"]), typ_en=_TYP_EN.get(typ, "video"),
                                meta=meta_line, lines="\n".join(rows), screen=screen_context(part, ocr))
        raw = try_fn(engine, pr, log, max_tokens=700, schema=FRAG_SCHEMA)
        record("czesc", pr, raw)
        d = loads(raw)
        if not str(d.get("streszczenie") or "").strip():       # pusta / nieczytelna odpowiedź — jedna próba od nowa
            log(f"        ! część {ts(part[0]['t'])}–{ts(part[-1]['end'])}: pusta odpowiedź — ponawiam")
            raw = try_fn(engine, pr, log, max_tokens=700, seed=11, schema=FRAG_SCHEMA)
            record("czesc_ponownie", pr, raw)
            d = loads(raw) or d
        return d

    with ThreadPoolExecutor(max_workers=max(1, min(par, len(parts)))) as pool:
        res = list(pool.map(one, parts))

    marked: set[int] = set()
    for part, d in zip(parts, res):
        ids = _ids(d.get("reklama"), {ln["n"] for ln in part})
        if len(ids) <= max(8, len(part) // 2):         # „wszystko jest reklamą” to nie wskazanie
            marked.update(ids)
    ads = ad_spans(lines, marked)
    if typ == "dokument":
        ads = [extend_ad_back(a, by_n) for a in ads]
    ad_lines = {n for a in ads for n in a["linie"]}
    if ads:
        log("        reklamy: " + ", ".join(f"{ts(a['start'])}–{ts(a['end'])}" + (f" ({a['marka']})" if a["marka"] else "")
                                         for a in ads))

    chapters, facts, quotes = [], [], []
    for i, (part, d) in enumerate(zip(parts, res)):
        valid = {ln["n"] for ln in part}
        start = part[0]["t"] if i else 0.0
        end = parts[i + 1][0]["t"] if i + 1 < len(parts) else duration
        content = [ln for ln in part if ln["n"] not in ad_lines]
        title = scrub(str(d.get("tytul") or "").strip())
        summ = scrub(str(d.get("streszczenie") or "").strip())
        chapters.append({"start": round(start, 2), "end": round(end, 2),
                         "tytul": title or ("Reklama" if not content else f"Część {i + 1}"),
                         "opis": summ, "reklama": not content, "n": i + 1})
        k = 5 if len(parts) > 1 else max(3, min(6, len(content) // 5))
        for ns in pick_facts(content, by_n, _ids(d.get("fakty"), valid), ad_lines, k):
            orig = _join(ns, by_n, "tekst")
            facts.append({"t": by_n[ns[0]]["t"], "tekst": _join(ns, by_n, "pl") or orig, "oryginal": orig,
                          "czasy": [by_n[x]["t"] for x in ns], "rodzaj": _kind(orig), "zrodlo": "mowa", "czesc": i + 1})
        ns = find_quote(d.get("cytat"), content, by_n)
        orig = _join(ns, by_n, "tekst") if ns else ""
        if ns and not set(ns) & ad_lines and len(orig.split()) >= 3 and not _META.search(orig):
            quotes.append({"t": by_n[ns[0]]["t"], "tekst": orig, "tlumaczenie": _join(ns, by_n, "pl"),
                           "czasy": [by_n[x]["t"] for x in ns]})

    for c in chapters:                                # zdania o sponsorze nie idą dalej do opisu całości
        if not c["reklama"]:
            c["opis"] = _no_ad_sentences(c["opis"], ads)
    live = [c for c in chapters if not c["reklama"]]
    # bardzo długi film (1–2 h = 20+ części): zapytanie o całość musi się zmieścić w stałym kontekście modelu —
    # streszczenia części przycinamy, a faktów pokazujemy najwyżej 40, równo z całego filmu (numeracja F zostaje)
    cut = 10_000 // max(1, len(live)) if len(live) > 12 else 2000
    parts_txt = "\n".join(f"[C{c['n']}] {ts(c['start'])}–{ts(c['end'])} {c['tytul']}: {c['opis'][:cut]}" for c in live)
    shown = set(map(id, _spread(facts, 40)))
    facts_txt = "\n".join(f"[F{j}] {ts(f['t'])} {f['oryginal'][:220]}" for j, f in enumerate(facts, 1) if id(f) in shown) or "—"
    pr = REDUCE_PROMPT.format(typ=typ, meta=meta_line, parts=parts_txt, facts=facts_txt, words=words)
    raw = try_fn(engine, pr, log, max_tokens=1600, schema=REDUCE_SCHEMA)
    record("opis_calosci", pr, raw)
    p = scrub(loads(raw))
    if not isinstance(p, dict):
        p = {}
    for k in ("streszczenie", "wnioski"):             # zdania o sponsorze nie należą do streszczenia filmu
        if isinstance(p.get(k), list):
            p[k] = [y for y in (_no_ad_sentences(str(x), ads) for x in p[k]) if y]

    if not [x for x in (p.get("streszczenie") or []) if str(x).strip()] and live:
        # opis całości nie przyszedł albo jest pusty (urwana odpowiedź) — użytkownik i tak dostaje streszczenie:
        # akapity ze streszczeń części; „Najważniejsze” = części po kolei
        log("        ! opis całości pusty — streszczenie złożone ze streszczeń części")
        p["streszczenie"] = [c["opis"] for c in live if c["opis"]][:8]
        p.setdefault("teza", (live[0]["opis"].split(". ")[0].rstrip(".") + ".") if live[0]["opis"] else "")
        p["najwazniejsze"] = [{"zrodlo": f"C{c['n']}", "tytul": c["tytul"], "opis": c["opis"].split(". ")[0].rstrip(".") + "."}
                              for c in _spread(live, 6) if c["opis"]]

    # „Najważniejsze”: czas z oznaczenia części/faktu, a gdy model go nie podał albo podał zły — z podobieństwa treści
    # do streszczeń części. Czasu podanego liczbą nie bierzemy: prawdziwy model oddawał raz minuty („t”: 8, 17, 21),
    # raz numery linii („t”: 8, 13) — wszystko lądowało na początku filmu.
    by_c = {c["n"]: c for c in live}

    def _moment(text: str, c: dict) -> float:
        """Chwila w części, o której mówi pozycja: linia najbardziej podobna do jej tekstu (nazwa, liczba), a gdy żadna
        nie pasuje — początek części."""
        own = [ln for ln in parts[c["n"] - 1] if ln["n"] not in ad_lines]
        want = _stems(text)
        sets = [(ln, _stems(ln["tekst"] + " " + (ln.get("pl") or ""))) for ln in own]
        freq: dict[str, int] = {}
        for _, ws in sets:
            for w in ws:
                freq[w] = freq.get(w, 0) + 1
        best, best_sc = None, 0.0
        for ln, ws in sets:
            common = want & ws
            # dwa wspólne słowa albo jedno, ale charakterystyczne (pada w najwyżej 2 liniach części: „Henley”, „Rayner”)
            sc = len(common) + sum(1.0 for w in common if freq[w] <= 2)
            if sc >= 2 and sc > best_sc:
                best, best_sc = ln, sc
        return best["t"] if best else c["start"]

    hl, used_t, per_ch = [], set(), {}
    for x in p.get("najwazniejsze") or []:
        if not isinstance(x, dict) or not str(x.get("tytul") or "").strip():
            continue
        text = f"{x.get('tytul', '')} {x.get('opis', '')}"
        ref = re.search(r"\b([CF])\s*(\d+)\b", str(x.get("zrodlo") or ""), re.I)
        t = None
        if ref and ref.group(1).upper() == "F" and 1 <= int(ref.group(2)) <= len(facts):
            t = facts[int(ref.group(2)) - 1]["t"]
        elif ref and int(ref.group(2)) in by_c:
            t = _moment(text, by_c[int(ref.group(2))])
        if t is None and live:
            t = _moment(text, max(live, key=lambda c: _sim(text, c["tytul"] + " " + c["opis"])))
        if t is None or any(a["start"] - 1 <= t <= a["end"] + 1 for a in ads) or _about_ad(text, ads):
            continue
        ch = next((c["n"] for c in reversed(live) if c["start"] <= t), 0)
        if len(live) >= 3 and per_ch.get(ch, 0) >= 2:
            continue                                  # „z różnych części”: najwyżej dwie pozycje z jednej
        per_ch[ch] = per_ch.get(ch, 0) + 1
        while t in used_t:                            # dwie pozycje z tej samej części — nie ten sam znacznik czasu
            t += 1.0
        used_t.add(t)
        hl.append({"t": t, "tytul": x.get("tytul"), "opis": x.get("opis") or "", "zrodlo": "mowa"})
    hl.sort(key=lambda h: h["t"])
    p["najwazniejsze"] = hl
    p["rozdzialy"] = [{k: v for k, v in c.items() if k not in ("reklama", "n")} for c in chapters]
    p["fakty"] = [{k: v for k, v in f.items() if k != "czesc"} for f in facts]
    p["cytaty"] = _spread(quotes, 4 if duration < 600 else 8)
    p["momenty"] = [{"t": f["t"], "tekst": f["tekst"]} for f in _spread(facts, 8)]
    p["reklamy"] = [{k: v for k, v in a.items() if k != "linie"} for a in ads]
    return p


def localize(summary: dict, segments: list[dict], pl_segments: list[dict] | None) -> int:
    """Gdy tłumaczenie linii jest gotowe: fakty, momenty i tłumaczenia cytatów po polsku — z tłumaczenia TYCH SAMYCH
    linii transkrypcji, a nie z przeróbki modelu. Zwraca liczbę podmienionych pozycji."""
    if not pl_segments or len(pl_segments) != len(segments):
        return 0
    by_t = {round(float(s["start"]), 2): (p.get("text") or "").strip() for s, p in zip(segments, pl_segments)}

    def pl_for(times) -> str:
        parts = [by_t.get(round(float(t), 2), "") for t in times or []]
        return " ".join(parts) if parts and all(parts) else ""

    n = 0
    done: dict[float, str] = {}
    for f in (summary.get("co_masz_zrobic") or {}).get("fakty", []):
        if f.get("oryginal") and f.get("tekst") == f["oryginal"]:
            new = pl_for(f.get("czasy"))
            if new:
                f["tekst"] = done[f["t"]] = new
                n += 1
    for m in summary.get("momenty", []):
        if m["t"] in done and m["tekst"] != done[m["t"]]:
            m["tekst"] = done[m["t"]]
            n += 1
    for q in summary.get("cytaty", []):
        if not q.get("tlumaczenie"):
            new = pl_for(q.get("czasy"))
            if new:
                q["tlumaczenie"] = new
                n += 1
    for x in summary.get("pokazane", []):                # „Pokazane na ekranie”: słowa narratora po polsku
        if not x.get("mowa_pl"):
            new = pl_for(x.get("czasy"))
            if new:
                x["mowa_pl"] = new
                n += 1
    return n
