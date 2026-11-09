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
        "do_zapamietania": _str(d.get("do_zapamietania")),
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
    L = ["## W skrócie", f"**Typ:** {s['typ']}." + (f" {s['teza']}" if s.get("teza") else ""), ""]
    if s.get("czas_czytania_s"):
        c = int(s["czas_czytania_s"])
        L += [f"_Czas czytania streszczenia: ≈ {c // 60} min {c % 60:02d} s_" if c >= 60 else f"_Czas czytania: ≈ {c} s_", ""]
    L += [p + "\n" for p in s["streszczenie"]]
    if s.get("do_zapamietania"):
        L += [f"> **Do zapamiętania:** {s['do_zapamietania']}", ""]
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
{glossary}

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
{glossary}

FAKTY Z FILMU:
{facts}

ZAPIS (czas w sekundach):
{timeline}

Odpowiedz WYŁĄCZNIE JSON-em:
"""
# opis całości w DWÓCH częściach — przy równoległej Ollamie liczą się naraz (każda część to połowa tekstu do napisania)
# bez „tytul_akcent”: pomiar (0.7.9 na karcie) — model wypisywał tam dziesiątki wariantów tytułu aż do limitu
# 3000 tokenów, dwa razy z rzędu (~60 s straty)
PRESENT_A = """{{"tytul": "krótki tytuł (3–6 słów)",
 "teza": "jedno zdanie: o co chodzi i co z tego wynika",
 "streszczenie": ["akapit 1 (3–4 zdania): temat i cel filmu, dla kogo jest", "akapit 2 (4–6 zdań): najważniejsze tezy albo etapy po kolei — konkretnie, z liczbami i przykładami z filmu", "akapit 3 (3–4 zdania): praktyczne wskazówki i uzasadnienia autora (dlaczego tak)", "akapit 4 (2–3 zdania): najważniejszy wniosek dla widza"],
 "do_zapamietania": "jedno zdanie: co widz ma zapamiętać",
 "najwazniejsze": [{{"t": sekundy, "tytul": "...", "opis": "1–2 zdania", "zrodlo": "mowa|obraz|mowa+obraz"}}],
 "szczera_ocena": "2–3 zdania: co wartościowe, czego brakuje",
 "czego_nie_wiadomo": ["czego film nie mówi, a widz chciałby wiedzieć"]}}
Streszczenie: razem około {words} słów (to ok. 1–1,5 minuty czytania) — pełne zdania, bez ogólników. Każde zdanie musi
wynikać z FAKTÓW albo ZAPISU; nie dodawaj wiedzy spoza filmu i liczb, których w nim nie ma. Etapy opisuj w kolejności
kroków i NIE łącz w jednym zdaniu rzeczy z różnych kroków (np. składnika z gotowania z czynnością ze smażenia). Nie pisz
o proporcjach ani ilościach, jeśli w filmie nie padły.
Liczby: 3–5 „najwazniejsze”.
"""
PRESENT_B = """{{"momenty": [{{"t": sekundy, "tekst": "co się dzieje"}}],
 "cytaty": [{{"t": sekundy, "tekst": "dosłownie z MOWA, w oryginale", "tlumaczenie": "po polsku, jeśli oryginał nie jest po polsku"}}],
 "rozdzialy": [{{"start": sekundy, "end": sekundy, "tytul": "...", "opis": "1–2 zdania"}}],
 "wnioski": ["dla wykładu/rozmowy: najważniejsze wnioski"],
 "pytania": ["3–5 pytań, które widz mógłby zadać"]}}
Liczby: 4–8 „momenty”, 2–4 „cytaty” (pusta lista, jeśli nikt nie mówi), 3–6 „rozdzialy” obejmujących cały film po kolei
(nowy rozdział tam, gdzie zaczyna się nowy temat albo etap).
"""
SHORT_A = """{{"tytul": "krótki tytuł (3–6 słów)", "teza": "jedno zdanie: o co chodzi",
 "streszczenie": ["akapit 1: temat i cel", "akapit 2: etapy po kolei, z liczbami", "akapit 3: wskazówki autora"],
 "do_zapamietania": "jedno zdanie"}}
Streszczenie: razem około {words} słów, tylko z FAKTÓW, etapy w kolejności kroków; nie łącz rzeczy z różnych kroków
i nie pisz o proporcjach, których nie podano.
"""
# przy krokach z linii mowy: model pisze cytaty, pytania i początki rozdziałów; program przyciąga je do kroków
PRESENT_B_SHORT = """{{"cytaty": [{{"t": sekundy, "tekst": "dosłownie z MOWA, w oryginale", "tlumaczenie": "po polsku, jeśli oryginał nie jest po polsku"}}],
 "rozdzialy": [{{"start": sekundy, "tytul": "2–4 słowa"}}],
 "pytania": ["3–5 pytań, które widz mógłby zadać"]}}
Liczby: 2–4 „cytaty” — najciekawsze zdania autora (porady, uzasadnienia), nie same polecenia. 3–6 „rozdzialy” po kolei
przez cały film; „start” to czas kroku, od którego zaczyna się nowy etap (np. krojenie, moczenie, gotowanie, smażenie).
"""
PRESENT_FULL = PRESENT_A.split("}}\nStreszczenie")[0] + ",\n" + PRESENT_B[2:].split("\nLiczby")[0] + """
Streszczenie: razem około {words} słów (ok. 1–1,5 minuty czytania). Każde zdanie musi wynikać z FAKTÓW albo ZAPISU.
Liczby: 3–5 „najwazniejsze”, 4–8 „momenty”, 2–4 „cytaty” (pusta lista, jeśli nikt nie mówi), 3–6 „rozdzialy” obejmujących cały film po kolei.
"""
PRESENT_PROMPT = PRESENT_HEAD + PRESENT_FULL

FILL_PROMPT = """Czytasz fragmenty filmu (czas w sekundach), które POMINIĘTO przy wypisywaniu kroków. Źródła:
MOWA = co mówi autor, NAPISY = tekst z ekranu (dokładne liczby i nazwy), OBRAZ = opis kadru (mało pewny).
{meta}
Kroki już wypisane:
{done}

Dopisz po polsku TYLKO to, czego na tej liście brakuje: czynności z tych fragmentów oraz KAŻDĄ liczbę z jednostką
(temperatury, czasy, ilości, rozmiary, serie, powtórzenia), która jeszcze nie występuje w krokach — jako osobny krok
z czasem tej linii. Nie powtarzaj kroków z listy. Treść bierz tylko z tych fragmentów; nie dodawaj przymiotników ani narzędzi.
Odpowiedz WYŁĄCZNIE JSON-em:
{{"kroki": [{{"t": sekundy, "tekst": "jedna czynność, tryb rozkazujący, z liczbami", "zrodlo": "mowa|obraz|mowa+obraz"}}]}}
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


