"""Streszczenie jako DANE (JSON, schemat vidsum.summary/1) + czat z filmem.

Dane zasilają widok wyniku (zakładki: Co masz zrobić, Najważniejsze, Momenty, Cytaty, Rozdziały)
i są eksportowalne (np. do dashboardu). Markdown do raportu powstaje z tych samych danych.
"""
from __future__ import annotations

import json
import re

from .analysis import beats_as_text, ts

SUMMARY_SCHEMA = "vidsum.summary/1"
TYPES = ("przepis", "trening", "poradnik", "wyklad", "inne")

SUMMARY_JSON_PROMPT = """Jesteś asystentem, który ogląda film za użytkownika i mówi mu konkretnie, co z niego wynika.
Dostajesz oś czasu filmu z niezależnych źródeł:
- OBRAZ — automatyczne opisy kadrów z małego lokalnego modelu (bywają nieprecyzyjne: myli narzędzia i nazwy),
- NAPISY — tekst odczytany z ekranu (OCR; zwykle dokładny w nazwach, liczbach i ilościach),
- MOWA — automatyczna transkrypcja w języku oryginału (mogą być literówki; może być w dowolnym języku — odpowiadasz i tak po polsku).

Odpowiedz WYŁĄCZNIE poprawnym JSON-em (bez komentarzy i bez ```), po polsku, według schematu:
{{
 "typ": "przepis" | "trening" | "poradnik" | "wyklad" | "inne",
 "tytul": "krótki tytuł po polsku (3–6 słów)",
 "tytul_akcent": "druga, krótka część tytułu (2–4 słowa) — puenta",
 "teza": "jedno zdanie: o co chodzi w filmie i co z niego wynika",
 "streszczenie": ["akapit 1", "akapit 2", "akapit 3 (opcjonalnie)"],
 "co_masz_zrobic": {{
   "skladniki": [{{"nazwa": "...", "ilosc": "... albo brak danych", "zrodlo": "mowa|obraz|mowa+obraz|szacunek"}}],
   "kroki": [{{"t": sekundy, "tekst": "...", "zrodlo": "..."}}],
   "sprzet": ["..."],
   "czas": "podany czas albo szacunek z dopiskiem (szacunek)",
   "cwiczenia": [{{"nazwa": "...", "serie": "...", "powtorzenia": "... albo czas", "t": sekundy, "technika": "...", "zrodlo": "..."}}],
   "wskazowki": ["..."],
   "bledy": ["błędy, których unikać"],
   "wnioski": ["dla wykładu/poradnika/innych: 3–7 najważniejszych wniosków lub działań"]
 }},
 "najwazniejsze": [{{"t": sekundy, "tytul": "krótki tytuł", "opis": "1–2 zdania", "zrodlo": "..."}}],
 "momenty": [{{"t": sekundy, "tekst": "co się dzieje — jedno zdanie"}}],
 "cytaty": [{{"t": sekundy, "tekst": "dosłownie z MOWA", "tlumaczenie": "po polsku, jeśli oryginał nie jest po polsku, inaczej pusty"}}],
 "rozdzialy": [{{"start": sekundy, "end": sekundy, "tytul": "...", "opis": "1–3 zdania", "momenty": [{{"t": sekundy, "tekst": "..."}}]}}],
 "szczera_ocena": "2–4 zdania (szacunek): czy warto, co wartościowe, czego brakuje, co wątpliwe",
 "czego_nie_wiadomo": ["..."],
 "pytania": ["5 pytań, które widz mógłby zadać o ten film"]
}}

Zasady (obowiązkowe):
1. Wypełnij tylko pola pasujące do typu (przepis → skladniki/kroki/sprzet/czas; trening → cwiczenia/wskazowki/bledy;
   poradnik → kroki; inne → wnioski). Pozostałe zostaw jako puste listy / pusty tekst.
2. Czasy "t", "start", "end" to liczby sekund z osi czasu. Kolejność chronologiczna.
3. Niczego nie zmyślaj. Brak informacji → „brak danych”. Wnioski spoza danych oznacz źródłem "szacunek".
4. Mowa jest pewniejsza niż opisy kadrów; NAPISY są pewniejsze w nazwach i liczbach niż MOWA.
5. 3–5 pozycji „najwazniejsze”, 4–8 „momenty”, 2–4 „cytaty” (pusta lista, jeśli nikt nie mówi), 2–6 „rozdzialy”.

Metadane: {meta}
Ograniczenia analizy: {gaps}

OŚ CZASU:
{timeline}
"""


