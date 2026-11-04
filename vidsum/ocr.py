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

    def read(self, image: Path, min_score: float = 0.80) -> list[tuple[str, float]]:
        res, _ = self.engine(str(image))
        out = []
        for box, text, score in res or []:
            text = re.sub(r"\s+", " ", str(text)).strip()
            if float(score) >= min_score and len(text) >= 2:
                out.append((text, float(score)))
        return out


def ocr_fps(duration: float) -> float:
    """Gęstość OCR: krótkie filmy (Shorts) 2 kl./s, dłuższe rzadziej (czas!)."""
    return 2.0 if duration <= 180 else 1.0 if duration <= 900 else 0.5


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


def read_captions(video: Path, duration: float, model_dir: Path, log=print) -> list[OcrLine]:
    fps = ocr_fps(duration)
    ocr = CaptionOCR(model_dir)
    lines: list[OcrLine] = []
    with tempfile.TemporaryDirectory(prefix="vidsum_ocr_") as tmp:
        # bez powiększania: Shorts 360×640 skalowane do 720 px szerokości liczyły się ~4× dłużej
        run([find_tool("ffmpeg"), "-v", "error", "-i", str(video), "-an", "-vf",
             f"fps={fps},scale='min(720,iw)':-2", "-q:v", "3", str(Path(tmp) / "f_%06d.jpg")])
        frames = sorted(Path(tmp).glob("f_*.jpg"))
        prev_img, prev_texts = None, []
        skipped, last_log, t0 = 0, 0.0, time.time()
        for i, f in enumerate(frames):
            t = i / fps
            img = _small_gray(f)
            if prev_img is not None and img is not None and _same_frame(prev_img, img):
                texts = prev_texts                         # ta sama klatka (także te same napisy) — bez OCR
                skipped += 1
            else:
                texts = ocr.read(f)
            prev_img, prev_texts = img, texts
            if time.time() - last_log > 5:                 # postęp na żywo (podgląd „co teraz robi”)
                last_log = time.time()
                log(f"        OCR {i + 1}/{len(frames)} klatek ({t:.0f} s filmu): {' | '.join(x for x, _ in texts)[:80]}")
            for text, score in texts:
                last = next((l for l in reversed(lines[-6:]) if l.text == text), None)
                if last and t - last.end <= 1.5 / fps:
                    last.end = round(t + 1 / fps, 2)           # ten sam napis dalej na ekranie
                    last.score = max(last.score, score)
                else:
                    lines.append(OcrLine(round(t, 2), round(t + 1 / fps, 2), text, round(score, 3)))
    log(f"        OCR: {len(frames)} klatek ({fps}/s, {skipped} pominiętych jako takie same), {len(lines)} napisów, "
        f"{time.time() - t0:.1f} s")
    return lines


_WORD = re.compile(r"[^\W\d_][\w'’-]{2,}", re.UNICODE)
# model łaciński myli polskie litery z czeskimi/słowackimi — w polskich filmach to zawsze pomyłka
_PL_FIX = str.maketrans({"ž": "ż", "Ž": "Ż", "š": "ś", "Š": "Ś", "č": "ć", "Č": "Ć", "ř": "r", "ě": "ę", "ý": "y"})


def fix_polish(text: str) -> str:
    return text.translate(_PL_FIX)


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
