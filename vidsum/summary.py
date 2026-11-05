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


def _zr(x) -> str:
    """Źródło do jednego z dozwolonych: mowa | obraz | mowa+obraz | szacunek (NAPISY/OCR to obraz)."""
    z = _str(x).lower().replace(" ", "")
    if not z:
        return ""
    z = re.sub(r"napisy|ocr|ekran|tekst", "obraz", z)
    has_m, has_o = "mow" in z, "obraz" in z
    if has_m and has_o:
        return "mowa+obraz"
    if has_m:
        return "mowa"
    if has_o:
        return "obraz"
    return "szacunek" if "szac" in z else ""


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
                           "zrodlo": _zr(x.get("zrodlo"))} for x in _lst(cmz.get("skladniki")) if isinstance(x, dict)],
            "kroki": [{"t": clamp(x.get("t")), "tekst": _str(x.get("tekst")), "zrodlo": _zr(x.get("zrodlo"))}
                      for x in _lst(cmz.get("kroki")) if isinstance(x, dict) and _str(x.get("tekst"))],
            "sprzet": [_str(x) for x in _lst(cmz.get("sprzet")) if _str(x)],
            "czas": _str(cmz.get("czas")),
            "cwiczenia": [{"nazwa": _str(x.get("nazwa")), "serie": _str(x.get("serie")),
                           "powtorzenia": _str(x.get("powtorzenia")), "t": clamp(x.get("t")),
                           "technika": _str(x.get("technika")), "zrodlo": _zr(x.get("zrodlo"))}
                          for x in _lst(cmz.get("cwiczenia")) if isinstance(x, dict) and _str(x.get("nazwa"))],
            "wskazowki": [_str(x) for x in _lst(cmz.get("wskazowki")) if _str(x)],
            "bledy": [_str(x) for x in _lst(cmz.get("bledy")) if _str(x)],
            "wnioski": [_str(x) for x in _lst(cmz.get("wnioski")) if _str(x)],
        },
        "najwazniejsze": [{"t": clamp(x.get("t")), "tytul": _str(x.get("tytul")), "opis": _str(x.get("opis")),
                           "zrodlo": _zr(x.get("zrodlo"))}
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
    # tylko pola pasujące do typu (pomiar na komputerze testowym: gemma wpisała „ćwiczenia” do przepisu na frytki)
    c = out["co_masz_zrobic"]
    if out["typ"] == "przepis":
        c["cwiczenia"] = []
    elif out["typ"] == "trening":
        c["skladniki"] = []
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
Nie dodawaj niczego, czego nie ma w zapisie — nie szacuj ilości, nie dopisuj nazw ani odmian. Ewidentne błędy rozpoznawania mowy popraw tylko, jeśli NAPISY albo kontekst
jasno wskazują poprawne słowo; w razie wątpliwości pomiń. Źródło: "mowa", "obraz" albo "mowa+obraz" (NAPISY to "obraz").

Odpowiedz WYŁĄCZNIE JSON-em:
{{"typ": "przepis|trening|poradnik|wyklad|inne",
 "kroki": [{{"t": sekundy, "tekst": "jedna czynność, tryb rozkazujący, z liczbami", "zrodlo": "..."}}],
 "skladniki": [{{"nazwa": "...", "ilosc": "ilość TYLKO jeśli padła w filmie, inaczej brak danych", "zrodlo": "..."}}],
 "cwiczenia": [{{"nazwa": "...", "serie": "...", "powtorzenia": "...", "t": sekundy, "technika": "...", "zrodlo": "..."}}],
 "sprzet": ["..."], "wskazowki": ["porada / wyjaśnienie dlaczego"], "bledy": ["czego unikać"],
 "fakty": ["inne ważne informacje z filmu (dla wykładów, rozmów, recenzji)"]}}
Puste listy dla tego, czego w filmie nie ma.

ZAPIS:
{timeline}
"""

PRESENT_HEAD = """Jesteś asystentem, który obejrzał film za użytkownika. Masz zapis filmu i listę faktów już z niego
wyciągniętych. Napisz po polsku opis całości. Niczego nie zmyślaj; to, co nie wynika z zapisu, oznacz jako szacunek.
{meta}

FAKTY Z FILMU (JSON):
{facts}

ZAPIS (czas w sekundach):
{timeline}

Odpowiedz WYŁĄCZNIE JSON-em:
"""
# opis całości w DWÓCH częściach — przy równoległej Ollamie liczą się naraz (każda część to połowa tekstu do napisania)
PRESENT_A = """{{"tytul": "krótki tytuł (3–6 słów)", "tytul_akcent": "puenta (2–4 słowa)",
 "teza": "jedno zdanie: o co chodzi i co z tego wynika",
 "streszczenie": ["akapit 1 (konkretnie, z liczbami)", "akapit 2"],
 "najwazniejsze": [{{"t": sekundy, "tytul": "...", "opis": "1–2 zdania", "zrodlo": "mowa|obraz|mowa+obraz"}}],
 "szczera_ocena": "2–3 zdania: co wartościowe, czego brakuje",
 "czego_nie_wiadomo": ["czego film nie mówi, a widz chciałby wiedzieć"]}}
Liczby: 3–5 „najwazniejsze”.
"""
PRESENT_B = """{{"momenty": [{{"t": sekundy, "tekst": "co się dzieje"}}],
 "cytaty": [{{"t": sekundy, "tekst": "dosłownie z MOWA, w oryginale", "tlumaczenie": "po polsku, jeśli oryginał nie jest po polsku"}}],
 "rozdzialy": [{{"start": sekundy, "end": sekundy, "tytul": "...", "opis": "1–2 zdania"}}],
 "wnioski": ["dla wykładu/rozmowy: najważniejsze wnioski"],
 "pytania": ["3–5 pytań, które widz mógłby zadać"]}}
Liczby: 4–8 „momenty”, 2–4 „cytaty” (pusta lista, jeśli nikt nie mówi), 3–6 „rozdzialy” obejmujących cały film po kolei.
"""
PRESENT_FULL = PRESENT_A.split("}}\nLiczby")[0] + ",\n" + PRESENT_B[2:].split("\nLiczby")[0] + """
Liczby: 3–5 „najwazniejsze”, 4–8 „momenty”, 2–4 „cytaty” (pusta lista, jeśli nikt nie mówi), 3–6 „rozdzialy” obejmujących cały film po kolei.
"""
PRESENT_PROMPT = PRESENT_HEAD + PRESENT_FULL

FILL_PROMPT = """Czytasz fragmenty filmu (czas w sekundach), które POMINIĘTO przy wypisywaniu kroków. Źródła:
MOWA = co mówi autor, NAPISY = tekst z ekranu (dokładne liczby i nazwy), OBRAZ = opis kadru (mało pewny).
{meta}
Kroki już wypisane:
{done}

Dopisz po polsku TYLKO to, czego na tej liście brakuje: czynności z tych fragmentów oraz KAŻDĄ liczbę z jednostką
(temperatury, czasy, ilości, rozmiary, serie, powtórzenia), która jeszcze nie występuje w krokach. Jeśli czynność już jest
na liście, ale bez liczby — podaj ją ponownie razem z liczbą. Nie powtarzaj kroków, które są kompletne. Nie zmyślaj.
Odpowiedz WYŁĄCZNIE JSON-em:
{{"kroki": [{{"t": sekundy, "tekst": "jedna czynność, tryb rozkazujący, z liczbami", "zrodlo": "mowa|obraz|mowa+obraz"}}],
 "skladniki": [{{"nazwa": "...", "ilosc": "ilość TYLKO jeśli padła, inaczej brak danych", "zrodlo": "..."}}],
 "wskazowki": ["..."]}}
Puste listy, jeśli niczego nie brakuje.

FRAGMENTY:
{timeline}
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


NUM_PROMPT = """Fragment filmu ({t} s): „{zdanie}”
{meta}
Napisz po polsku JEDNĄ czynność w trybie rozkazującym, która wynika z tego fragmentu i zawiera liczbę {n} razem z jednostką
(np. stopnie, minuty, gramy, centymetry, powtórzenia). Nie dodawaj niczego spoza fragmentu.
Odpowiedz WYŁĄCZNIE JSON-em: {{"tekst": "..."}}
"""

_LINE_T = re.compile(r"^\[(\d+)s\]")
_NUM = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?")


def _line_content(line: str) -> str:
    """MOWA + NAPISY jednej linii zapisu (bez opisu kadru i bez znacznika czasu)."""
    parts = [p.strip() for p in line.split(" | ")]
    parts[0] = _LINE_T.sub("", parts[0]).strip()
    return " ".join(p.split(":", 1)[1] for p in parts if p.startswith(("MOWA:", "NAPISY:")))


def _t(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def missing_lines(timeline: str, ext: dict) -> list[str]:
    """Linie zapisu, z których nie powstał żaden krok, albo których liczby nie trafiły do kroków/składników.

    Pomiar na komputerze testowym: przy jednym przebiegu mały model raz wypisał 11 kroków, raz 2 (bez 140°C i 190°C).
    Sprawdzamy to mechanicznie, a brakujące fragmenty model czyta jeszcze raz."""
    lines = [l for l in timeline.splitlines() if _LINE_T.match(l)]
    starts = [float(_LINE_T.match(l).group(1)) for l in lines]
    step_t = [t for t in (_t(k.get("t")) for k in ext.get("kroki", []) if isinstance(k, dict)) if t is not None]
    have = " ".join(json.dumps(ext.get(k, []), ensure_ascii=False) for k in ("kroki", "skladniki", "cwiczenia", "wskazowki"))
    have_nums = set(_NUM.findall(have))
    out = []
    for i, line in enumerate(lines):
        content = _line_content(line)
        if len(re.findall(r"\w+", content)) < 3:
            continue
        a, b = starts[i], starts[i + 1] if i + 1 < len(starts) else starts[i] + 30
        covered = any(a - 1 <= t < b + 1 for t in step_t)
        lost_num = any(n not in have_nums for n in _NUM.findall(content))
        if not covered or lost_num:
            out.append(line)
    return out


def missing_numbers(timeline: str, ext: dict) -> list[tuple[float, str, str, str]]:
    """(czas, liczba, zdanie, źródło) dla liczb z MOWY/NAPISÓW, których nie ma w żadnym kroku ani składniku."""
    have = " ".join(json.dumps(ext.get(k, []), ensure_ascii=False) for k in ("kroki", "skladniki", "cwiczenia", "wskazowki"))
    have_nums = set(_NUM.findall(have))
    out, seen = [], set()
    for line in timeline.splitlines():
        m = _LINE_T.match(line)
        if not m:
            continue
        for part in line.split(" | "):
            part = _LINE_T.sub("", part).strip()
            if not part.startswith(("MOWA:", "NAPISY:")):
                continue
            src = "mowa" if part.startswith("MOWA:") else "obraz"
            for sent in re.split(r"(?<=[.!?])\s+|\s\|\s", part.split(":", 1)[1]):
                for n in _NUM.findall(sent):
                    if n not in have_nums and n not in seen:
                        seen.add(n)
                        out.append((float(m.group(1)), n, sent.strip(), src))
    return out


def _same_step(a: str, b: str) -> bool:
    wa, wb = set(_norm_words(a)), set(_norm_words(b))
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.6


def _split_even(text: str, n: int) -> list[str]:
    lines = text.splitlines()
    size = -(-len(text) // n)
    return _chunks(text, max(size, max((len(l) for l in lines), default=1)))


def staged_summary(engine, timeline: str, meta: str, duration: float, log=lambda s: None,
                   chunk_chars: int = 6000, trace: list | None = None, parallel: int | None = None) -> dict | None:
    """Streszczenie etapami. `engine.complete(prompt, as_json=True)` — Ollama albo Claude.

    1) fakty z fragmentów zapisu (fragmenty równolegle, gdy Ollama obsługuje kilka zapytań naraz),
    2) kontrola kompletności: fragmenty bez kroku albo z liczbą, której nie ma w krokach → dopisanie,
    3) opis całości (dwie części równolegle albo jedna)."""
    from concurrent.futures import ThreadPoolExecutor
    par = max(1, int(parallel if parallel is not None else getattr(engine, "parallel", 1)))
    meta_line = f"Metadane: {meta}" if meta else ""
    ext: dict = {"kroki": [], "skladniki": [], "cwiczenia": [], "sprzet": [], "wskazowki": [], "bledy": [], "fakty": []}
    types: list[str] = []

    def record(stage: str, prompt: str, raw: str) -> None:
        if trace is not None:
            trace.append({"etap": stage, "odpowiedz": raw, "prompt_znakow": len(prompt)})

    # równoległa Ollama: zapis dzielimy na tyle części, ile zapytań idzie naraz (min. ~1500 znaków na część)
    n_par = min(par, max(1, len(timeline) // 1500))
    parts = _split_even(timeline, n_par) if n_par > 1 and len(timeline) <= chunk_chars * n_par else _chunks(timeline, chunk_chars)
    if len(parts) > 1:
        log(f"        fakty: {len(parts)} fragmenty" + (f" ({min(par, len(parts))} naraz)" if par > 1 else ""))

    def extract(part: str) -> str:
        pr = EXTRACT_PROMPT.format(meta=meta_line, timeline=part)
        raw = _try(engine, pr, log)
        record("fakty", pr, raw)
        return raw

    with ThreadPoolExecutor(max_workers=min(par, len(parts))) as pool:
        raws = list(pool.map(extract, parts))
    for raw in raws:
        d = _loads(raw)
        if _str(d.get("typ")).lower() in TYPES:
            types.append(_str(d.get("typ")).lower())
        for k in ext:
            for x in _lst(d.get(k)):
                if x and x not in ext[k]:
                    ext[k].append(x)
    typ = max(set(types), key=types.count) if types else "inne"

    # 2) kontrola kompletności (instrukcje: przepis, poradnik, trening)
    if typ in ("przepis", "poradnik", "trening"):
        miss = missing_lines(timeline, ext)
        if miss:
            log(f"        kontrola kompletności: {len(miss)} fragment(y) bez kroku albo z pominiętą liczbą — dopisuję")
            done = "\n".join(f"- [{_str(k.get('t'))}s] {_str(k.get('tekst'))}" for k in ext["kroki"] if isinstance(k, dict)) or "—"
            pr = FILL_PROMPT.format(meta=meta_line, done=done, timeline="\n".join(miss))
            raw = _try(engine, pr, log)
            record("uzupelnienie", pr, raw)
            d = _loads(raw)
            added = 0
            for k in _lst(d.get("kroki")):
                if not isinstance(k, dict) or not _str(k.get("tekst")):
                    continue
                txt = _str(k.get("tekst"))
                same = [i for i, o in enumerate(ext["kroki"]) if isinstance(o, dict) and _same_step(txt, _str(o.get("tekst")))]
                new_nums = set(_NUM.findall(txt))
                if same:
                    old = ext["kroki"][same[0]]
                    if new_nums - set(_NUM.findall(_str(old.get("tekst")))):
                        ext["kroki"][same[0]] = {**old, "tekst": txt}     # ten sam krok, ale teraz z liczbą
                        added += 1
                    continue
                ext["kroki"].append(k)
                added += 1
            for key in ("skladniki", "wskazowki"):
                for x in _lst(d.get(key)):
                    name = _str(x.get("nazwa")) if isinstance(x, dict) else _str(x)
                    olds = [_str(o.get("nazwa")) if isinstance(o, dict) else _str(o) for o in ext[key]]
                    if name and not any(_same_step(name, o) for o in olds):
                        ext[key].append(x)
                        added += 1
            log(f"        kontrola kompletności: dopisano {added}")
        # liczby, których model nadal nie przeniósł (pomiar: raz zgubił 140 °C i 190 °C mimo uzupełnienia) —
        # osobne, bardzo krótkie zapytanie na każdą liczbę: małe modele robią to niezawodnie
        nums = missing_numbers(timeline, ext)[:6]
        if nums:
            log(f"        kontrola liczb: brakuje {', '.join(n for _, n, _, _ in nums)} — dopisuję")

            def one(item):
                t0, n, sent, src = item
                pr = NUM_PROMPT.format(t=int(t0), zdanie=sent, n=n, meta=meta_line)
                raw = _try(engine, pr, log)
                record("liczba", pr, raw)
                txt = _str(_loads(raw).get("tekst"))
                return {"t": t0, "tekst": txt, "zrodlo": src} if n in _NUM.findall(txt) else None

            with ThreadPoolExecutor(max_workers=min(par, len(nums))) as pool:
                for k in pool.map(one, nums):
                    if k:
                        ext["kroki"].append(k)
    ext["kroki"].sort(key=lambda k: _t(k.get("t")) if isinstance(k, dict) and _t(k.get("t")) is not None else 1e9)

    facts_json = json.dumps({"typ": typ, **ext}, ensure_ascii=False)
    # do opisu całości: zapis skrócony do rozsądnej długości (fakty są już kompletne)
    short = timeline if len(timeline) <= 9000 else "\n".join(_chunks(timeline, 9000)[0].splitlines()) + "\n[…]"
    head = PRESENT_HEAD.format(meta=meta_line, facts=facts_json, timeline=short)

    def present(tail: str, need: tuple, stage: str) -> dict:
        got: dict = {}
        for _ in (1, 2):                           # jedna ponowna próba, gdy odpowiedź nie jest poprawnym JSON-em
            pr = head + tail.format()
            raw = _try(engine, pr, log)
            record(stage, pr, raw)
            got = _loads(raw)
            if any(got.get(k) for k in need):
                break
        return got

    if par > 1:
        with ThreadPoolExecutor(max_workers=2) as pool:
            fa = pool.submit(present, PRESENT_A, ("teza", "streszczenie", "najwazniejsze"), "opis_a")
            fb = pool.submit(present, PRESENT_B, ("momenty", "rozdzialy", "cytaty"), "opis_b")
            p = {**fb.result(), **fa.result()}
    else:
        p = present(PRESENT_FULL, ("teza", "streszczenie", "najwazniejsze"), "opis")

    def texts(xs) -> list[str]:
        return [x if isinstance(x, str) else _str((x or {}).get("tekst") or (x or {}).get("nazwa")) for x in xs]

    merged = {**p, "typ": typ, "co_masz_zrobic": {
        "skladniki": ext["skladniki"], "kroki": ext["kroki"], "sprzet": ext["sprzet"], "czas": _str(p.get("czas")),
        "cwiczenia": ext["cwiczenia"], "wskazowki": texts(ext["wskazowki"]), "bledy": texts(ext["bledy"]),
        "wnioski": texts(_lst(p.get("wnioski"))) or texts(ext["fakty"])[:7]}}
    merged["co_masz_zrobic"]["sprzet"] = texts(ext["sprzet"])
    has_facts = any(ext[k] for k in ("kroki", "skladniki", "cwiczenia", "wskazowki", "fakty"))
    return parse_summary(json.dumps(merged, ensure_ascii=False), duration, allow_partial=has_facts)


def _norm_words(t: str) -> list[str]:
    return re.findall(r"\w+", t.lower())


def verify_quotes(summary: dict, segments: list[dict]) -> int:
    """Cytat musi naprawdę paść w filmie: ≥80% jego słów po kolei w transkrypcji (w oknie). Zmyślone usuwamy.

    Pomiar na komputerze testowym: mały model „zacytował” zdanie, którego w filmie nie było. Zwraca liczbę usuniętych."""
    words = _norm_words(" ".join(s.get("text") or "" for s in segments))
    text = " ".join(words)
    kept, removed = [], 0
    for q in summary.get("cytaty", []):
        qw = _norm_words(q.get("tekst", ""))
        if not qw:
            removed += 1
            continue
        if " ".join(qw) in text:
            kept.append(q)
            continue
        best = 0
        n = len(qw)
        for i in range(max(1, len(words) - n + 1)):
            win = set(words[i:i + n + 3])
            best = max(best, sum(1 for w in qw if w in win) / n)
        if best >= 0.8:
            kept.append(q)
        else:
            removed += 1
    summary["cytaty"] = kept
    return removed
