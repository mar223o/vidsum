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
 "fakty": [line numbers (integers) with the most important concrete facts of this part: numbers, people, dates, places, claims — at most 5],
 "cytat": one line number with the most striking sentence of a speaker, or null,
 "reklama": [line numbers that are an advertisement, a sponsor message or channel self-promotion; empty list if none]}}
Use only these lines; do not add knowledge from outside. Translate meaning exactly (thinner stays thinner, uncle stays uncle).

LINES:
{lines}
"""

REDUCE_PROMPT = """Masz streszczenia kolejnych części filmu (typ: {typ}) i wybrane fakty z jego transkrypcji. {meta}
Napisz po polsku opis CAŁEGO filmu. Każde zdanie musi wynikać z poniższych części; nie dodawaj wiedzy spoza filmu
ani liczb, których tu nie ma. Pomiń reklamy i autopromocję kanału.

CZĘŚCI:
{parts}

FAKTY:
{facts}

Odpowiedz WYŁĄCZNIE JSON-em:
{{"tytul": "krótki tytuł (3–6 słów)",
 "teza": "jedno zdanie: o co chodzi i co z tego wynika",
 "streszczenie": ["akapit 1 (3–4 zdania): temat i cel filmu", "akapit 2 (4–6 zdań): najważniejsze wątki po kolei, z liczbami i nazwami", "akapit 3 (3–4 zdania): dalsze wątki do końca filmu", "akapit 4 (2–3 zdania): najważniejszy wniosek"],
 "do_zapamietania": "jedno zdanie",
 "najwazniejsze": [{{"t": sekundy, "tytul": "2–5 słów", "opis": "1–2 zdania"}}],
 "wnioski": ["3–6 najważniejszych wniosków"],
 "szczera_ocena": "2–3 zdania: co wartościowe, czego brakuje, co wątpliwe",
 "czego_nie_wiadomo": ["czego film nie mówi, a widz chciałby wiedzieć"],
 "pytania": ["3–5 pytań, które widz mógłby zadać"]}}
„najwazniejsze”: 3–6 pozycji z RÓŻNYCH części, od początku do końca filmu; „t” = czas początku części albo faktu.
Streszczenie: razem około {words} słów.
"""

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


def story_summary(engine, lines: list[dict], typ: str, meta_line: str, duration: float, words: int,
                  try_fn, loads, log=lambda s: None, record=lambda *a: None, par: int = 1) -> dict:
    """Zwraca słownik pól streszczenia (jak opis całości) + `fakty`, `rozdzialy`, `cytaty`, `momenty`, `reklamy`."""
    from concurrent.futures import ThreadPoolExecutor
    parts = split_parts(lines, duration)
    by_n = {ln["n"]: ln for ln in lines}
    log(f"        części filmu: {len(parts)}" + (f" ({min(par, len(parts))} naraz)" if par > 1 and len(parts) > 1 else ""))

    def one(part: list[dict]) -> dict:
        txt = "\n".join(f"[{ln['n']}] {ts(ln['t'])} {ln['tekst']}" for ln in part)
        pr = FRAG_PROMPT.format(a=ts(part[0]["t"]), b=ts(part[-1]["end"]), typ_en=_TYP_EN.get(typ, "video"),
                                meta=meta_line, lines=txt)
        raw = try_fn(engine, pr, log, max_tokens=700)
        record("czesc", pr, raw)
        return loads(raw)

    with ThreadPoolExecutor(max_workers=max(1, min(par, len(parts)))) as pool:
        res = list(pool.map(one, parts))

    marked: set[int] = set()
    for part, d in zip(parts, res):
        marked.update(_ids(d.get("reklama"), {ln["n"] for ln in part}))
    ads = ad_spans(lines, marked)
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
        title = str(d.get("tytul") or "").strip()
        summ = str(d.get("streszczenie") or "").strip()
        if not content:                               # cała część to reklama
            title, summ = title or "Reklama", summ
        chapters.append({"start": round(start, 2), "end": round(end, 2), "tytul": title or f"Część {i + 1}",
                         "opis": summ, "reklama": not content})
        seen: set[int] = set()
        for n in _ids(d.get("fakty"), valid)[:5]:
            ns = sentence_at(n, by_n)
            if set(ns) & ad_lines or set(ns) & seen:
                continue
            orig = _join(ns, by_n, "tekst")
            if len(orig.split()) < 4:                 # „Option 1.” to nagłówek, nie fakt
                continue
            seen.update(ns)
            facts.append({"t": by_n[ns[0]]["t"], "tekst": _join(ns, by_n, "pl") or orig, "oryginal": orig,
                          "czasy": [by_n[x]["t"] for x in ns], "rodzaj": _kind(orig), "zrodlo": "mowa"})
        q = _ids(d.get("cytat"), valid)
        if q:
            ns = sentence_at(q[0], by_n)
            orig = _join(ns, by_n, "tekst")
            if not set(ns) & ad_lines and len(orig.split()) >= 5:
                quotes.append({"t": by_n[ns[0]]["t"], "tekst": orig, "tlumaczenie": _join(ns, by_n, "pl"),
                               "czasy": [by_n[x]["t"] for x in ns]})

    parts_txt = "\n".join(f"[{ts(c['start'])}–{ts(c['end'])}] {c['tytul']}: {c['opis']}"
                          for c in chapters if not c["reklama"])
    facts_txt = "\n".join(f"- [{ts(f['t'])}] {f['oryginal']}" for f in facts) or "—"
    pr = REDUCE_PROMPT.format(typ=typ, meta=meta_line, parts=parts_txt, facts=facts_txt, words=words)
    raw = try_fn(engine, pr, log, max_tokens=1600)
    record("opis_calosci", pr, raw)
    p = loads(raw)

    # „najważniejsze” — tylko z czasem w filmie i poza reklamą; czas przyciągamy do początku części albo faktu
    anchors = sorted({c["start"] for c in chapters if not c["reklama"]} | {f["t"] for f in facts})
    hl = []
    for x in p.get("najwazniejsze") or []:
        if not isinstance(x, dict) or not str(x.get("tytul") or "").strip():
            continue
        try:
            t = float(x.get("t"))
        except (TypeError, ValueError):
            continue
        if any(a["start"] - 1 <= t <= a["end"] + 1 for a in ads):
            continue                                  # model streścił reklamę — nie jest „najważniejsza”
        if anchors:
            t = min(anchors, key=lambda a: abs(a - t))
        hl.append({**x, "t": t, "zrodlo": "mowa"})
    p["najwazniejsze"] = hl
    p["rozdzialy"] = [{k: v for k, v in c.items() if k != "reklama"} for c in chapters]
    p["fakty"] = facts
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
