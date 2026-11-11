"""Mowa -> tekst ze znacznikami czasu. Silnik: faster-whisper (lokalnie) albo plik napisów."""
from __future__ import annotations

import gc
import time
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
                 download_root: str | None = None, beam_size: int | None = None, hotwords: str | None = None):
        self.model_name, self.device, self.compute_type, self.root = model, device, compute_type, download_root
        self.beam_size = beam_size          # None = 5 na GPU (dokładnie), 1 na CPU (szybko)
        self.hotwords = hotwords            # słowa-podpowiedzi: tytuł, napisy z ekranu (nazwy, marki)
        self.coverage_hints: list[tuple[float, float]] = []   # gdzie na ekranie były napisy (OCR)
        self.recovered = 0                  # ile zdań odzyskano drugim przebiegiem
        self.cuda_download = False          # pobierz biblioteki CUDA, jeśli jest karta NVIDIA, a ich brak
        self._resolved: tuple[str, str | None] | None = None
        self.timings: dict = {}             # 0.11.9: wczytanie modelu / rozpoznanie / drugi przebieg (s) — pomiar czasu

    def resolve_device(self, log=None) -> tuple[str, str | None]:
        """Zwraca (urządzenie, uwaga). GPU tylko wtedy, gdy biblioteki CUDA da się NAPRAWDĘ załadować.

        Na Windows brak cuBLAS/cuDNN potrafi nie rzucić wyjątku, tylko zawiesić albo zamknąć
        proces w kodzie natywnym — dlatego sprawdzamy biblioteki przed użyciem GPU. Gdy jest karta
        NVIDIA, a bibliotek brak, pobieramy je jednorazowo (cuda_download=True; zob. vidsum/cuda.py).
        """
        if self._resolved:
            return self._resolved
        self._resolved = self._resolve(log or (lambda s: None))
        return self._resolved

    def _resolve(self, log) -> tuple[str, str | None]:
        if self.device == "cpu":
            return "cpu", None
        from . import cuda
        cuda.activate()
        if self.device == "cuda":
            return "cuda", None
        if cuda.gpu_count() <= 0:
            return "cpu", None
        missing = _missing_cuda_libs()
        fail = None
        if missing and self.cuda_download:
            try:
                cuda.ensure(log)
                cuda.activate()
                missing = _missing_cuda_libs()
            except Exception as e:      # brak sieci / miejsca — analiza idzie dalej na CPU
                fail = f"{type(e).__name__}: {str(e)[:120]}"
                log(f"        ! biblioteki CUDA: {fail}")
        if missing:
            why = f"nie udało się pobrać bibliotek CUDA ({fail})" if fail else f"brak bibliotek CUDA ({', '.join(missing)})"
            return "cpu", (f"Whisper na CPU — {why}. Model obrazu w Ollamie nadal używa GPU. "
                           "Biblioteki można pobrać poleceniem: VidSum --pobierz-cuda")
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
        t_load = time.time()
        model = WhisperModel(self.model_name, device=device, compute_type=compute, download_root=self.root)
        self.timings = {"wczytanie_s": round(time.time() - t_load, 1), "typ": compute}
        t_dec = time.time()
        try:
            beam = self.beam_size or 5      # dokładność ważniejsza niż szybkość (turbo: beam 5 ≈ ten sam czas)

            batched = None
            if device == "cuda":
                # GPU: kilka fragmentów mowy naraz (BatchedInferencePipeline) — kilka razy szybciej przy tej samej dokładności
                from faster_whisper import BatchedInferencePipeline
                batched = BatchedInferencePipeline(model)

            def decode(chunk, offset: float, hot) -> tuple[list[Segment], object]:
                nonlocal batched
                kw = dict(language=language, vad_filter=True, word_timestamps=True, beam_size=beam,
                          condition_on_previous_text=False, hotwords=hot or None)
                if batched is not None:
                    try:
                        segs, info = batched.transcribe(chunk, batch_size=8, **kw)
                        segs = list(segs)
                    except Exception:            # starsza karta / za mało VRAM — zwykły tryb
                        batched = None
                        segs, info = model.transcribe(chunk, **kw)
                else:
                    segs, info = model.transcribe(chunk, **kw)
                res = []
                for s in segs:
                    if not s.text.strip():
                        continue
                    if s.words:
                        res.extend(split_sentences([(w.start + offset, w.end + offset, w.word) for w in s.words]))
                    else:
                        res.append(Segment(round(s.start + offset, 2), round(s.end + offset, 2), s.text.strip()))
                return res, info

            out, info = decode(audio, 0.0, self.hotwords)
            self.timings["rozpoznanie_s"] = round(time.time() - t_dec, 1)
            t_dec = time.time()
            # Zabezpieczenie: z podpowiedzią Whisper czasem POMIJA zdanie. Tam, gdzie na ekranie są napisy
            # (zwykle = mowa), a w transkrypcji nic nie ma — przepisz ten fragment jeszcze raz BEZ podpowiedzi.
            if self.hotwords and self.coverage_hints:
                for a0, a1 in uncovered(self.coverage_hints, out):
                    lo, hi = max(0, int((a0 - 0.5) * 16000)), int((a1 + 0.5) * 16000)
                    extra, _ = decode(audio[lo:hi], lo / 16000, None)
                    if not extra:
                        continue
                    e0, e1 = extra[0].start, extra[-1].end
                    old = [o for o in out if o.start < e1 and e0 < o.end]
                    # w tym fragmencie wygrywa wersja z większą liczbą słów (drugi przebieg nic nie „przeskakuje”)
                    if sum(len(x.text.split()) for x in extra) > sum(len(o.text.split()) for o in old):
                        out = [o for o in out if o not in old] + extra
                        self.recovered += len(extra)
                out.sort(key=lambda x: x.start)
            self.timings["drugi_przebieg_s"] = round(time.time() - t_dec, 1)
        finally:
            del model          # zwolnij VRAM przed modelem wizyjnym (8 GB nie zmieści obu naraz)
            gc.collect()
        return Transcript(info.language, f"faster-whisper:{self.model_name}:{device}", out)


