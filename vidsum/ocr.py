"""Gęsty OCR napisów na ekranie (napisy wypalone w filmie, plansze z nazwami, ilościami).

Detekcja tekstu: model z pakietu RapidOCR (Apache-2.0). Rozpoznawanie: PP-OCRv5 „latin”
(Apache-2.0, zna polskie znaki), pobierany przy pierwszym użyciu z HuggingFace.

Napisy z ekranu służą do trzech rzeczy:
1) podpowiedzi słów dla Whispera (nazwy własne, liczby),
2) sprawdzenia/korekty transkrypcji,
3) dokładnego tekstu z ekranu w wyniku (zamiast zgadywania przez model obrazu).
"""
from __future__ import annotations

import hashlib
import re
import time
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .tools import find_tool, run

_HF = "https://huggingface.co/monkt/paddleocr-onnx/resolve/main/languages/latin/"
_FILES = {  # nazwa → sha256 (sprawdzane po pobraniu)
    "rec.onnx": "614ffc2d6d3902d360fad7f1b0dd455ee45e877069d14c4e51a99dc4ef144409",
    "dict.txt": "3c0a8a79b612653c25f765271714f71281e4e955962c153e272b7b8c1d2b13ff",
}


@dataclass
class OcrLine:
    start: float
    end: float
    text: str
    score: float


def ensure_models(root: Path, log=print) -> Path:
    d = Path(root) / "ocr_latin"
    d.mkdir(parents=True, exist_ok=True)
    for name in _FILES:
        p = d / name
        if not p.is_file() or p.stat().st_size == 0:
            log(f"        pobieranie modelu OCR ({name})…")
            tmp = p.with_suffix(p.suffix + ".part")
            urllib.request.urlretrieve(_HF + name, tmp)
            got = hashlib.sha256(tmp.read_bytes()).hexdigest()
            if got != _FILES[name]:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(f"Model OCR {name}: zła suma kontrolna ({got[:12]}…) — pobieranie przerwane.")
            tmp.replace(p)
    return d


class CaptionOCR:
    def __init__(self, model_dir: Path):
        from rapidocr_onnxruntime import RapidOCR
        from rapidocr_onnxruntime.ch_ppocr_v3_rec import TextRecognizer

        self.engine = RapidOCR(use_angle_cls=False)
        # podmiana rozpoznawania na model łaciński (polskie znaki); wejście 48 px wysokości
        self.engine.text_recognizer = TextRecognizer({
            "model_path": str(model_dir / "rec.onnx"), "keys_path": str(model_dir / "dict.txt"),
            "rec_img_shape": [3, 48, 320], "rec_batch_num": 6, "use_cuda": False})
        # Detektor domyślnie POWIĘKSZA klatkę tak, by krótszy bok miał 736 px (Shorts 360×640 → 736×1308).
        # Ograniczamy dłuższy bok do 768 px: pomiar — ten sam wynik (45/45 napisów), 3× szybciej.
        for op in self.engine.text_detector.preprocess_op:
            if hasattr(op, "limit_type"):
                op.limit_type, op.limit_side_len = "max", 768

    def read(self, image: Path, min_score: float = 0.80) -> list[tuple[str, float]]:
        res, _ = self.engine(str(image))
        out = []
        for box, text, score in res or []:
            text = re.sub(r"\s+", " ", str(text)).strip()
            text = re.sub(r"(?<=\d)[oO](?=[\d°])", "0", text)      # „19o°C” → „190°C”
            if float(score) >= min_score and len(text) >= 2:
                out.append((text, float(score)))
        return out


LONG_FILM_S = 900          # powyżej: OCR jednym przebiegiem i najwyżej MAX_LONG_FRAMES klatek
MAX_LONG_FRAMES = 240


def ocr_fps(duration: float) -> float:
    """Gęstość OCR: krótkie filmy (Shorts) 2 kl./s, dłuższe rzadziej (czas!).

    0.12.0, długie filmy (> 15 min): najwyżej 240 klatek na cały film, jednym przebiegiem. Pomiar 0.11.9 (dokument
    24:50): 745 klatek w dwóch przebiegach = 257 s OCR; opis kadrów skończył się 160 s wcześniej i karta czekała.
    Przy 240 klatkach i tym samym tempie (0,42 s na klatkę) to ok. 100 s — tyle, ile trwa opis kadrów."""
    if duration <= 180:
        return 2.0
    if duration <= LONG_FILM_S:
        return 1.0
    return round(min(0.5, MAX_LONG_FRAMES / duration), 4)


def _small_gray(path: Path):
    """Klatka w skali szarości, 240 px szerokości — wystarcza, by zauważyć zmianę napisu."""
    try:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        h, w = img.shape
        return cv2.resize(img, (240, max(1, int(h * 240 / w))), interpolation=cv2.INTER_AREA).astype("int16")
    except Exception:
        return None