def build_json_prompt(beats: list[dict], meta: dict, gaps: list[str]) -> str:
    meta_txt = "; ".join(f"{k}: {v}" for k, v in meta.items() if v not in (None, ""))
    return SUMMARY_JSON_PROMPT.format(meta=meta_txt or "—", gaps="; ".join(gaps) or "—",
                                      timeline=beats_as_text(beats))


def _num(x, default=0.0) -> float:
    try:
        if isinstance(x, str) and ":" in x:                      # „01:23” → 83
            parts = [float(p) for p in x.split(":")]
            v = 0.0
            for p in parts:
                v = v * 60 + p
            return v
        return float(x)
    except (TypeError, ValueError):
        return default


def _str(x) -> str:
    return "" if x is None else str(x).strip()


def _lst(x) -> list:
    return x if isinstance(x, list) else []


def parse_summary(text: str, duration: float, allow_partial: bool = False) -> dict | None:
    """Wyciąga i normalizuje JSON streszczenia z odpowiedzi modelu. None, gdy to nie JSON."""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
    if m:
        t = m.group(1)
    elif not t.startswith("{"):
        i, j = t.find("{"), t.rfind("}")
        if i < 0 or j <= i:
            return None
        t = t[i:j + 1]
    try:
        d = json.loads(t)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    clamp = lambda v: round(max(0.0, min(duration, _num(v))), 2)   # noqa: E731
    cmz = d.get("co_masz_zrobic") if isinstance(d.get("co_masz_zrobic"), dict) else {}
    out = {
        "schema": SUMMARY_SCHEMA,
        "typ": _str(d.get("typ")).lower() if _str(d.get("typ")).lower() in TYPES else "inne",
        "tytul": _str(d.get("tytul")),
        "tytul_akcent": _str(d.get("tytul_akcent")),
        "teza": _str(d.get("teza")),
        "streszczenie": [_str(p) for p in _lst(d.get("streszczenie")) if _str(p)] or
                        ([_str(d.get("streszczenie"))] if isinstance(d.get("streszczenie"), str) else []),
        "co_masz_zrobic": {
            "skladniki": [{"nazwa": _str(x.get("nazwa")), "ilosc": _str(x.get("ilosc")) or "brak danych",
                           "zrodlo": _str(x.get("zrodlo"))} for x in _lst(cmz.get("skladniki")) if isinstance(x, dict)],
            "kroki": [{"t": clamp(x.get("t")), "tekst": _str(x.get("tekst")), "zrodlo": _str(x.get("zrodlo"))}
                      for x in _lst(cmz.get("kroki")) if isinstance(x, dict) and _str(x.get("tekst"))],
            "sprzet": [_str(x) for x in _lst(cmz.get("sprzet")) if _str(x)],
            "czas": _str(cmz.get("czas")),
            "cwiczenia": [{"nazwa": _str(x.get("nazwa")), "serie": _str(x.get("serie")),
                           "powtorzenia": _str(x.get("powtorzenia")), "t": clamp(x.get("t")),
                           "technika": _str(x.get("technika")), "zrodlo": _str(x.get("zrodlo"))}
                          for x in _lst(cmz.get("cwiczenia")) if isinstance(x, dict) and _str(x.get("nazwa"))],
            "wskazowki": [_str(x) for x in _lst(cmz.get("wskazowki")) if _str(x)],
            "bledy": [_str(x) for x in _lst(cmz.get("bledy")) if _str(x)],
            "wnioski": [_str(x) for x in _lst(cmz.get("wnioski")) if _str(x)],
        },
        "najwazniejsze": [{"t": clamp(x.get("t")), "tytul": _str(x.get("tytul")), "opis": _str(x.get("opis")),
                           "zrodlo": _str(x.get("zrodlo"))}
                          for x in _lst(d.get("najwazniejsze")) if isinstance(x, dict) and _str(x.get("tytul"))],
        "momenty": [{"t": clamp(x.get("t")), "tekst": _str(x.get("tekst"))}
                    for x in _lst(d.get("momenty")) if isinstance(x, dict) and _str(x.get("tekst"))],
        "cytaty": [{"t": clamp(x.get("t")), "tekst": _str(x.get("tekst")), "tlumaczenie": _str(x.get("tlumaczenie"))}
                   for x in _lst(d.get("cytaty")) if isinstance(x, dict) and _str(x.get("tekst"))],
        "rozdzialy": [{"start": clamp(x.get("start")), "end": clamp(x.get("end") if x.get("end") is not None else duration),
                       "tytul": _str(x.get("tytul")), "opis": _str(x.get("opis")),
                       "momenty": [{"t": clamp(m.get("t")), "tekst": _str(m.get("tekst"))}
                                   for m in _lst(x.get("momenty")) if isinstance(m, dict) and _str(m.get("tekst"))]}
                      for x in _lst(d.get("rozdzialy")) if isinstance(x, dict) and _str(x.get("tytul"))],
        "szczera_ocena": _str(d.get("szczera_ocena")),
        "czego_nie_wiadomo": [_str(x) for x in _lst(d.get("czego_nie_wiadomo")) if _str(x)],
        "pytania": [_str(x) for x in _lst(d.get("pytania")) if _str(x)][:6],
    }
    for k in ("najwazniejsze", "momenty", "cytaty"):
        out[k].sort(key=lambda x: x["t"])
    out["co_masz_zrobic"]["kroki"].sort(key=lambda x: x["t"])
    out["rozdzialy"].sort(key=lambda x: x["start"])
    if not (out["streszczenie"] or out["najwazniejsze"] or out["teza"]) and not allow_partial:
        return None
    return out


