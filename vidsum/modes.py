"""Tryby analizy (0.12.0) i kadry wskazane mową.

Tryby (przełącznik przy linku):
- "pelna"  — jak dotąd: opis wybranych kadrów + OCR całego filmu + mowa. Najdokładniejsza dla przepisów i ćwiczeń.
- "mowa"   — tylko mowa: transkrypcja → cały raport. Bez modelu obrazu i bez OCR (kilka miniatur do podglądu).
- "szybki" — mowa + szybki obraz: najpierw raport z mowy, potem opis tylko wybranych kadrów (wskazane mową,
             początki rozdziałów, kilka równo rozłożonych) i napisy z tych kadrów; raport jest UZUPEŁNIANY.

Kadry wskazane mową: narrator mówi „look at this”, „right here”, „this is what…”, „spójrzcie”, „jak widać” — to znak,
że na ekranie jest coś, o czym mowa. Pomiar na dokumencie 24:50 (0.11.9): z pięciu takich miejsc trzy nie miały
swojego kadru (mapa przy „It's located here”, 06:47; kable przy „One is right here”, 07:58; list przy „This one.”, 19:30),
bo 100 kadrów było wybieranych tylko po zmianach sceny. Funkcje tu są czyste (bez ffmpeg i modeli) — testowane jednostkowo.
"""
from __future__ import annotations

import re

MODES = ("pelna", "mowa", "szybki")
MODE_LABEL = {"pelna": "Pełna", "mowa": "Tylko mowa", "szybki": "Mowa + szybki obraz"}

_CUE_EN = (r"look(?:ing)? at (?:this|that|these|those|here|the|how|what)|take a (?:close[r]? )?look|(?:as )?you can see|"
           r"can see (?:here|this|that|it)|right here|over here|(?:located|is|are|sits|it's) here\b|this is what|"
           r"here(?:'s| is| are) (?:what|how|the|a|an|my|our)|this one\b|watch (?:this|closely|how|what)|"
           r"check (?:this|it) out|shown here|(?:on|in) (?:the|this) (?:screen|map|chart|graph|diagram|slide|picture|image|photo|"
           r"footage|blueprint|plan)s?|this (?:chart|graph|map|diagram|picture|image|photo|slide|table|screenshot|footage)")
_CUE_PL = (r"sp[oó]jrz(?:cie|my)?|zobacz(?:cie|my)?|popatrz(?:cie|my)?|jak wida[ćc]|wida[ćc] (?:tu|tutaj|to|na|jak|że)|"
           r"o,? tutaj|tutaj (?:wida[ćc]|mamy|jest|są)|wygląda to tak|to wygląda tak|tak to wygląda|"
           r"na (?:tym |tej )?(?:ekranie|mapie|wykresie|zdjęciu|obrazku|slajdzie|schemacie|nagraniu|planie)|"
           r"ten (?:wykres|schemat|obrazek|slajd)|ta (?:mapa|tabela)|to zdjęcie|to nagranie")
CUE = re.compile(r"(?<![\w'’])(?:" + _CUE_EN + "|" + _CUE_PL + r")(?![\w])", re.I)


def normalize_mode(x) -> str:
    x = str(x or "").strip().lower()
    return x if x in MODES else "pelna"


def speech_cues(segments: list[dict], duration: float, skip: list[tuple[float, float]] | None = None,
                limit: int = 18, lead: float = 0.8) -> list[dict]:
    """Momenty, w których mowa wskazuje na obraz → [{t, zwrot, tekst}], najwyżej `limit`, co najmniej 4 s od siebie.

    Czas kadru: miejsce zwrotu w zdaniu (liniowo po znakach) + `lead` s — to, o czym mowa, zwykle jest na ekranie chwilę
    po słowach. `skip` — odcinki reklam (nie pokazujemy „Scan this QR code”)."""
    skip = skip or []
    out: list[dict] = []
    for s in segments:
        text = str(s.get("text") or "")
        a, b = float(s.get("start") or 0), float(s.get("end") or s.get("start") or 0)
        for m in CUE.finditer(text):
            t = a + (b - a) * (m.end() / max(1, len(text))) + lead
            t = round(max(0.0, min(t, b + 2.0, max(0.0, duration - 0.2))), 2)
            if any(x - 1 <= t <= y + 1 for x, y in skip) or any(x <= a <= y for x, y in skip):
                continue
            if out and t - out[-1]["t"] < 4.0:
                continue
            out.append({"t": t, "zwrot": m.group(0), "tekst": text[:120]})
    if len(out) > limit:                                  # gadatliwy narrator: równo rozłożone
        step = len(out) / limit
        out = [out[int(i * step)] for i in range(limit)]
    return out