def _try(engine, prompt: str, log, max_tokens: int | None = None, seed: int | None = None) -> str:
    """Jedno wywołanie z jedną ponowną próbą. Pomiar: Ollama potrafi przerwać odpowiedź
    („token repeat limit reached”) — wtedy druga próba zwykle przechodzi; jeśli nie, ten etap jest pusty."""
    from .llm import LLMError
    for attempt in (1, 2):
        try:
            kw = {k: v for k, v in (("max_tokens", max_tokens),) if v}
            if seed is not None:
                kw.update(seed=seed, temperature=0.3)
            if attempt == 1:
                try:
                    return engine.complete(prompt, as_json=True, **kw)
                except TypeError:                      # silnik bez tych parametrów (Claude, atrapy w testach)
                    return engine.complete(prompt, as_json=True)
            # ponowna próba z innym ziarnem: przy temperaturze 0 i tym samym ziarnie model zapętla się tak samo
            # (pomiar: dwa razy „token repeat limit reached” na tym samym etapie)
            try:
                return engine.complete(prompt, as_json=True, seed=11, temperature=0.3)
            except TypeError:
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


def _stems(t: str) -> set:
    # polska odmiana: „mąką” i „mąkę” → „mąk”; krótkie słowa (i, w, do) pomijamy
    return {w[:4] if len(w) > 5 else w[:3] for w in _norm_words(t) if len(w) > 2}


def _same_step(a: str, b: str) -> bool:
    wa, wb = _stems(a), _stems(b)
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.6


def tidy(summary: dict, duration: float, max_quotes: int = 4, max_chapters: int = 6) -> dict:
    """Porządki po modelu (pomiar na komputerze testowym, 0.7.6): 11 cytatów i 9 rozdziałów z dziurami zamiast 2–4 i 3–6,
    ten sam krok dwa razy, „wnioski” = kopia „wskazówek”."""
    c = summary.get("co_masz_zrobic") or {}
    kroki, seen = [], []
    for k in c.get("kroki", []):
        t, txt = _t(k.get("t")), _str(k.get("tekst"))
        if any(abs((t or 0) - (t2 or 0)) <= 2 and _same_step(txt, x2) for t2, x2 in seen):
            continue
        seen.append((t, txt))
        kroki.append(k)
    if c:
        c["kroki"] = kroki
        tips = c.get("wskazowki", [])
        c["wnioski"] = [w for w in c.get("wnioski", []) if not any(_same_step(w, x) for x in tips)]
    q = summary.get("cytaty", [])
    if len(q) > max_quotes:                       # równo rozłożone po filmie
        step = len(q) / max_quotes
        summary["cytaty"] = [q[int(i * step)] for i in range(max_quotes)]
    ch = sorted(summary.get("rozdzialy", []), key=lambda x: x["start"])
    while len(ch) > max_chapters:                 # scal najkrótszy rozdział z następnym (albo poprzednim)
        lens = [(ch[i + 1]["start"] if i + 1 < len(ch) else duration) - ch[i]["start"] for i in range(len(ch))]
        i = min(range(len(ch)), key=lambda j: lens[j])
        j = i + 1 if i + 1 < len(ch) else i - 1
        a, b = sorted((i, j))
        ch[a] = {**ch[a], "end": ch[b]["end"]}
        del ch[b]
    for i, x in enumerate(ch):                    # bez dziur: rozdział trwa do początku następnego
        x["end"] = ch[i + 1]["start"] if i + 1 < len(ch) else round(duration, 2)
    summary["rozdzialy"] = ch
    return summary


# ---------------- kroki ZAKOTWICZONE w liniach mowy (0.7.8) ----------------
# Pomiar na komputerze testowym (0.7.7, frytki): model wypisujący kroki z całego zapisu naraz zmyślał („wyciśnij nadmiar skrobi”,
# „papierowy ręcznik”, „świeżo zmielona sól”) i przenosił liczby do złych kroków (190 °C przy pierwszym smażeniu).
# Teraz każdy krok musi wskazać numery linii mowy, z których powstał; program sprawdza liczby i pokrycie linii,
# a to, co się nie zgadza, model poprawia krótkim zapytaniem o konkretne linie.

GLOSSARY = ("Uwaga na tłumaczenie: baking soda = soda oczyszczona (NIE proszek do pieczenia), baking powder = proszek "
            "do pieczenia, duck fat = tłuszcz z kaczki, par-fry/blanch (w OLEJU, nie w wodzie) = podsmaż wstępnie / blanszuj, "
            "drain = odsącz / odcedź, dust = oprósz, tray = taca, pot = garnek, sprinkle = posyp.")

TYPE_PROMPT = """Fragment transkrypcji filmu. {meta}
Jaki to typ filmu? Do wyboru: przepis — gotowanie; trening — ćwiczenia; poradnik — instrukcja krok po kroku;
wyklad — wykład, rozmowa, wyjaśnianie, recenzja, wiadomości; inne.
Odpowiedz WYŁĄCZNIE JSON-em z jednym słowem: {{"typ": "przepis|trening|poradnik|wyklad|inne"}}

TRANSKRYPCJA:
{text}
"""

# Format jak przy tłumaczeniu (linia → linia), bo ten mały model robi niezawodnie. Pomiar (gemma3:4b, frytki, 0.7.8):
# format z numerami linii przy krokach („z”: [3, 4]) — model kończył po 8 krokach, pisał po angielsku, zmyślał „piekarnik”.
LINES_PROMPT = """You turn numbered lines of an automatic video transcript ({typ_en}) into POLISH instructions.
For EVERY numbered line, keep the SAME number and write in Polish:
- if the line says what to do: one short instruction in Polish imperative mood (e.g. "Obierz ziemniaki."), using only
  what this line says (you may use the previous line to know what "them" means);
- if the line only explains or describes (why, what effect): start with "Wyjaśnienie: " and write it in Polish;
- if the line adds nothing or only finishes the sentence from the previous line: an empty string "".
Keep every number exactly, with its unit (the unit may come from SCREEN = text shown on screen at that moment).
Do not add tools, amounts, adjectives or tips that are not in the line. Write only in Polish (Latin alphabet).
Polish terms: baking soda = soda oczyszczona (NOT proszek do pieczenia), baking powder = proszek do pieczenia,
duck fat = tłuszcz z kaczki, par-fry = podsmaż wstępnie w oleju, blanch (in oil) = blanszuj w oleju, dust/sprinkle = oprósz/posyp, tray = taca.
{meta}
{context}Answer ONLY with JSON: {{"1": "...", "2": "..."}}

LINES:
{lines}
"""