def _same_frame(a, b) -> bool:
    """Prawie identyczne: mniej niż 0,05% pikseli zmieniło się wyraźnie (zmiana napisu to zwykle >0,5%)."""
    if a.shape != b.shape:
        return False
    import numpy as np
    return int((np.abs(a - b) > 40).sum()) < a.size * 0.0005


# nakładki aplikacji (TikTok/Instagram) przeklejone do filmu — liczniki, hashtagi, data, wyszukiwarka, utwór
# (pomiar 0.11.9, reel „wisdm”: „138.6K”, „3,933”, „#fyp #foryoupage”, „Contains: Clumsy - Fergie”, „Q Search - …”)
_JUNK = [
    re.compile(r"^\d{1,3}(?:[.,]\d)?\s?[KkMm]$"),                         # 138.6K (licznik polubień)
    re.compile(r"^\d{1,3}(?:,\d{3})+$"),                                 # 3,933
    re.compile(r"^(?:#\S+\s*)+$"),                                     # same hashtagi
    re.compile(r"[·•.]\s*(?:19|20)\d\d-\d\d-\d\d$"),                       # „nick · 2025-12-12” pod filmem
    re.compile(r"^(?:contains|original audio|oryginalny dźwięk|dźwięk oryginalny|follow|obserwuj|reply to|"
               r"odpowiedz|liked by|polubione przez|see translation|zobacz tłumaczenie)\b", re.I),
    re.compile(r"^q\s*search\b|^search\s*[-·•]", re.I),
    re.compile(r"^@[\w.]+$"),                                           # sam nick
]


def is_overlay_junk(text: str) -> bool:
    """Napis z interfejsu aplikacji (licznik, hashtagi, data, „Contains: utwór”), a nie z treści filmu."""
    t = (text or "").strip()
    return not t or any(r.search(t) for r in _JUNK)


def _ocr_key(text: str) -> str:
    return re.sub(r"[^\w]", "", text.lower()).translate(str.maketrans("l1|", "iii"))


def merge_frames(texts_at: list, fps: float) -> list[OcrLine]:
    """Napisy z kolejnych klatek → linie z czasem od–do. Ten sam napis na kolejnych klatkach = jedna linia.

    0.11.10: wcześniej szukano powtórzenia tylko w 6 ostatnich liniach, a na ekranie TikToka bywa 9–10 napisów —
    ten sam napis dopisywał się co klatkę (reel „wisdm”: 10× „I wish men had sluttier”)."""
    lines: list[OcrLine] = []
    open_: dict[str, OcrLine] = {}
    for i, texts in enumerate(texts_at):
        t = i / fps
        for text, score in texts or []:
            if is_overlay_junk(text):
                continue
            key = _ocr_key(text)                       # „why am l in” = „why am I in” (OCR myli l z I)
            last = open_.get(key)
            if last and t - last.end <= 1.5 / fps:
                last.end = round(t + 1 / fps, 2)           # ten sam napis dalej na ekranie
                last.score = max(last.score, score)
            else:
                open_[key] = OcrLine(round(t, 2), round(t + 1 / fps, 2), text, round(score, 3))
                lines.append(open_[key])
    lines.sort(key=lambda l: l.start)
    return lines


def read_captions(video: Path, duration: float, model_dir: Path, log=print) -> list[OcrLine]:
    fps = ocr_fps(duration)
    ocr = CaptionOCR(model_dir)
    lines: list[OcrLine] = []
    with tempfile.TemporaryDirectory(prefix="vidsum_ocr_") as tmp:
        # bez powiększania: Shorts 360×640 skalowane do 720 px szerokości liczyły się ~4× dłużej
        run([find_tool("ffmpeg"), "-v", "error", "-i", str(video), "-an", "-vf",
             f"fps={fps},scale='min(720,iw)':-2", "-q:v", "3", str(Path(tmp) / "f_%06d.jpg")])
        frames = sorted(Path(tmp).glob("f_*.jpg"))
        n = len(frames)
        texts_at: list[list | None] = [None] * n
        imgs = [_small_gray(f) for f in frames]
        skipped, done, last_log, t0 = 0, 0, 0.0, time.time()

        def read(i: int) -> list:
            nonlocal skipped, done, last_log
            prev = i - 1
            if prev >= 0 and texts_at[prev] is not None and imgs[i] is not None and imgs[prev] is not None \
                    and _same_frame(imgs[prev], imgs[i]):
                skipped += 1
                return texts_at[prev]                      # ta sama klatka (także te same napisy) — bez OCR
            done += 1
            res = ocr.read(frames[i])
            if time.time() - last_log > 5:                 # postęp na żywo (podgląd „co teraz robi”)
                last_log = time.time()
                log(f"        OCR {i + 1}/{n} klatek ({i / fps:.0f} s filmu): {' | '.join(x for x, _ in res)[:80]}")
            return res

        # 1. przebieg: co druga klatka. 2. przebieg: klatka pomiędzy — tylko gdy napisy przed i po się różnią
        # (wtedy coś się zmieniło i krótki napis mógłby zniknąć). Gdy napis stoi, połowa klatek odpada.
        if duration > LONG_FILM_S:                     # długi film: jeden przebieg po wszystkich (już rzadkich) klatkach
            for i in range(n):
                texts_at[i] = read(i)
        else:
            for i in range(0, n, 2):
                texts_at[i] = read(i)
            for i in range(1, n, 2):
                a = texts_at[i - 1]
                b = texts_at[i + 1] if i + 1 < n else None
                if b is not None and [x for x, _ in a] == [x for x, _ in b]:
                    texts_at[i] = a
                    skipped += 1
                else:
                    texts_at[i] = read(i)
        lines = merge_frames(texts_at, fps)
    el = time.time() - t0
    log(f"        OCR: {n} klatek ({fps}/s; odczytanych {done}, pominiętych {skipped} — bez zmiany napisów), "
        f"{len(lines)} napisów, {el:.1f} s ({el / max(1, done):.2f} s na klatkę)")
    return lines


