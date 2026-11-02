"""Mowa -> tekst ze znacznikami czasu. Silnik: faster-whisper (lokalnie) albo plik napisów."""
from __future__ import annotations

import gc
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    language: str | None
    engine: str
    segments: list[Segment] = field(default_factory=list)
    note: str | None = None


class WhisperEngine:
    """faster-whisper (MIT). Na GPU NVIDIA używa CUDA, inaczej CPU int8."""

    def __init__(self, model: str = "small", device: str = "auto", compute_type: str = "auto",
                 download_root: str | None = None):
        self.model_name, self.device, self.compute_type, self.root = model, device, compute_type, download_root

    def resolve_device(self) -> tuple[str, str | None]:
        """Zwraca (urządzenie, uwaga). GPU tylko wtedy, gdy biblioteki CUDA da się NAPRAWDĘ załadować.

        Na Windows brak cuBLAS/cuDNN potrafi nie rzucić wyjątku, tylko zawiesić albo zamknąć
        proces w kodzie natywnym — dlatego sprawdzamy biblioteki przed użyciem GPU.
        """
        if self.device != "auto":
            return self.device, None
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() <= 0:
                return "cpu", None
        except Exception:
            return "cpu", None
        missing = _missing_cuda_libs()
        if missing:
            return "cpu", (f"Whisper na CPU — brak bibliotek CUDA ({', '.join(missing)}). "
                           "Model obrazu w Ollamie nadal używa GPU.")
        return "cuda", None

    def transcribe(self, wav: Path, language: str | None = None) -> Transcript:
        from faster_whisper import WhisperModel

        device, note = self.resolve_device()
        try:
            t = self._run(WhisperModel, wav, language, device, self.compute_type)
        except Exception as e:
            if device != "cuda" or self.device == "cuda":
                raise
            t = self._run(WhisperModel, wav, language, "cpu", "int8")
            note = f"Whisper na CPU — błąd GPU ({type(e).__name__}). Model obrazu w Ollamie nadal używa GPU."
        t.note = note
        return t

    def _run(self, WhisperModel, wav: Path, language, device: str, compute: str) -> Transcript:
        if compute == "auto":
            compute = "float16" if device == "cuda" else "int8"
        audio = _load_wav16k(wav)
        model = WhisperModel(self.model_name, device=device, compute_type=compute, download_root=self.root)
        try:
            segs, info = model.transcribe(audio, language=language, vad_filter=True, word_timestamps=True,
                                          beam_size=1, condition_on_previous_text=False)  # beam 1: ~2x szybciej
            out = []
            for s in segs:
                if not s.text.strip():
                    continue
                # czas z pierwszego/ostatniego słowa — dokładniejszy niż czas segmentu
                # (segment potrafi „zacząć się” w ciszy przed mową)
                st, en = (s.words[0].start, s.words[-1].end) if s.words else (s.start, s.end)
                out.append(Segment(round(st, 2), round(en, 2), s.text.strip()))
        finally:
            del model          # zwolnij VRAM przed modelem wizyjnym (8 GB nie zmieści obu naraz)
            gc.collect()
        return Transcript(info.language, f"faster-whisper:{self.model_name}:{device}", out)


def _missing_cuda_libs() -> list[str]:
    import ctypes
    import os
    if os.name == "nt":
        groups = [["cublas64_12.dll"], ["cudnn_ops64_9.dll", "cudnn64_9.dll"]]
        loader = ctypes.WinDLL  # type: ignore[attr-defined]
    else:
        groups = [["libcublas.so.12"], ["libcudnn_ops.so.9", "libcudnn.so.9"]]
        loader = ctypes.CDLL
    missing = []
    for alts in groups:
        for name in alts:
            try:
                loader(name)
                break
            except OSError:
                continue
        else:
            missing.append(alts[0])
    return missing


def _load_wav16k(wav: Path):
    """Wczytuje WAV 16 kHz mono PCM16 (z ffmpeg) jako float32 — bez PyAV, którego nowe wersje
    są niezgodne z faster-whisper 1.2.1 (`metadata_errors`)."""
    import wave

    import numpy as np

    with wave.open(str(wav), "rb") as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("Oczekiwano WAV 16 kHz mono 16-bit.")
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


_SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def _t(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


class SidecarEngine:
    """Gotowe napisy (.srt albo .json z listą {start,end,text}) — do testów i gdy napisy już są."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def transcribe(self, wav: Path | None = None, language: str | None = None) -> Transcript:
        raw = self.path.read_text(encoding="utf-8-sig")
        segs: list[Segment] = []
        if self.path.suffix.lower() == ".vtt":
            segs = parse_vtt(raw)
        elif self.path.suffix.lower() == ".json":
            data = json.loads(raw)
            items = data["segments"] if isinstance(data, dict) else data
            segs = [Segment(float(i["start"]), float(i["end"]), i["text"].strip()) for i in items]
            language = language or (data.get("language") if isinstance(data, dict) else None)
        else:
            for block in re.split(r"\n\s*\n", raw.strip()):
                lines = block.strip().splitlines()
                for i, line in enumerate(lines):
                    m = _SRT_TIME.search(line)
                    if m:
                        g = m.groups()
                        segs.append(Segment(_t(*g[:4]), _t(*g[4:]), " ".join(lines[i + 1:]).strip()))
                        break
        return Transcript(language, f"napisy:{self.path.name}", segs)


_VTT_TIME = re.compile(r"(?:(\d+):)?(\d+):(\d+)\.(\d+)\s*-->\s*(?:(\d+):)?(\d+):(\d+)\.(\d+)")
_TAG = re.compile(r"<[^>]+>")


def parse_vtt(raw: str) -> list[Segment]:
    """WebVTT (np. YouTube). Automatyczne napisy YouTube „przewijają się”: każdy wpis powtarza
    poprzednią linię — bierzemy tylko nowy tekst i scalamy powtórzenia."""
    cues: list[tuple[float, float, list[str]]] = []
    for line in raw.replace("\r", "").split("\n"):
        m = _VTT_TIME.search(line)
        if m:
            g = [x or "0" for x in m.groups()]
            if cues and cues[-1][2] and cues[-1][2][-1].isdigit():
                cues[-1][2].pop()                       # numer następnego wpisu, nie tekst
            cues.append((_t(*g[:4]), _t(*g[4:]), []))
        elif cues:
            txt = _TAG.sub("", line).strip()
            if txt:
                cues[-1][2].append(txt)
    segs: list[Segment] = []
    seen_last = ""
    for st, en, lines in cues:
        if not lines or en - st < 0.05:
            continue
        new = [l for l in lines if l != seen_last]
        seen_last = lines[-1]
        if not new:
            continue
        text = " ".join(new)
        if segs and segs[-1].text == text:
            segs[-1].end = round(en, 2)
        else:
            segs.append(Segment(round(st, 2), round(en, 2), text))
    return segs