STAGES_PROMPT = """Kroki z filmu ({typ}), po kolei, ponumerowane:
{steps}
Dla KAŻDEGO kroku, w tej samej numeracji, podaj nazwę etapu, do którego należy (2–3 słowa po polsku, np.
„Przygotowanie ziemniaków”, „Gotowanie”, „Pierwsze smażenie”, „Drugie smażenie”, „Podanie”). Kolejne kroki tego samego
etapu mają IDENTYCZNĄ nazwę. Razem {lo}–{hi} różnych nazw na cały film.
Odpowiedz WYŁĄCZNIE JSON-em: {{"1": "...", "2": "..."}}
"""

INGR_PROMPT = """Lines of a video transcript (a recipe):
{lines}
List the ingredients mentioned in these lines, with names in POLISH. Amount only if a number is said in the line
(e.g. "2 łyżki"), otherwise "brak danych". Also list kitchen equipment mentioned in the speech, in Polish.
Do not add anything that is not in the lines. Polish terms: baking soda = soda oczyszczona, potato starch = skrobia
ziemniaczana, duck fat = tłuszcz z kaczki, pot = garnek, tray = taca.
Answer ONLY with JSON: {{"skladniki": [{{"nazwa": "...", "ilosc": "..."}}], "sprzet": ["..."]}}
"""

_NUM_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
              "nine": "9", "ten": "10", "twelve": "12", "fifteen": "15", "twenty": "20", "thirty": "30",
              "forty": "40", "fifty": "50", "hundred": "100", "half": "0.5", "jeden": "1", "jedna": "1", "jedno": "1",
              "dwa": "2", "dwie": "2", "trzy": "3", "cztery": "4", "pięć": "5", "sześć": "6", "siedem": "7",
              "osiem": "8", "dziewięć": "9", "dziesięć": "10", "pół": "0.5",
              # odmiana (pomiar 0.8.1: „Około jednego centymetra” nie liczyło się jako 1 → krok z 1 cm odpadał)
              "jednego": "1", "jednej": "1", "jednym": "1", "jedną": "1", "dwóch": "2", "dwoma": "2", "dwom": "2",
              "trzech": "3", "trzema": "3", "czterech": "4", "czterema": "4", "pięciu": "5", "sześciu": "6",
              "siedmiu": "7", "ośmiu": "8", "dziewięciu": "9", "dziesięciu": "10", "połowa": "0.5", "połowę": "0.5"}


_TERM_FIXES = [  # (warunek w oryginale, zły termin → dobry) — fałszywi przyjaciele, których mały model nie unika
    (r"baking soda|bicarbonate", r"baking powder", [(r"\b(dodaj\w*|dodać|wsyp\w*|użyj|użyć|daj)( trochę| odrobinę)? proszek do pieczenia",
                                                       r"\1\2 sodę oczyszczoną"),
                                                      (r"proszek do pieczenia", "soda oczyszczona"),
                                                     (r"proszku do pieczenia", "sody oczyszczonej"),
                                                     (r"proszkiem do pieczenia", "sodą oczyszczoną")]),
    (r"duck fat", None, [(r"tłuszcz(\w*) z kaczego pióra", r"tłuszcz\1 z kaczki"), (r"\(duck fat\)", "(tłuszcz z kaczki)"),
                         (r"\bduck fat\b", "tłuszcz z kaczki")]),
    # par-fry = wstępne smażenie w oleju; model pisał „parzenie”/„parowanie” (pomiar 0.8.1) — to gotowanie na parze
    (r"par[- ]?fr", r"steam|na parze|parowar",
     [(rf"\bpar(?:zeni|owani){e}(?: wstępn\w*)?\b", w) for e, w in (("em", "wstępnym smażeniem"), ("e", "wstępne smażenie"),
                                                                    ("a", "wstępnego smażenia"), ("u", "wstępnemu smażeniu"))]
     + [(r"\bparzone\b", "wstępnie usmażone")]),
]


_HOMO = str.maketrans("аеорсухыіАЕОРСХ", "aeorcuxyiAEOPCX")   # cyrylica w polskim tekście (pomiar: „sodы”)


def fix_terms(text: str, source: str) -> str:
    """Poprawia znane błędy tłumaczenia, gdy oryginał jednoznacznie wskazuje termin (baking soda ≠ proszek do pieczenia),
    i pojedyncze litery cyrylicy wstawione przez model w polskie słowa."""
    if re.search(r"[a-ząćęłńóśźż][\u0400-\u04ff]|[\u0400-\u04ff][a-ząćęłńóśźż]", text, re.I):
        text = text.translate(_HOMO)
    src = source.lower()
    for need, unless, subs in _TERM_FIXES:
        if re.search(need, src) and not (unless and re.search(unless, src)):
            for a, b in subs:
                def rep(m, b=b):
                    out = m.expand(b)
                    return out[:1].upper() + out[1:] if m.group(0)[:1].isupper() else out
                text = re.sub(a, rep, text, flags=re.I)
    return text


def fix_terms_deep(obj, source: str):
    if isinstance(obj, str):
        return fix_terms(obj, source)
    if isinstance(obj, list):
        return [fix_terms_deep(x, source) for x in obj]
    if isinstance(obj, dict):
        return {k: fix_terms_deep(v, source) for k, v in obj.items()}
    return obj


def _nums(text: str) -> set:
    """Liczby w tekście (cyfry i liczebniki „one”, „jeden”) — do porównania kroku ze źródłem."""
    out = {n.replace(",", ".") for n in _NUM.findall(text)}
    out |= {_NUM_WORDS[w] for w in _norm_words(text) if w in _NUM_WORDS}
    return out


def speech_lines(segments: list[dict], ocr: list[dict] | None = None, pl: list | None = None) -> list[dict]:
    """Linie mowy do kroków: numer, czas, tekst, polskie tłumaczenie (jeśli jest) + napis z ekranu z tego samego momentu."""
    pl = pl if pl and len(pl) == len(segments) else [None] * len(segments)
    lines = [{"n": i + 1, "t": float(s["start"]), "end": float(s.get("end") or s["start"]),
              "tekst": _str(s.get("text")), "pl": _str(pl[i]), "ekran": []}
             for i, s in enumerate(segments) if _str(s.get("text"))]
    for i, ln in enumerate(lines, 1):
        ln["n"] = i
    for o in ocr or []:
        a, b = float(o.get("start", 0)), float(o.get("end", o.get("start", 0)))
        best, score = None, -1e9
        for ln in lines:
            ov = min(b, ln["end"] + 0.5) - max(a, ln["t"] - 0.5)          # nakładanie się w czasie
            if ov > score:
                best, score = ln, ov
        if best is not None and score > -1.0 and _str(o.get("text")):
            best["ekran"].append(_str(o["text"]))
    return lines


