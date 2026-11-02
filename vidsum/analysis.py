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


def build_beats(frames: list[FrameInfo], segments: list[Segment], duration: float) -> list[dict]:
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
        beats.append({
            "start": round(start, 2), "end": round(end, 2), "kadr": f.file, "powod_kadru": f.reasons,
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
                             ("tekst_na_ekranie", "napisy"), ("cialo", "ciało")):
                val = w.get(key)
                if val:
                    parts.append(f"{lab}: {', '.join(val) if isinstance(val, list) else val}")
            parts.append(f"pewność: {w.get('pewnosc')}")
            seen = "; ".join(p for p in parts if p)
        else:
            seen = "brak opisu obrazu"
        heard = b["slychac"]["tekst"] or "—"
        lines.append(f"[{ts(b['start'])}–{ts(b['end'])}] OBRAZ: {seen}\n    MOWA: {heard}")
    return "\n".join(lines)


SUMMARY_PROMPT = """Jesteś analitykiem filmu. Dostajesz oś czasu filmu złożoną z dwóch niezależnych źródeł:
- OBRAZ — opisy kadrów wygenerowane automatycznie przez lokalny model wizyjny (mogą zawierać błędy),
- MOWA — automatyczna transkrypcja (Whisper; mogą być literówki w nazwach).

Zasady (obowiązkowe):
1. Przy KAŻDEJ informacji podaj źródło w nawiasie: [mowa], [obraz], [mowa+obraz] albo [szacunek].
2. Przy każdym momencie podaj czas z osi (mm:ss).
3. Niczego nie zmyślaj. Jeśli czegoś nie widać ani nie słychać, napisz „brak danych”.
4. Jeśli mowa i obraz sobie przeczą, napisz to wprost.
5. [szacunek] tylko dla wniosków, których nie ma wprost w danych, i krótko uzasadnij.

Odpowiedz po polsku, w Markdown, dokładnie w tym układzie:
## Streszczenie
3–6 zdań: o czym jest film, co pokazuje, jaki jest efekt końcowy.
## Najważniejsze momenty
Lista: `mm:ss` — co się dzieje — [źródło]
## Czego nie wiadomo
Lista rzeczy, których nie da się ustalić z mowy ani obrazu (brak danych).

Metadane: {meta}
Ograniczenia analizy: {gaps}

OŚ CZASU:
{timeline}
"""


def build_summary_prompt(beats: list[dict], meta: dict, gaps: list[str]) -> str:
    meta_txt = "; ".join(f"{k}: {v}" for k, v in meta.items() if v not in (None, ""))
    return SUMMARY_PROMPT.format(meta=meta_txt or "—", gaps="; ".join(gaps) or "—",
                                 timeline=beats_as_text(beats))