def thumbnail_times(duration: float) -> list[float]:
    """Kilka równo rozłożonych kadrów: miniatury w trybie „mowa” i kadry „pokrycia” w trybie „szybki”
    (jeden na ~2 minuty, od 4 do 12; krótki film: co najmniej jeden na 15 s)."""
    if duration <= 0:
        return []
    n = max(1, min(4, int(duration // 15) or 1)) if duration < 240 else max(4, min(12, round(duration / 120)))
    return [round(duration * (i + 0.5) / n, 2) for i in range(n)]


def light_picks(duration: float, cues: list[dict], chapter_starts: list[float], max_frames: int) -> list[dict]:
    """Kadry dla trybu „szybki”: wskazane mową (pierwszeństwo), początki rozdziałów (+1,5 s), równe pokrycie.
    Nie bliżej niż 3 s od siebie; nigdy więcej niż `max_frames` (limit pełnej analizy) ani niż 30."""
    cap = max(1, min(30, max_frames))
    cands = [{"t": c["t"], "reasons": ["wskazany_w_mowie"], "pri": 0, "zwrot": c.get("zwrot", "")} for c in cues]
    cands += [{"t": round(min(max(0.0, duration - 0.2), s + 1.5), 2), "reasons": ["poczatek_rozdzialu"], "pri": 1}
              for s in chapter_starts[:12]]
    cands += [{"t": t, "reasons": ["pokrycie"], "pri": 2} for t in thumbnail_times(duration)]
    kept: list[dict] = []
    for c in sorted(cands, key=lambda x: (x["pri"], x["t"])):
        if len(kept) >= cap:
            break
        if all(abs(c["t"] - k["t"]) >= 3.0 for k in kept):
            kept.append(c)
    return sorted(kept, key=lambda x: x["t"])


def extra_cue_picks(existing: list[float], cues: list[dict], max_extra: int = 12) -> list[dict]:
    """Tryb „pełna”: kadry wskazane mową dokładane do wybranych po zmianach sceny — tylko tam, gdzie w promieniu 2 s
    nie ma już kadru."""
    out = []
    for c in cues:
        if len(out) >= max_extra:
            break
        if all(abs(c["t"] - t) >= 2.0 for t in existing) and all(abs(c["t"] - o["t"]) >= 2.0 for o in out):
            out.append({"t": c["t"], "reasons": ["wskazany_w_mowie"], "zwrot": c.get("zwrot", "")})
    return out


def shown_items(cues: list[dict], frames: list, ocr: list, segments: list[dict], limit: int = 12) -> list[dict]:
    """„Pokazane na ekranie”: co narrator mówi, gdy wskazuje na obraz, i co wtedy widać.

    Dla każdego zwrotu („look at this”) — najbliższy opisany kadr (do 2 s) i napisy odczytane z ekranu w tym momencie.
    → [{t, mowa, zwrot, obraz, napisy:[…], czasy:[t linii]}]. Pozycje bez opisu kadru i bez napisów pomijamy."""
    from .ocr import is_overlay_junk
    out = []
    for c in cues:
        fr = min(frames, key=lambda f: abs(f.t - c["t"]), default=None)
        if fr is None or abs(fr.t - c["t"]) > 2.0:
            continue
        v = fr.vision or {}
        seen = " ".join(str(v.get("scena") or "").split())
        if v.get("czynnosci"):
            seen += " (" + ", ".join(v["czynnosci"][:3]) + ")"
        texts: list[str] = []
        for o in ocr:
            a, b = float(getattr(o, "start", 0)), float(getattr(o, "end", 0))
            text = " ".join(str(getattr(o, "text", "")).split())
            if a - 1.5 <= fr.t <= b + 1.5 and len(text) >= 3 and not is_overlay_junk(text) and text not in texts:
                texts.append(text)
        texts = sorted(texts, key=len, reverse=True)[:3]
        if not seen and not texts:
            continue
        seg = next((s for s in segments if float(s["start"]) <= c["t"] <= float(s.get("end") or s["start"]) + 2.5
                    and c.get("zwrot", "").lower() in str(s.get("text") or "").lower()), None)
        out.append({"t": fr.t, "mowa": str((seg or {}).get("text") or c.get("tekst") or "").strip(), "zwrot": c.get("zwrot", ""),
                    "obraz": seen, "napisy": texts, "czasy": [float(seg["start"])] if seg else []})
        if len(out) >= limit:
            break
    return out


def suggest_mode(duration: float, vram_mb: int | None) -> tuple[str, str]:
    """Tryb proponowany dla tego komputera i filmu → (tryb, powód po polsku). Tylko PROPOZYCJA dla interfejsu —
    wybór użytkownika zawsze wygrywa. Bez karty NVIDIA albo z małą pamięcią karty opis kadrów liczy się na procesorze
    (bardzo wolno), więc proponujemy samą mowę."""
    if not vram_mb:
        return "mowa", "Nie wykryto karty NVIDIA — opis kadrów liczyłby się na procesorze (bardzo wolno)."
    if vram_mb < 5500:
        return "mowa", f"Karta ma {vram_mb / 1024:.0f} GB pamięci — model obrazu może się na niej nie zmieścić."
    return "pelna", ""