def _src(z: str) -> str:
    return f" [{z}]" if z else ""


def to_markdown(s: dict) -> str:
    """Markdown do raportu — z tych samych danych co widok."""
    L = ["## W skrócie", f"**Typ:** {s['typ']}. {s['teza']}", ""]
    L += [p + "\n" for p in s["streszczenie"]]
    c = s["co_masz_zrobic"]
    if any(c[k] for k in ("skladniki", "kroki", "sprzet", "cwiczenia", "wskazowki", "bledy", "wnioski")) or c["czas"]:
        L.append("## Co masz zrobić")
        if c["skladniki"]:
            L += ["### Składniki"] + [f"- {x['nazwa']} — {x['ilosc']}{_src(x['zrodlo'])}" for x in c["skladniki"]] + [""]
        if c["kroki"]:
            L += ["### Kroki"] + [f"{i}. `{ts(x['t'])}` {x['tekst']}{_src(x['zrodlo'])}" for i, x in enumerate(c["kroki"], 1)] + [""]
        if c["cwiczenia"]:
            L += ["### Ćwiczenia"] + [
                f"- `{ts(x['t'])}` **{x['nazwa']}** — {x['serie'] or '?'} × {x['powtorzenia'] or '?'}"
                f"{(' — ' + x['technika']) if x['technika'] else ''}{_src(x['zrodlo'])}" for x in c["cwiczenia"]] + [""]
        for k, lab in (("sprzet", "Sprzęt"), ("wskazowki", "Wskazówki"), ("bledy", "Błędy, których unikać"),
                       ("wnioski", "Wnioski")):
            if c[k]:
                L += [f"### {lab}"] + [f"- {x}" for x in c[k]] + [""]
        if c["czas"]:
            L += ["### Czas", c["czas"], ""]
    if s["najwazniejsze"]:
        L += ["## Najważniejsze"] + [f"{i}. `{ts(x['t'])}` **{x['tytul']}** — {x['opis']}{_src(x['zrodlo'])}"
                                     for i, x in enumerate(s["najwazniejsze"], 1)] + [""]
    if s["rozdzialy"]:
        L += ["## Rozdziały"] + [f"- `{ts(x['start'])}–{ts(x['end'])}` **{x['tytul']}** — {x['opis']}" for x in s["rozdzialy"]] + [""]
    if s["momenty"]:
        L += ["## Momenty"] + [f"- `{ts(x['t'])}` {x['tekst']}" for x in s["momenty"]] + [""]
    L += ["## Cytaty"] + ([f"- `{ts(x['t'])}` „{x['tekst']}”" + (f" ({x['tlumaczenie']})" if x["tlumaczenie"] else "")
                           for x in s["cytaty"]] or ["brak danych"]) + [""]
    if s["szczera_ocena"]:
        L += ["## Szczera ocena", s["szczera_ocena"] + " [szacunek]", ""]
    if s["czego_nie_wiadomo"]:
        L += ["## Czego nie wiadomo"] + [f"- {x}" for x in s["czego_nie_wiadomo"]] + [""]
    return "\n".join(L).strip() + "\n"