def _line_txt(ln: dict, mark: bool = False) -> str:
    s = f"[{ln['n']}] {ts(ln['t'])} | " + (f"PL: {ln['pl']} | ORYGINAŁ: {ln['tekst']}" if ln.get("pl") else ln["tekst"])
    if ln["ekran"]:
        s += " | EKRAN: " + " / ".join(ln["ekran"])
    return ("► " if mark else "") + s


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


def _src_nums(ids: list[int], by_n: dict) -> set:
    return set().union(*(_nums(by_n[i]["tekst"] + " " + " ".join(by_n[i]["ekran"])) for i in ids)) if ids else set()


def _speech_nums(ids: list[int], by_n: dict) -> set:
    """Liczby, które padły w MOWIE tych linii (te muszą trafić do kroku; z ekranu bywa też szum, np. numer odcinka)."""
    return set().union(*(_nums(by_n[i]["tekst"]) for i in ids)) if ids else set()


def check_step(text: str, ids: list[int], by_n: dict) -> tuple[set, set]:
    """(liczby w kroku, których nie ma w jego liniach; liczby z mowy tych linii, których nie ma w kroku)."""
    got = _nums(text)
    return got - _src_nums(ids, by_n), _speech_nums(ids, by_n) - got


_EN = {"the", "and", "to", "them", "with", "of", "until", "it", "is", "this", "into", "in", "your", "you", "a", "for",
       "then", "add", "heat", "fry", "cut", "boil", "we", "our", "going"}


def looks_foreign(text: str) -> bool:
    """Krok przepisany po angielsku zamiast po polsku (pomiar: gemma3:4b przepisywała oryginał)."""
    w = _norm_words(text)
    return len(w) >= 2 and sum(x in _EN for x in w) / len(w) >= 0.3 and not re.search(r"[ąćęłńóśźż]", text.lower())


