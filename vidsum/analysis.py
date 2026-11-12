"""Łączenie mowy i obrazu w oś czasu („beats”) oraz budowa promptu do streszczenia."""
from __future__ import annotations

from dataclasses import dataclass

from . import SRC_NONE, SRC_SPEECH, SRC_VISION
from .transcribe import Segment


def ts(t: float) -> str:
    t = max(0, int(round(t)))
    h, m, s = t // 3600, t % 3600 // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


@dataclass
class FrameInfo:
    t: float
    file: str
    reasons: list[str]
    score: float
    vision: dict | None


def audio_beats(segments: list[Segment], duration: float, step: float = 30.0) -> list[dict]:
    """Oś czasu pliku dźwiękowego (0.12.0): odcinki po ok. `step` sekund, bez kadru; granice na początkach zdań."""
    beats: list[dict] = []
    start = 0.0
    while start < duration - 0.5 or not beats:
        end = min(duration, start + step)
        nxt = next((s.start for s in segments if end - 5 <= s.start <= end + 10), None)   # nie tniemy zdania w pół
        if nxt is not None and nxt > start + 5:
            end = nxt
        if duration - end < step / 3:
            end = duration
        said = [s.text for s in segments if start <= s.start < end or (not beats and s.start < end)]
        beats.append({"start": round(start, 2), "end": round(max(end, start), 2), "kadr": None, "powod_kadru": [],
                      "napisy": "", "widac": {"zrodlo": SRC_NONE},
                      "slychac": {"tekst": " ".join(said).strip(), "zrodlo": SRC_SPEECH if said else SRC_NONE},
                      "zmiana": None})
        if end >= duration:
            break
        start = end
    return beats


def build_beats(frames: list[FrameInfo], segments: list[Segment], duration: float, ocr_lines=None) -> list[dict]:
    """Jeden beat = odcinek od kadru do następnego kadru.

    seen  — to, co rozpoznał model wizyjny na kadrze (źródło: obraz),
    heard — mowa, której segmenty nachodzą na odcinek (źródło: mowa),
    changed — co pojawiło się/zniknęło względem poprzedniego beatu (mechanicznie, bez modelu).
    """
    def boundary(f: FrameInfo) -> float:
        # kadr przy cięciu jest pobierany 0,5 s PO cięciu — odcinek zaczyna się w chwili cięcia
        return max(0.0, f.t - 0.5) if "zmiana_sceny" in f.reasons else f.t

    beats: list[dict] = []
    prev_items: set[str] = set()
    for i, f in enumerate(frames):
        start = 0.0 if i == 0 else boundary(f)
        end = boundary(frames[i + 1]) if i + 1 < len(frames) else duration
        said = [s.text for s in segments if s.end > start and s.start < end]
        # segment przypisany do beatu, w którym się zaczyna (unikamy dublowania w prompcie)
        said_own = [s.text for s in segments if start <= s.start < end or (i == 0 and s.start < end)]
        if f.vision:
            items = {x.lower() for x in f.vision.get("obiekty", []) + f.vision.get("czynnosci", [])}
            changed = {"nowe": sorted(items - prev_items), "zniknely": sorted(prev_items - items)} if i else None
            prev_items = items
            seen = dict(f.vision, zrodlo=SRC_VISION)
        else:
            changed = None
            seen = {"zrodlo": SRC_NONE}
        caps = [l.text for l in (ocr_lines or []) if start <= l.start < end]
        beats.append({
            "start": round(start, 2), "end": round(end, 2), "kadr": f.file, "powod_kadru": f.reasons,
            "napisy": " | ".join(caps),
            "widac": seen,
            "slychac": {"tekst": " ".join(said_own).strip(), "zrodlo": SRC_SPEECH if said else SRC_NONE},
            "zmiana": changed,
        })
    return beats


def beats_as_text(beats: list[dict]) -> str:
    lines = []
    for b in beats:
        w = b["widac"]
        if w.get("zrodlo") == SRC_VISION:
            parts = [w.get("scena", "")]
            for key, lab in (("czynnosci", "czynności"), ("obiekty", "obiekty"),
                             ("tekst_na_ekranie", "napisy w filmie"),
                             ("napisy_na_przedmiotach", "napisy na przedmiotach"), ("cialo", "ciało")):
                val = w.get(key)
                if val:
                    parts.append(f"{lab}: {', '.join(val) if isinstance(val, list) else val}")
            parts.append(f"pewność: {w.get('pewnosc')}")
            seen = "; ".join(p for p in parts if p)
        else:
            seen = "brak opisu obrazu"
        heard = b["slychac"]["tekst"] or "—"
        caps = f"\n    NAPISY: {b['napisy']}" if b.get("napisy") else ""
        lines.append(f"[{ts(b['start'])}–{ts(b['end'])}] OBRAZ: {seen}{caps}\n    MOWA: {heard}")
    return "\n".join(lines)