_WORD = re.compile(r"[^\W\d_][\w'’-]{2,}", re.UNICODE)
# model łaciński myli polskie litery z czeskimi/słowackimi — w polskich filmach to zawsze pomyłka
_PL_FIX = str.maketrans({"ž": "ż", "Ž": "Ż", "š": "ś", "Š": "Ś", "č": "ć", "Č": "Ć", "ř": "r", "ě": "ę", "ý": "y"})


def fix_polish(text: str) -> str:
    return text.translate(_PL_FIX)


def hotwords_targeted(lines: list[OcrLine], title: str | None, reference: str, limit: int = 60) -> str:
    """Podpowiedź do DRUGIEJ transkrypcji: tylko napisy z ekranu zawierające słowa, których pierwsza wersja
    nie ma (to zwykle źle usłyszane nazwy/liczby), każdy jako zdanie z wielkiej litery i kropką.

    Pomiar na prawdziwym filmie (frytki): pełna lista napisów małymi literami → Whisper pisał BEZ interpunkcji
    i wielkich liter; same słowa → „Maldon” poprawione, „Agria” nie; ta wersja → oba poprawione i interpunkcja jest.
    """
    known = {w.lower() for w in re.findall(r"[\w°'’]+", reference)}
    picked: list[str] = []
    count = 0
    for l in lines:
        text = fix_polish(l.text).strip(" -–")
        new = [w for w in re.findall(r"[^\W_][\w°'’-]*", text) if len(w) >= 3 and w.lower() not in known]
        if not new or text in picked:
            continue
        picked.append(text)
        count += len(text.split())
        if count >= limit:
            break
    if not picked:
        return ""
    head = [title.strip().rstrip(".") + "."] if title else []
    return " ".join(head + [t[:1].upper() + t[1:].rstrip(".!?") + "." for t in picked])


def hotwords(lines: list[OcrLine], title: str | None = None, limit: int = 80) -> str:
    """Podpowiedź dla Whispera: tytuł + napisy z ekranu jako NATURALNY tekst (wielkie litery, interpunkcja).

    Lista słów małymi literami bez kropek sprawiała, że Whisper pisał bez interpunkcji i oddawał
    całą mowę w 2–4 kawałkach (zdania nie trafiały do scen). Pomiar (tests/bench):
    large-v3-turbo + podpowiedź: EN 0,9% → 0–1,8% WER, PL 5,5% → 1,4%.
    UWAGA: dla małych modeli (small i mniejsze) podpowiedzi szkodzą (WER 13–52%) — nie używać.
    """
    words_all: set[str] = set()
    for l in lines:
        words_all.update(w.lower() for w in _WORD.findall(l.text))
    parts: list[str] = [title.strip()] if title else []
    seen: set[str] = set()
    count = 0
    for l in lines:
        text = fix_polish(l.text)
        key = text.lower()
        toks = [w.lower() for w in _WORD.findall(text)]
        # sklejka z przejścia między napisami (np. „thenjdustthem”) — pomiń
        if any(len(o) >= 4 and o not in toks and any(o in t and len(t) >= len(o) + 4 for t in toks) for o in words_all):
            continue
        if key in seen:
            continue
        seen.add(key)
        parts.append(text)
        count += len(toks)
        if count >= limit:
            break
    return " ".join(parts)


_FILLERS = {"just", "then", "now", "so", "really", "very", "also", "simply", "gently", "quickly", "and"}