def _groups(ns: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for n in sorted(ns):
        if out and n - out[-1][-1] <= 2 and len(out[-1]) < 4:      # luka jednej linii — to zwykle to samo zdanie
            out[-1].append(n)
        else:
            out.append([n])
    return out


_CONT = re.compile(r"^(to|which|until|or|so|for the|into|in order|once|and once|and when|they should|it should|"
                   r"roughly|about|around|approximately|"
                   r"aby|żeby|by|aż|dopóki|albo|lub|co)\b", re.I)
_EXPL = re.compile(r"^(this|which|that|it)( is|'s| will)? (going to|gonna|will|helps?|makes?|adds?|gives?)\b|"
                   r"^(we've got|we have got|we have|i've got|i have)\b|"
                   r"^(this particular|perfect for|is a very|to remove)\b|^(to|co) (pomoże|doda|sprawi)", re.I)


_FILLER = re.compile(r"^(this is it|this is the|here is|here's|hi\b|hello|welcome|hey\b|so,? today|today we|"
                     r"the secret to|the trick to)", re.I)
# typowe polecenia na początku zdania (angielski) — pusta odpowiedź przy takiej linii to zgubiony krok („Peel.”)
_EN_IMP = re.compile(r"^(peel|cut|trim|chop|slice|dice|add|heat|fry|boil|bake|cook|soak|wash|rinse|drain|dust|place|put|"
                     r"remove|lay|stir|mix|whisk|season|finish|serve|pour|bring|set|take|use|make|start|open|click|"
                     r"press|select|go|turn|let|leave|cover|preheat|grate|blend|combine|spread|sprinkle|freeze|chill)\b", re.I)


_ADVERBS = {"ponownie", "następnie", "potem", "teraz", "lekko", "dokładnie", "delikatnie", "szybko", "powoli", "najpierw",
            "dalej", "jeszcze", "zawsze", "stale", "ostrożnie", "dobrze", "mocno", "krótko", "na", "w", "do", "po"}


def _continues(orig: str) -> bool:
    """Linia tylko kończy zdanie poprzedniej („To completely cool.”, „Or blanch them.”, „Roughly one centimetre.”)."""
    return bool(_CONT.match(orig.strip()))


def _imperative(txt: str) -> bool:
    """Polskie polecenie: pierwsze słowo bez końcowej samogłoski („Obierz”, „Dodaj”, „Smaż”, „Posyp”), a nie opis
    („Posiada…”, „Idealne…”, „Mamy…”, „Powinny…”). Pomiar: model zamieniał każdą linię na „krok”."""
    w = _norm_words(re.sub(r"^(i|a|oraz|albo|lub)\s+", "", txt.strip(), flags=re.I))
    while len(w) > 1 and w[0] in _ADVERBS:          # „Ponownie zamroź”, „Lekko oprósz”
        w = w[1:]
    return bool(w) and not re.search(r"[aeiouyąęó]$", w[0])


def _explains(orig: str) -> bool:
    """Linia wyjaśnia (dlaczego, jaki efekt), a nie mówi, co zrobić („This is going to add a crispy layer.”)."""
    return bool(_EXPL.match(orig.strip()))


def _fix_name(name: str, spoken: str) -> str:
    """Drobne poprawki nazw składników od modelu: „sol” → „sól”, „malon” → „Maldon” (gdy tak w filmie)."""
    name = re.sub(r"\bsol\b", "sól", name)
    if re.search(r"maldon", spoken, re.I):
        name = re.sub(r"\bmal(?:d)?on\b", "Maldon", name, flags=re.I)
    return name.strip()


def _num_line(ln: dict) -> str:
    return f"{ln['n']}. {ln['tekst']}" + (f"   [SCREEN: {' / '.join(ln['ekran'])}]" if ln["ekran"] else "")


def grounded_steps(engine, lines: list[dict], typ: str, meta_line: str, log=lambda s: None,
                   record=lambda *a: None, par: int = 1, chunk_lines: int = 20) -> dict:
    """Kroki i wyjaśnienia linia po linii (każdy krok wie, z której linii mowy pochodzi), składniki, sprzęt, etapy.

    Program sprawdza: liczby kroku muszą paść w jego linii (albo na ekranie w tym momencie), liczby z mowy muszą trafić
    do kroku, krok musi być po polsku. Co się nie zgadza — jeszcze raz tylko te linie; jeśli nadal — polskie
    tłumaczenie tej linii (jeśli jest) albo brak kroku. Lepiej brak kroku niż zła liczba."""
    from concurrent.futures import ThreadPoolExecutor
    by_n = {ln["n"]: ln for ln in lines}
    typ_pl = typ
    chunks = [lines[i:i + chunk_lines] for i in range(0, len(lines), chunk_lines)]
    if len(chunks) > 1 and len(chunks[-1]) < 6:            # krótka końcówka — do poprzedniej części
        tail = chunks.pop()                                 # (nie `chunks[-2] += chunks.pop()` — to nadpisuje 1. część)
        chunks[-1] = chunks[-1] + tail

    def ask(ch: list[dict]) -> dict:
        prev = [by_n[i] for i in (ch[0]["n"] - 2, ch[0]["n"] - 1) if i in by_n]
        ctx = ("Previous lines (context only, do NOT answer them):\n" +
               "\n".join(f"- {ln['tekst']}" for ln in prev) + "\n") if prev else ""
        local = [{**ln, "n": i} for i, ln in enumerate(ch, 1)]      # numeracja od 1 w każdej części (jak w tłumaczeniu)
        typ_en = {"przepis": "a recipe", "poradnik": "a how-to tutorial"}.get(typ, "a video")
        pr = LINES_PROMPT.format(typ_en=typ_en, meta=meta_line, context=ctx,
                                 lines="\n".join(_num_line(ln) for ln in local))
        raw = _try(engine, pr, log)
        record("kroki", pr, raw)
        d = _loads(raw)
        if isinstance(d.get("linie"), dict):
            d = d["linie"]
        return {ln["n"]: _str(d.get(str(i))) if not isinstance(d.get(str(i)), dict) else _str(d[str(i)].get("tekst"))
                for i, ln in enumerate(ch, 1)}

    def run(groups: list[list[dict]]) -> dict:
        res: dict = {}
        with ThreadPoolExecutor(max_workers=max(1, min(par, len(groups)))) as pool:
            for r in pool.map(ask, groups):
                res.update(r)
        return res

    log(f"        kroki z linii mowy: {len(lines)} linii, {len(chunks)} części"
        + (f" ({min(par, len(chunks))} naraz)" if par > 1 and len(chunks) > 1 else ""))

    # składniki i sprzęt — osobne krótkie zapytanie (równolegle z liniami)
    def ask_ingr() -> dict:
        if typ != "przepis":
            return {}
        pr = INGR_PROMPT.format(lines="\n".join(f"- {ln['tekst']}" for ln in lines)[:6000])
        raw = _try(engine, pr, log)
        record("skladniki", pr, raw)
        return _loads(raw)

    with ThreadPoolExecutor(max_workers=2 if par > 1 else 1) as pool:
        f_ingr = pool.submit(ask_ingr)
        out = run(chunks)
        ingr_raw = f_ingr.result()

    def ok(n: int, txt: str) -> bool:
        if not txt:
            return True
        body = re.sub(r"^wyja\w*:\s*", "", txt, flags=re.I)
        extra, lost = check_step(body, [n], by_n)
        return not extra and not lost and not looks_foreign(body)

    bad = [n for n, txt in out.items() if not ok(n, txt)]
    # linia z liczbą w mowie, a pusta odpowiedź — liczba by zginęła (pomiar 0.7.7: 140 °C)
    bad += [n for n, txt in out.items() if not txt and _speech_nums([n], by_n) and n not in bad]
    bad += [n for n, txt in out.items() if not txt and _EN_IMP.match(by_n[n]["tekst"].strip()) and n not in bad]
    if bad:
        log(f"        kontrola kroków: {len(bad)} linii do poprawy (liczby albo język) — pytam o nie jeszcze raz")
        again = run([[by_n[n] for n in sorted(bad)]][:1] if len(bad) <= chunk_lines else
                    [[by_n[n] for n in sorted(bad)[i:i + chunk_lines]] for i in range(0, len(bad), chunk_lines)])
        for n in bad:
            txt = again.get(n, "")
            if txt and ok(n, txt) and (txt or not _speech_nums([n], by_n)):
                out[n] = txt
            else:                                  # nadal źle: polskie tłumaczenie linii (jeśli liczby się zgadzają)
                pl = by_n[n].get("pl", "")
                out[n] = pl if pl and ok(n, pl) else ""

    steps, notes = [], []
    for n in sorted(out):
        txt = out[n].strip()
        if not txt or _FILLER.match(by_n[n]["tekst"].strip()):
            continue
        ln = by_n[n]
        zr = "mowa+obraz" if ln["ekran"] else "mowa"
        m = re.match(r"^wyja\w*:\s*(.+)", txt, flags=re.I)
        if m:
            notes.append({"z": [n], "t": ln["t"], "tekst": m.group(1).strip(), "zrodlo": zr})
            continue
        txt = re.sub(r"^(I|A|Oraz|Albo|Lub)\s+(?=\w)", lambda m: "" if len(txt) > 12 else m.group(0), txt)
        txt = txt[:1].upper() + txt[1:] if not _continues(ln["tekst"]) else txt
        prev = steps[-1] if steps else None
        # między poprzednim krokiem a tą linią są tylko wyjaśnienia / puste linie — to nadal ciąg dalszy
        between = range(prev["z"][-1] + 1, n) if prev else range(0)
        adjacent = prev is not None and all(not out.get(i, "").strip() or i in {x["z"][0] for x in notes} for i in between)
        # dokończenie zdania z poprzedniej linii („To completely cool.” → „…, aby całkowicie ostudzić.”) albo
        # powtórzenie — do poprzedniego kroku (pomiar: model zamieniał każdą linię na osobny „krok”)
        if adjacent and n - prev["z"][-1] <= 3 and (txt[:1].islower() or _same_step(txt, prev["tekst"])
                                                     or _continues(ln["tekst"])):
            if not _same_step(txt, prev["tekst"]):
                prev["tekst"] = prev["tekst"].rstrip(".!") + ", " + txt[:1].lower() + txt[1:]
            prev["z"].append(n)
            prev["zrodlo"] = "mowa+obraz" if prev["zrodlo"] == "mowa+obraz" or ln["ekran"] else "mowa"
            continue
        if _explains(ln["tekst"]) or not _imperative(txt):
            if _FILLER.match(ln["tekst"].strip()):
                continue                           # „This is it.” — bez treści (pomiar: model wstawił tu „Obierz ziemniaki”)
            notes.append({"z": [n], "t": ln["t"], "tekst": txt, "zrodlo": zr})
            continue
        steps.append({"z": [n], "t": ln["t"], "tekst": txt, "zrodlo": zr, "etap": ""})

    # składniki: nazwa musi pojawić się w mowie (po polsku w tłumaczeniu albo w oryginale); ilość tylko z liczbą z mowy
    spoken = " ".join(ln["tekst"] + " " + ln.get("pl", "") + " " + " ".join(ln["ekran"]) for ln in lines)
    spoken_pl = spoken + " " + " ".join(s["tekst"] for s in steps + notes)
    all_nums = _nums(spoken)
    out_ingr, seen = [], []
    for x in _lst(ingr_raw.get("skladniki") or ingr_raw.get("składniki") or ingr_raw.get("ingredients")):
        name = _fix_name(_str(x.get("nazwa")) if isinstance(x, dict) else _str(x), spoken)
        # duplikat tylko przy tych samych słowach (pomiar: „skrobia ziemniaczana” wypadała jako duplikat „ziemniaków”)
        if not name or any(_stems(name) == _stems(o) for o in seen) or not (_stems(name) & _stems(spoken_pl)):
            continue
        q = _str(x.get("ilosc")) if isinstance(x, dict) else ""
        if not (_nums(q) and _nums(q) <= all_nums):
            q = "brak danych"
        seen.append(name)
        out_ingr.append({"nazwa": name, "ilosc": q, "zrodlo": "mowa"})
    out_equip = []
    for x in _lst(ingr_raw.get("sprzet") or ingr_raw.get("sprzęt") or ingr_raw.get("equipment")):
        name = _str(x.get("nazwa")) if isinstance(x, dict) else _str(x)
        if name and _stems(name) & _stems(spoken_pl) and not any(_same_step(name, o) for o in out_equip):
            out_equip.append(name)
    return {"kroki": steps, "wyjasnienia": merge_notes(notes), "skladniki": out_ingr, "sprzet": out_equip}


def merge_notes(notes: list[dict]) -> list[dict]:
    """Sąsiednie wyjaśnienia (urywki jednego zdania z kolejnych linii) sklejone w jedno zdanie.
    Pomiar 0.8.0: „Posiada bardzo wysoką zawartość skrobi.” / „Bardzo niską zawartość wody.” jako osobne „wskazówki”."""
    out: list[dict] = []
    for n in notes:
        if out and n["z"][0] - out[-1]["z"][-1] <= 2:
            prev = out[-1]
            part = re.sub(r"^(i|a|oraz)\s+", "", n["tekst"].strip(), flags=re.I).rstrip(".")
            prev["tekst"] = prev["tekst"].rstrip(".") + ", " + part[:1].lower() + part[1:] + "."
            prev["z"] = prev["z"] + n["z"]
        else:
            out.append(dict(n))
    return out


def chapters_from_steps(steps: list[dict], duration: float, max_chapters: int = 6, notes: list[dict] | None = None) -> list[dict]:
    """Rozdziały z etapów kroków — granica rozdziału tylko na zmianie etapu (pomiar: rozdział „Smażenie i schładzanie”
    obejmował gotowanie, a ostatni łączył mrożenie, drugie smażenie i solenie)."""
    ch: list[dict] = []
    if steps and not any(s.get("etap") for s in steps):
        # brak etapów: rozdział na każdy krok (tytuł = początek kroku), potem łączenie najkrótszych do max_chapters
        steps = [{**s, "etap": " ".join(s["tekst"].rstrip(".").split()[:4])} for s in steps]
    for s in steps:
        name = s.get("etap") or ""
        if ch and (name == ch[-1]["tytul"] or (name and _same_step(name, ch[-1]["tytul"]))):
            ch[-1]["kroki"].append(s["tekst"])
            continue
        ch.append({"start": s["t"], "tytul": name or "Kroki", "kroki": [s["tekst"]]})
    if ch and ch[0]["start"] > 3:                 # wstęp: to, co autor mówi przed pierwszym krokiem (wyjaśnienia)
        intro = [n["tekst"] for n in notes or [] if n.get("t", 1e9) < ch[0]["start"]][:2]
        ch.insert(0, {"start": 0.0, "tytul": "Wstęp", "kroki": intro})
    elif ch:
        ch[0]["start"] = 0.0
    while len(ch) > max_chapters:                 # scal najkrótszy z sąsiadem (zachowaj tytuł dłuższego)
        lens = [(ch[i + 1]["start"] if i + 1 < len(ch) else duration) - ch[i]["start"] for i in range(len(ch))]
        i = min(range(len(ch)), key=lambda j: lens[j])
        j = i + 1 if i + 1 < len(ch) else i - 1
        a, b = sorted((i, j))
        keep = ch[a] if lens[a] >= lens[b] else ch[b]
        ch[a] = {"start": ch[a]["start"], "tytul": keep["tytul"], "kroki": ch[a]["kroki"] + ch[b]["kroki"]}
        del ch[b]
    out = []
    for i, c in enumerate(ch):
        end = ch[i + 1]["start"] if i + 1 < len(ch) else round(duration, 2)
        opis = "; ".join(k.rstrip(".") for k in c["kroki"][:3]) + ("." if c["kroki"] else "")
        if len(c["kroki"]) > 3:
            opis = opis[:-1] + " i dalej."
        out.append({"start": round(c["start"], 2), "end": round(end, 2), "tytul": c["tytul"],
                    "opis": opis or "Zapowiedź tematu filmu.", "momenty": []})
    return out


_FOLD = str.maketrans("ąćęłńóśźż", "acelnoszz")
_KEY_STOP = {"przygotowanie", "przygotowywanie", "przygotuj", "frytki", "frytek", "ziemniaki", "ziemniaków", "ziemniaka",
             "etap", "etapu", "część", "krok", "kroki", "wstęp", "podsumowanie", "oraz", "dla", "przez", "jako"}


def _keys(text: str) -> set:
    """Rdzenie słów do dopasowania tytułu z krokiem (bez polskich znaków, 4 pierwsze litery, bez słów ogólnych)."""
    out = set()
    for w in _norm_words(text):
        if len(w) < 4 or w in _KEY_STOP:
            continue
        r = re.sub(r"(owanie|ywanie|iwanie|anie|enie|cie|nia|nie|ów|ami|ach)$", "", w.translate(_FOLD))
        if len(r) >= 3:
            out.add(r[:5])                  # „gotowanie” → „got” (trafia w „zagotuj”), „smażenie” → „smaz”
    return out


def _hits(keys: set, text: str) -> int:
    words = [w.translate(_FOLD) for w in _norm_words(text)]
    return sum(any(k in w for w in words) for k in keys)       # „goto” trafia w „zagotuj”, „smaz” w „podsmaż”


def chapters_snapped(model_ch: list, steps: list[dict], duration: float, notes: list[dict] | None = None) -> list[dict]:
    """Rozdziały z modelu (tytuł + przybliżony początek), przypięte do kroków PO TREŚCI: w oknie ±15 s od czasu modelu
    wybieramy pierwszy krok, który pasuje do tytułu („Gotowanie” → „Zagotuj wodę”); bez dopasowania — najbliższy krok.
    Pomiar (0.8.0): przypinanie po samym czasie dawało „Gotowanie ziemniaków” nad krojeniem."""
    if not steps:
        return []
    picks: dict = {}
    last = -1.0
    for c in sorted((c for c in model_ch or [] if isinstance(c, dict) and _str(c.get("tytul"))),
                    key=lambda c: _num(c.get("start"), 0)):
        t = _num(c.get("start"), -1)
        if t < 0:
            continue
        title = _str(c["tytul"])
        cand = [x for x in steps if x["t"] > last and abs(x["t"] - t) <= 15]
        if not cand:
            continue
        keys = _keys(title)
        best = max((_hits(keys, x["tekst"]) for x in cand), default=0)
        if keys and not best:
            continue                # tytuł nie pasuje do żadnego kroku w pobliżu — nie stawiamy granicy w ciemno
        pick = next(x for x in cand if _hits(keys, x["tekst"]) == best) if best else min(cand, key=lambda x: abs(x["t"] - t))
        picks[pick["t"]] = title
        last = pick["t"]
    if len(picks) < 2:
        return []
    for s_ in steps:                                # etap kroku = rozdział, w którym jest (do momentów)
        s_["etap"] = next((picks[t] for t in sorted(picks, reverse=True) if t <= s_["t"]), "")
    return chapters_from_steps(steps, duration, notes=notes)


def snap_highlights(items: list, steps: list[dict], duration: float) -> list:
    """„Najważniejsze” przypięte do kroku po liczbach i treści (pomiar 0.8.0: model wpisał 140 jako czas → 00:58)."""
    out = []
    for x in items or []:
        text = _str(x.get("tytul")) + " " + _str(x.get("opis"))
        nums = {n.replace(",", ".") for n in _NUM.findall(text)}
        cand = [s_ for s_ in steps if nums & _nums(s_["tekst"])]
        keys = _keys(text)
        if not cand:
            best = max((_hits(keys, s_["tekst"]) for s_ in steps), default=0)
            cand = [s_ for s_ in steps if best and _hits(keys, s_["tekst"]) == best]
        if cand:
            t0 = _num(x.get("t"), 0)
            x = {**x, "t": min(cand, key=lambda s_: (-_hits(keys, s_["tekst"]), abs(s_["t"] - t0)))["t"]}
        elif _num(x.get("t"), -1) > duration:
            continue
        out.append(x)
    return out


def moments_from_steps(steps: list[dict], limit: int = 8) -> list[dict]:
    """Momenty z kroków: początek każdego etapu i kroki z liczbami (pomiar: momenty z modelu przypisywały 190 °C do 00:33)."""
    pick, last = [], None
    for s in steps:
        if s.get("etap") != last or _nums(s["tekst"]):
            pick.append(s)
        last = s.get("etap")
    if len(pick) > limit:
        step = len(pick) / limit
        pick = [pick[int(i * step)] for i in range(limit)]
    return [{"t": s["t"], "tekst": s["tekst"]} for s in pick]


def drop_unsupported_numbers(summary: dict, source_text: str) -> int:
    """Zdania opisu z liczbą, której nie ma w filmie (mowa, napisy) — usuwamy. Zwraca liczbę usuniętych zdań."""
    have = _nums(source_text)
    removed = 0

    def digits(t: str) -> set:                 # tylko liczby zapisane cyframi — „dwa smażenia” to nie zmyślona liczba
        return {n.replace(",", ".") for n in _NUM.findall(t)}

    def clean(text: str) -> str:
        nonlocal removed
        parts = re.split(r"(?<=[.!?])\s+", text)
        keep = [p for p in parts if not (digits(p) - have)]
        removed += len(parts) - len(keep)
        return " ".join(keep)

    summary["streszczenie"] = [p for p in (clean(x) for x in summary.get("streszczenie", [])) if p]
    for x in summary.get("najwazniejsze", []):
        x["opis"] = clean(x.get("opis", ""))
    summary["najwazniejsze"] = [x for x in summary.get("najwazniejsze", []) if x.get("opis")]
    if summary.get("teza") and digits(summary["teza"]) - have:
        summary["teza"], removed = "", removed + 1
    return removed


def reading_seconds(summary: dict, wpm: int = 190) -> int:
    """Szacowany czas czytania streszczenia (akapity + teza), ~190 słów/min po polsku."""
    words = len(_norm_words(" ".join(summary.get("streszczenie", [])) + " " + _str(summary.get("teza"))))
    return round(words / wpm * 60)


def target_words(n_source_words: int) -> int:
    """Docelowa długość streszczenia: ok. 1:00–1:25 czytania (190–270 słów), krócej, gdy film ma mało treści."""
    return max(120, min(270, int(n_source_words * 0.9)))


def staged_summary(engine, timeline: str, meta: str, duration: float, log=lambda s: None,
                   chunk_chars: int = 6000, trace: list | None = None, parallel: int | None = None,
                   segments: list[dict] | None = None, ocr: list[dict] | None = None,
                   on_partial=None, polish=None) -> dict | None:
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

    lines = speech_lines(segments, ocr) if segments else []
    n_words = sum(len(_norm_words(ln["tekst"])) for ln in lines)
    typ = ""
    if len(lines) >= 4 and n_words >= 25:
        # typ z początku transkrypcji (krótkie zapytanie) — od niego zależy, czy kroki budujemy z linii mowy
        sample = " ".join(ln["tekst"] for ln in lines)[:2500]
        pr = TYPE_PROMPT.format(meta=meta_line, text=sample)
        raw = _try(engine, pr, log)
        record("typ", pr, raw)
        # model potrafi przepisać etykietę z opisem („przepis (gotowanie)”) — bierzemy rozpoznaną nazwę typu
        m = re.search(r"przepis|trening|poradnik|wyk[łl]ad|inne", _str(_loads(raw).get("typ")).lower())
        typ = m.group(0).replace("ł", "l") if m else ""
    grounded = typ in ("przepis", "poradnik")
    notes: list[dict] = []
    if grounded:
        # polskie linie (tłumaczenie liczy się równolegle) — `polish()` czeka na nie; None = mowa już po polsku / brak
        pl = polish() if callable(polish) else polish
        if pl:
            lines = speech_lines(segments, ocr, pl)
        g = grounded_steps(engine, lines, typ, meta_line, log, record, par)
        notes = g["wyjasnienia"]
        ext.update({"kroki": [{"t": s["t"], "tekst": s["tekst"], "zrodlo": s["zrodlo"]} for s in g["kroki"]],
                    "skladniki": g["skladniki"], "sprzet": g["sprzet"],
                    "wskazowki": [n["tekst"] for n in notes if len(_norm_words(n["tekst"])) >= 4]})   # „Ta odmiana ziemniaka.” — nie wskazówka
        steps_full = g["kroki"]
        log(f"        kroki: {len(steps_full)}, wyjaśnienia: {len(notes)}, składniki: {len(g['skladniki'])}")
        if on_partial:
            try:
                on_partial("kroki", {"typ": typ, "kroki": ext["kroki"], "skladniki": ext["skladniki"]})
            except Exception:
                pass
    else:
        # fragmenty po ~6000 znaków (krótki film = jeden). Pomiar (tests/bench/summary_bench.py, gemma3:4b, frytki):
        # dzielenie krótkiego zapisu na małe części, żeby liczyć je naraz, dawało 7 kroków zamiast 14–18 — model
        # bez kontekstu gubi czynności. Długie filmy mają kilka fragmentów i te liczą się równolegle.
        parts = _chunks(timeline, chunk_chars)
        if len(parts) > 1:
            log(f"        fakty: {len(parts)} fragmenty" + (f" ({min(par, len(parts))} naraz)" if par > 1 else ""))

        def extract(part: str) -> str:
            pr = EXTRACT_PROMPT.format(meta=meta_line, timeline=part, glossary=GLOSSARY)
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
        typ = typ or (max(set(types), key=types.count) if types else "inne")

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
                    if any(_same_step(txt, _str(o.get("tekst"))) for o in ext["kroki"] if isinstance(o, dict)):
                        continue                       # ten krok już jest — nie podmieniamy go (0.7.7: 190 °C w złym kroku)
                    ext["kroki"].append(k)
                    added += 1
                # składników i porad z tego etapu nie dodajemy (0.7.7: zmyślone „świeżo zmielona” sól Maldon)
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

    if grounded:
        # krótko i tekstem (nie JSON-em): pomiar — przy 27 krokach w JSON-ie + pełnym zapisie gemma3:4b zapętlała się
        # („token repeat limit reached”) i opis całości wychodził pusty
        facts_json = "\n".join(
            [f"Typ: {typ}", "Kroki:"] + [f"{i}. [{ts(k['t'])}] {k['tekst']}" for i, k in enumerate(ext["kroki"], 1)]
            + (["Wyjaśnienia autora:"] + [f"- [{ts(n['t'])}] {n['tekst']}" for n in notes] if notes else [])
            + (["Składniki: " + ", ".join(x["nazwa"] for x in ext["skladniki"])] if ext["skladniki"] else []))
        limit = 5000
    else:
        facts_json = json.dumps({"typ": typ, **ext}, ensure_ascii=False)
        limit = 9000
    # do opisu całości: zapis skrócony do rozsądnej długości (fakty są już kompletne)
    short = timeline if len(timeline) <= limit else "\n".join(_chunks(timeline, limit)[0].splitlines()) + "\n[…]"
    head = PRESENT_HEAD.format(meta=meta_line, facts=facts_json, timeline=short, glossary=GLOSSARY)

    src_words = sum(len(_norm_words(ln["tekst"])) for ln in lines) if lines else len(_norm_words(timeline)) // 2
    words = target_words(src_words)

    def present(tail: str, need: tuple, stage: str, cap: int = 1600) -> dict:
        # jedna próba z limitem długości; przy pustym wyniku NIE powtarzamy tego samego (przy temperaturze 0 model
        # zapętla się identycznie) — niżej jest krótsze polecenie z innym ziarnem
        pr = head + tail.format(words=words)
        raw = _try(engine, pr, log, max_tokens=cap)
        record(stage, pr, raw)
        return _loads(raw)

    tail_b = PRESENT_B_SHORT if grounded else PRESENT_B
    need_b = ("cytaty", "rozdzialy") if grounded else ("momenty", "rozdzialy", "cytaty")
    if par > 1:
        with ThreadPoolExecutor(max_workers=2) as pool:
            fa = pool.submit(present, PRESENT_A, ("teza", "streszczenie", "najwazniejsze"), "opis_a")
            fb = pool.submit(present, tail_b, need_b, "opis_b")
            p = {**fb.result(), **fa.result()}
    elif grounded:
        p = {**present(tail_b, need_b, "opis_b"), **present(PRESENT_A, ("teza", "streszczenie"), "opis_a")}
    else:
        p = present(PRESENT_FULL, ("teza", "streszczenie", "najwazniejsze"), "opis")
    if not p.get("streszczenie"):
        # zapas: krótsze polecenie bez zapisu (pomiar: przy pełnym poleceniu model potrafi się zapętlić dwa razy z rzędu)
        log("        opis całości: drugie podejście, krótszym poleceniem")
        pr = (PRESENT_HEAD.split("ZAPIS (czas")[0].format(meta=meta_line, facts=facts_json, glossary=GLOSSARY)
              + "Odpowiedz WYŁĄCZNIE JSON-em:\n" + SHORT_A.format(words=words))
        raw = _try(engine, pr, log, max_tokens=1200, seed=11)
        record("opis_zapas", pr, raw)
        p = {**_loads(raw), **{k: v for k, v in p.items() if v}}
    if grounded:
        p["rozdzialy"] = chapters_snapped(_lst(p.get("rozdzialy")), steps_full, duration, notes) or \
            chapters_from_steps([{**s_, "etap": ""} for s_ in steps_full], duration, notes=notes)
        p["momenty"] = moments_from_steps(steps_full)
        p["najwazniejsze"] = snap_highlights(_lst(p.get("najwazniejsze")), steps_full, duration)

    def texts(xs) -> list[str]:
        return [x if isinstance(x, str) else _str((x or {}).get("tekst") or (x or {}).get("nazwa")) for x in xs]

    merged = {**p, "typ": typ, "co_masz_zrobic": {
        "skladniki": ext["skladniki"], "kroki": ext["kroki"], "sprzet": ext["sprzet"], "czas": _str(p.get("czas")),
        "cwiczenia": ext["cwiczenia"], "wskazowki": texts(ext["wskazowki"]), "bledy": texts(ext["bledy"]),
        "wnioski": texts(_lst(p.get("wnioski"))) or texts(ext["fakty"])[:7]}}
    merged["co_masz_zrobic"]["sprzet"] = texts(ext["sprzet"])
    has_facts = any(ext[k] for k in ("kroki", "skladniki", "cwiczenia", "wskazowki", "fakty"))
    out = parse_summary(json.dumps(merged, ensure_ascii=False), duration, allow_partial=has_facts)
    if out is not None:
        out["metoda"] = "kroki z linii mowy" if grounded else "fakty z fragmentów"
        source = " ".join(ln["tekst"] + " " + " ".join(ln["ekran"]) for ln in lines) if lines else timeline
        out = fix_terms_deep(out, source + " " + timeline)
        n = drop_unsupported_numbers(out, source + " " + timeline)
        if n:
            log(f"        usunięto {n} zdanie(a) z liczbą, której nie ma w filmie")
        out["czas_czytania_s"] = reading_seconds(out)
    return out


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