# ---------------- czat z filmem ----------------
CHAT_PROMPT = """Odpowiadasz na pytanie o JEDEN konkretny film. Masz jego pełną oś czasu (mowa, napisy z ekranu,
opisy kadrów) i streszczenie. Odpowiadaj po polsku, krótko i konkretnie (2–6 zdań albo krótka lista).
Przy faktach z filmu podawaj czas `mm:ss`. Jeśli w filmie tego nie ma — powiedz to wprost („w filmie tego nie ma”)
i dopiero potem, wyraźnie oznaczone jako [szacunek], możesz dodać ogólną wiedzę.

STRESZCZENIE:
{summary}

OŚ CZASU:
{timeline}

DOTYCHCZASOWA ROZMOWA:
{history}

PYTANIE: {question}
"""


def build_chat_prompt(analysis: dict, question: str, history: list[dict]) -> str:
    st = analysis.get("streszczenie") or {}
    summary = st.get("markdown") or "—"
    hist = "\n".join(f"{'Użytkownik' if h['rola'] == 'user' else 'Asystent'}: {h['tekst']}" for h in history[-8:]) or "—"
    return CHAT_PROMPT.format(summary=summary, timeline=beats_as_text(analysis.get("os_czasu", [])),
                              history=hist, question=question.strip()[:2000])


# ---------------- streszczenie etapami (lokalne modele 4–8B) ----------------
# Pomiar (docs/modele.md): małe modele z JEDNYM wielkim promptem gubią większość faktów (4–5 z 14).
# Dlatego lokalnie: (1) wyciągnięcie faktów fragment po fragmencie, (2) opis całości na podstawie faktów.

def compact_timeline(beats: list[dict]) -> str:
    """Zwięzła oś czasu: MOWA i NAPISY w całości, z obrazu tylko scena + czynności (bez listy obiektów)."""
    lines = []
    for b in beats:
        w = b["widac"]
        parts = []
        heard = (b.get("slychac") or {}).get("tekst")
        if heard:
            parts.append(f"MOWA: {heard}")
        if b.get("napisy"):
            parts.append(f"NAPISY: {b['napisy']}")
        if w.get("zrodlo") == "obraz":
            seen = w.get("scena", "")
            if w.get("czynnosci"):
                seen += " (" + ", ".join(w["czynnosci"]) + ")"
            if seen:
                parts.append(f"OBRAZ: {seen}")
        if parts:
            lines.append(f"[{_sec(b['start'])}s] " + " | ".join(parts))
    return "\n".join(lines)


def _sec(t: float) -> str:
    return f"{float(t):.0f}"


