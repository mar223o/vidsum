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
- MOWA — automatyczna transkrypcja (mogą być literówki; może być po angielsku).

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


def parse_summary(text: str, duration: float) -> dict | None:
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
    if not (out["streszczenie"] or out["najwazniejsze"] or out["teza"]):
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