SUMMARY_PROMPT = """Jesteś asystentem, który ogląda film za użytkownika i mówi mu konkretnie, co z niego wynika.
Dostajesz oś czasu filmu z dwóch niezależnych źródeł:
- OBRAZ — automatyczne opisy kadrów z małego lokalnego modelu (bywają nieprecyzyjne: myli narzędzia i nazwy),
- MOWA — automatyczna transkrypcja albo napisy (mogą być literówki; może być w dowolnym języku — streszczenie i tak pisz po polsku),
- NAPISY — tekst odczytany z ekranu przez OCR (zwykle dokładny w nazwach, liczbach i ilościach; oznaczaj jako [obraz]).

Najpierw sam rozpoznaj TYP filmu: przepis | trening | poradnik | wykład/rozmowa | inne.
Potem napisz wynik po polsku, w Markdown, DOKŁADNIE w tym układzie (nagłówki bez zmian):

## W skrócie
**Typ:** <typ>. 2–3 zdania: o czym jest film i co z niego wynika dla widza.

## Co masz zrobić
Dopasuj do typu:
- przepis → `### Składniki` (lista; ilość, jeśli padła — inaczej „ilość: brak danych”), `### Kroki` (lista numerowana, każdy krok z `mm:ss`), `### Sprzęt`, `### Czas` (podany albo [szacunek]);
- trening → `### Ćwiczenia` (każde: nazwa — serie × powtórzenia albo czas — `mm:ss`), `### Technika` (wskazówki), `### Błędy, których unikać`;
- poradnik → lista numerowana kroków z `mm:ss`;
- wykład/rozmowa/inne → 3–7 najważniejszych wniosków albo działań do wykonania.

## Rozdziały
Lista: `mm:ss` **Tytuł** — jedno zdanie. 3–8 rozdziałów, w kolejności.

## Cytaty
2–4 dosłowne cytaty TYLKO z MOWA, z `mm:ss`; obcojęzyczne zostaw w oryginale i dodaj tłumaczenie w nawiasie.
Jeśli w filmie nikt nie mówi — napisz „brak danych”.

## Szczera ocena
2–4 zdania [szacunek]: czy warto obejrzeć, co jest wartościowe, czego brakuje, co jest wątpliwe
(np. ryzykowna technika ćwiczenia, brak ilości w przepisie, sprzeczność mowy z obrazem).

## Czego nie wiadomo
Lista rzeczy, których nie da się ustalić z mowy ani obrazu.

Zasady (obowiązkowe):
1. Na końcu KAŻDEJ informacji źródło: [mowa], [obraz], [mowa+obraz] albo [szacunek].
2. Niczego nie zmyślaj. Jeśli czegoś nie widać ani nie słychać, pisz „brak danych”.
3. Mowa jest pewniejsza niż opisy kadrów. Gdy opis kadru przeczy mowie lub zdrowemu rozsądkowi
   (np. „nożyce” przy krojeniu ziemniaków), zaufaj mowie / kontekstowi i zaznacz to krótko.
4. Gdy MOWA i NAPISY różnią się w nazwie, liczbie lub ilości, zwykle rację mają NAPISY (OCR) — popraw to po cichu
   w wyniku, a w „Czego nie wiadomo” wymień tylko sprzeczności, których nie da się rozstrzygnąć.
5. Bądź zwięzły i konkretny — użytkownik ma od razu wiedzieć, co zrobić.

Metadane: {meta}
Ograniczenia analizy: {gaps}

OŚ CZASU:
{timeline}
"""


def build_summary_prompt(beats: list[dict], meta: dict, gaps: list[str]) -> str:
    meta_txt = "; ".join(f"{k}: {v}" for k, v in meta.items() if v not in (None, ""))
    return SUMMARY_PROMPT.format(meta=meta_txt or "—", gaps="; ".join(gaps) or "—",
                                 timeline=beats_as_text(beats))