EXTRACT_PROMPT = """Czytasz zapis fragmentu filmu (czas w sekundach w nawiasach). Źródła:
MOWA = co mówi autor (najważniejsze), NAPISY = tekst z ekranu (dokładne liczby i nazwy), OBRAZ = opis kadru (mało pewny).
{meta}
Wypisz po polsku WSZYSTKO, co widz ma zrobić albo zapamiętać. Przejdź linia po linii — każda linia z MOWA zwykle
zawiera czynność albo poradę. Zachowaj KAŻDĄ liczbę z jednostką (temperatury, czasy, ilości, rozmiary, serie, powtórzenia).
Nie dodawaj niczego, czego nie ma w zapisie. Ewidentne błędy rozpoznawania mowy popraw tylko, jeśli NAPISY albo kontekst
jasno wskazują poprawne słowo; w razie wątpliwości pomiń. Źródło: "mowa", "obraz" albo "mowa+obraz" (NAPISY to "obraz").

Odpowiedz WYŁĄCZNIE JSON-em:
{{"typ": "przepis|trening|poradnik|wyklad|inne",
 "kroki": [{{"t": sekundy, "tekst": "jedna czynność, tryb rozkazujący, z liczbami", "zrodlo": "..."}}],
 "skladniki": [{{"nazwa": "...", "ilosc": "ilość albo brak danych", "zrodlo": "..."}}],
 "cwiczenia": [{{"nazwa": "...", "serie": "...", "powtorzenia": "...", "t": sekundy, "technika": "...", "zrodlo": "..."}}],
 "sprzet": ["..."], "wskazowki": ["porada / wyjaśnienie dlaczego"], "bledy": ["czego unikać"],
 "fakty": ["inne ważne informacje z filmu (dla wykładów, rozmów, recenzji)"]}}
Puste listy dla tego, czego w filmie nie ma.

ZAPIS:
{timeline}
"""

PRESENT_PROMPT = """Jesteś asystentem, który obejrzał film za użytkownika. Masz zapis filmu i listę faktów już z niego
wyciągniętych. Napisz po polsku opis całości. Niczego nie zmyślaj; to, co nie wynika z zapisu, oznacz jako szacunek.
{meta}

FAKTY Z FILMU (JSON):
{facts}

ZAPIS (czas w sekundach):
{timeline}

Odpowiedz WYŁĄCZNIE JSON-em:
{{"tytul": "krótki tytuł (3–6 słów)", "tytul_akcent": "puenta (2–4 słowa)",
 "teza": "jedno zdanie: o co chodzi i co z tego wynika",
 "streszczenie": ["akapit 1 (konkretnie, z liczbami)", "akapit 2"],
 "najwazniejsze": [{{"t": sekundy, "tytul": "...", "opis": "1–2 zdania", "zrodlo": "mowa|obraz|mowa+obraz"}}],
 "momenty": [{{"t": sekundy, "tekst": "co się dzieje"}}],
 "cytaty": [{{"t": sekundy, "tekst": "dosłownie z MOWA, w oryginale", "tlumaczenie": "po polsku, jeśli oryginał nie jest po polsku"}}],
 "rozdzialy": [{{"start": sekundy, "end": sekundy, "tytul": "...", "opis": "1–2 zdania"}}],
 "wnioski": ["dla wykładu/rozmowy: najważniejsze wnioski"],
 "szczera_ocena": "2–3 zdania: co wartościowe, czego brakuje",
 "czego_nie_wiadomo": ["czego film nie mówi, a widz chciałby wiedzieć"],
 "pytania": ["3–5 pytań, które widz mógłby zadać"]}}
Liczby: 3–5 „najwazniejsze”, 4–8 „momenty”, 2–4 „cytaty” (pusta lista, jeśli nikt nie mówi), 2–5 „rozdzialy”.
"""


def _chunks(text: str, limit: int) -> list[str]:
    out, cur, n = [], [], 0
    for line in text.splitlines():
        if cur and n + len(line) > limit:
            out.append("\n".join(cur))
            cur, n = [], 0
        cur.append(line)
        n += len(line) + 1
    if cur:
        out.append("\n".join(cur))
    return out