def caption_coverage(segments: list, lines: list) -> float:
    """Jaka część zdań mowy ma w tym samym momencie na ekranie napis, który ją powtarza (≥ połowa słów napisu
    jest w zdaniu). Wysoka = film ma wypalone napisy do mowy; niska = tekst na ekranie to coś innego."""
    word = re.compile(r"[^\W_]+", re.UNICODE)
    n = hit = 0
    for seg in segments:
        sw = {w.lower() for w in word.findall(getattr(seg, "text", "") or "")}
        if len(sw) < 3:
            continue
        n += 1
        for ln in lines:
            if ln.end < seg.start - 1.0 or ln.start > seg.end + 1.0:
                continue
            cw = [w.lower() for w in word.findall(ln.text)]
            if len(cw) >= 2 and sum(w in sw for w in cw) >= 0.5 * len(cw):
                hit += 1
                break
    return hit / n if n else 0.0


def correct_from_captions(segments: list, lines: list, min_score: float = 0.85) -> list[dict]:
    """Poprawia w transkrypcji pojedyncze słowa, które napis na ekranie w TYM SAMYM momencie podaje inaczej.

    Pomiar na komputerze testowym (0.7.5): Whisper „maldon chocolate” / „Steering constantly”, a na ekranie „maldon salt” /
    „stirring constantly”. Zamieniamy tylko 1 słowo na 1 słowo (litery, ≥3 znaki), gdy obok są ≥2 słowa zgodne
    z napisem, napis ma ≥3 słowa i pewność OCR ≥0.85, a słowo pada w czasie, gdy napis jest na ekranie. Zmienia `segments` w miejscu;
    zwraca listę poprawek {t, bylo, jest, napis} do zapisu w wynikach."""
    import difflib
    word = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)
    fixes: list[dict] = []
    if caption_coverage(segments, lines) < 0.4:
        # 0.11.10: na ekranie nie ma napisów do mowy, tylko np. cytowane dokumenty i nagłówki (dokument „ambasada”:
        # „Total” → „Toial”, „embassy” → „site”) — ekran nie jest wtedy zapisem tego, co ktoś mówi
        return fixes
    for seg in segments:
        text = seg.text or ""
        toks = list(word.finditer(text))
        if len(toks) < 3:
            continue
        low = [m.group(0).lower() for m in toks]
        for ln in lines:
            if ln.score < min_score or ln.end < seg.start - 1.0 or ln.start > seg.end + 1.0:
                continue
            cap = [w.lower() for w in word.findall(ln.text)]
            if len(cap) < 3:
                continue
            ops = difflib.SequenceMatcher(None, low, cap, autojunk=False).get_opcodes()
            equal = [(i1, i2) for tag, i1, i2, _, _ in ops if tag == "equal"]
            for k, (tag, i1, i2, j1, j2) in enumerate(ops):
                if tag != "replace" or j2 - j1 != 1 or i2 - i1 not in (1, 2):
                    continue
                span = (i1, i2)
                if i2 - i1 == 2:
                    # pomiar 0.11.4: mowa „Drain just lightly with potato starch”, ekran „dust lightly with” — dwa słowa
                    # mowy na jedno z ekranu; jedno z nich to wtrącenie (just, then, now…) i ono zostaje,
                    # poprawiamy tylko drugie
                    fill = [i for i in (i1, i1 + 1) if low[i] in _FILLERS]
                    if len(fill) != 1:
                        continue
                    i1 = i1 + 1 if fill[0] == i1 else i1
                    i2 = i1 + 1
                if not (cap[j1].isalpha() and low[i1].isalpha()) or min(len(cap[j1]), len(low[i1])) < 3:
                    continue
                # słowo musi paść, gdy napis jest na ekranie (czas słowa szacowany liniowo w zdaniu)
                tw = seg.start + (seg.end - seg.start) * (i1 + 0.5) / max(1, len(low))
                if not (ln.start - 1.0 <= tw <= ln.end + 1.0):
                    continue
                # słowo z mowy jest w innym napisie obok (np. „high” w „high starch content”) — potwierdzone, zostaje
                if any(low[i1] in (o.text or "").lower().split() for o in lines
                       if o is not ln and o.end >= seg.start - 3 and o.start <= seg.end + 3):
                    continue
                near = sum(b - a for (a, b) in equal if b == span[0] or a == span[1])      # zgodne słowa tuż obok
                if near < 2 or sum(b - a for a, b in equal) < 2:
                    continue
                m = toks[i1]
                new = cap[j1]
                if m.group(0)[:1].isupper():
                    new = new[:1].upper() + new[1:]
                fixes.append({"t": round(seg.start, 2), "bylo": m.group(0), "jest": new, "napis": ln.text})
                text = text[:m.start()] + new + text[m.end():]
                toks = list(word.finditer(text))
                low = [x.group(0).lower() for x in toks]
                break
        seg.text = text
    return fixes