def uncovered(hints: list[tuple[float, float]], segs: list[Segment], min_len: float = 1.0) -> list[tuple[float, float]]:
    """Okna czasu, w których były napisy na ekranie, a transkrypcja nie ma ani jednego zdania."""
    gaps: list[list[float]] = []
    for a, b in sorted(hints):
        if any(s.start < b + 0.3 and a - 0.3 < s.end for s in segs):
            continue
        if gaps and a - gaps[-1][1] <= 1.0:
            gaps[-1][1] = max(gaps[-1][1], b)
        else:
            gaps.append([a, b])
    return [(a, b) for a, b in gaps if b - a >= min_len]


def split_sentences(words: list[tuple[float, float, str]], max_len: float = 12.0, pause: float = 0.5) -> list[Segment]:
    """Dzieli mowę na zdania po znacznikach czasu słów: koniec zdania (.?!), pauza albo zbyt długi kawałek.

    Whisper z podpowiedziami potrafi oddać całą minutę jako 1–2 segmenty — wtedy zdania nie
    trafiałyby do właściwych scen na osi czasu. Czas zdania = pierwsze i ostatnie słowo.
    """
    out: list[Segment] = []
    cur: list[tuple[float, float, str]] = []

    def flush():
        if cur:
            text = "".join(w[2] for w in cur).strip()
            if text:
                out.append(Segment(round(cur[0][0], 2), round(cur[-1][1], 2), text))
            cur.clear()

    for i, w in enumerate(words):
        if cur and (w[0] - cur[-1][1] > pause or w[1] - cur[0][0] > max_len):
            flush()
        cur.append(w)
        if w[2].strip().endswith((".", "?", "!", "…")):
            flush()
    flush()
    return out


def _missing_cuda_libs() -> list[str]:
    import ctypes
    import os
    if os.name == "nt":
        groups = [["cublas64_12.dll"], ["cublasLt64_12.dll"], ["cudnn_ops64_9.dll", "cudnn64_9.dll"]]
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