def _loads(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        i, j = raw.find("{"), raw.rfind("}")
        try:
            d = json.loads(raw[i:j + 1]) if 0 <= i < j else {}
        except json.JSONDecodeError:
            d = {}
    return d if isinstance(d, dict) else {}


def _try(engine, prompt: str, log) -> str:
    """Jedno wywołanie z jedną ponowną próbą. Pomiar: Ollama potrafi przerwać odpowiedź
    („token repeat limit reached”) — wtedy druga próba zwykle przechodzi; jeśli nie, ten etap jest pusty."""
    from .llm import LLMError
    for attempt in (1, 2):
        try:
            return engine.complete(prompt, as_json=True)
        except LLMError as e:
            log(f"        ! model: {str(e)[:100]}" + (" — ponawiam" if attempt == 1 else " — pomijam ten etap"))
            last = e
            if "połączyć" in str(e) or "nie odpowiada" in str(e):
                raise                                  # Ollama nie działa — nie ma sensu ponawiać
    if "repeat" not in str(last).lower():
        raise last
    return ""


def staged_summary(engine, timeline: str, meta: str, duration: float, log=lambda s: None,
                   chunk_chars: int = 6000, trace: list | None = None) -> dict | None:
    """Streszczenie w dwóch etapach. `engine.complete(prompt, as_json=True)` — Ollama albo Claude."""
    meta_line = f"Metadane: {meta}" if meta else ""
    ext: dict = {"kroki": [], "skladniki": [], "cwiczenia": [], "sprzet": [], "wskazowki": [], "bledy": [], "fakty": []}
    types: list[str] = []
    parts = _chunks(timeline, chunk_chars)
    for i, part in enumerate(parts, 1):
        if len(parts) > 1:
            log(f"        fakty: fragment {i}/{len(parts)}")
        raw = _try(engine, EXTRACT_PROMPT.format(meta=meta_line, timeline=part), log)
        if trace is not None:
            trace.append(raw)
        d = _loads(raw)
        if _str(d.get("typ")).lower() in TYPES:
            types.append(_str(d.get("typ")).lower())
        for k in ext:
            for x in _lst(d.get(k)):
                if x and x not in ext[k]:
                    ext[k].append(x)
    typ = max(set(types), key=types.count) if types else "inne"
    facts_json = json.dumps({"typ": typ, **ext}, ensure_ascii=False)
    # do drugiego etapu: zapis skrócony do rozsądnej długości (fakty są już kompletne)
    short = timeline if len(timeline) <= 9000 else "\n".join(_chunks(timeline, 9000)[0].splitlines()) + "\n[…]"
    p: dict = {}
    for _ in (1, 2):                                   # jedna ponowna próba, gdy odpowiedź nie jest poprawnym JSON-em
        raw = _try(engine, PRESENT_PROMPT.format(meta=meta_line, facts=facts_json, timeline=short), log)
        if trace is not None:
            trace.append(raw)
        p = _loads(raw)
        if p.get("teza") or p.get("streszczenie") or p.get("najwazniejsze"):
            break
    def texts(xs) -> list[str]:
        return [x if isinstance(x, str) else _str((x or {}).get("tekst") or (x or {}).get("nazwa")) for x in xs]

    merged = {**p, "typ": typ, "co_masz_zrobic": {
        "skladniki": ext["skladniki"], "kroki": ext["kroki"], "sprzet": ext["sprzet"], "czas": _str(p.get("czas")),
        "cwiczenia": ext["cwiczenia"], "wskazowki": texts(ext["wskazowki"]), "bledy": texts(ext["bledy"]),
        "wnioski": texts(_lst(p.get("wnioski"))) or texts(ext["fakty"])[:7]}}
    merged["co_masz_zrobic"]["sprzet"] = texts(ext["sprzet"])
    has_facts = any(ext[k] for k in ("kroki", "skladniki", "cwiczenia", "wskazowki", "fakty"))
    return parse_summary(json.dumps(merged, ensure_ascii=False), duration, allow_partial=has_facts)
