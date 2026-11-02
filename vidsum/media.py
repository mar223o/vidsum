"""Operacje na wideo przez ffmpeg: metadane, audio, wynik zmian scen i wybór kadrów."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .tools import find_tool, run


@dataclass
class MediaInfo:
    duration: float
    width: int | None
    height: int | None
    has_audio: bool
    fps: float | None


def probe(path: Path) -> MediaInfo:
    out = run([find_tool("ffprobe"), "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", str(path)]).stdout_text
    data = json.loads(out)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    a = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    if v is None:
        raise ValueError("Plik nie zawiera ścieżki wideo.")
    fps = None
    if v.get("avg_frame_rate") and v["avg_frame_rate"] != "0/0":
        n, d = v["avg_frame_rate"].split("/")
        fps = float(n) / float(d) if float(d) else None
    dur = float(data.get("format", {}).get("duration") or v.get("duration") or 0)
    return MediaInfo(dur, v.get("width"), v.get("height"), a, fps)


def extract_audio(path: Path, wav: Path) -> Path:
    run([find_tool("ffmpeg"), "-y", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
         "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])
    return wav


_PTS = re.compile(r"pts_time:([0-9.]+)")
_SCORE = re.compile(r"lavfi\.scene_score=([0-9.]+)")


def scene_scores(path: Path, sample_fps: float) -> list[tuple[float, float]]:
    """Zwraca listę (czas_s, wynik_zmiany_sceny 0..1) dla klatek próbkowanych z sample_fps.

    Jedno przejście ffmpeg na zmniejszonym obrazie — tanie nawet dla filmu 40 min.
    """
    proc = run([find_tool("ffmpeg"), "-v", "info", "-nostats", "-i", str(path), "-an",
                "-vf", f"fps={sample_fps},scale=320:-2,select='gte(scene,0)',metadata=print",
                "-f", "null", "-"])
    scores: list[tuple[float, float]] = []
    t = None
    for line in proc.stderr_text.splitlines():  # type: ignore[attr-defined]
        m = _PTS.search(line)
        if m:
            t = float(m.group(1))
            continue
        m = _SCORE.search(line)
        if m and t is not None:
            scores.append((t, float(m.group(1))))
            t = None
    return scores


@dataclass
class FramePick:
    t: float
    reasons: list[str] = field(default_factory=list)
    score: float = 0.0


@dataclass
class SamplingPlan:
    base_interval: float
    max_frames: int
    scene_threshold: float = 0.22   # 0.30 gubiło cięcia między ciemnymi ujęciami (test: 0.255)
    activity_threshold: float = 0.06
    min_gap: float = 1.0


def plan_for(duration: float, max_frames: int | None = None) -> SamplingPlan:
    """Dobiera gęstość kadrów do długości: krótki przepis gęsto, 40 min rzadziej."""
    if max_frames is None:
        max_frames = 40 if duration <= 120 else 80 if duration <= 600 else 150
    base = max(2.0, min(30.0, duration / max(1, max_frames * 0.6)))
    return SamplingPlan(base_interval=round(base, 2), max_frames=max_frames)


_PRIORITY = {"zmiana_sceny": 0, "aktywnosc": 1, "pokrycie": 2}


def choose_frames(scores: list[tuple[float, float]], duration: float, plan: SamplingPlan) -> list[FramePick]:
    """Wybiera momenty kadrów: cięcia scen + gęściej w ruchu + równomierne pokrycie.

    Funkcja czysta (bez ffmpeg) — testowana jednostkowo.
    """
    cands: list[FramePick] = []
    end = max(0.0, duration - 0.05)
    # 1) cięcia scen: kadr chwilę PO cięciu, żeby nie złapać przejścia
    for t, s in scores:
        if s >= plan.scene_threshold:
            cands.append(FramePick(min(end, t + 0.5), ["zmiana_sceny"], s))
    # 2) aktywność: średni wynik w oknie ~2 s powyżej progu -> dodatkowe kadry co base/2
    if scores:
        win = 4
        step = plan.base_interval / 2
        last = -1e9
        for i in range(len(scores)):
            chunk = [s for _, s in scores[max(0, i - win // 2): i + win // 2 + 1]]
            mean = sum(chunk) / len(chunk)
            t = scores[i][0]
            if plan.activity_threshold <= mean < plan.scene_threshold and t - last >= step:
                cands.append(FramePick(min(end, t), ["aktywnosc"], mean))
                last = t
    # 3) pokrycie bazowe: pierwszy kadr na 0.5 s, potem co base_interval
    t = min(0.5, end)
    while t <= end:
        cands.append(FramePick(round(t, 2), ["pokrycie"], 0.0))
        t += plan.base_interval

    # scalanie bliskich kandydatów (wygrywa ważniejszy powód)
    cands.sort(key=lambda c: (c.t, _PRIORITY[c.reasons[0]]))
    merged: list[FramePick] = []
    for c in cands:
        if merged and c.t - merged[-1].t < plan.min_gap:
            m = merged[-1]
            for r in c.reasons:
                if r not in m.reasons:
                    m.reasons.append(r)
            if _PRIORITY[c.reasons[0]] < _PRIORITY[m.reasons[0]]:
                m.t, m.score = c.t, c.score
                m.reasons.sort(key=_PRIORITY.get)
            continue
        merged.append(c)

    # limit: najpierw odrzucamy "pokrycie", potem "aktywność" — z zachowaniem rozkładu w czasie
    for drop in ("pokrycie", "aktywnosc"):
        while len(merged) > plan.max_frames:
            pool = [i for i, m in enumerate(merged) if m.reasons == [drop]]
            if not pool:
                break
            # usuń kadr z najmniejszą przerwą do sąsiadów (najmniej informacji)
            def gap(i: int) -> float:
                prev = merged[i - 1].t if i > 0 else 0.0
                nxt = merged[i + 1].t if i + 1 < len(merged) else duration
                return nxt - prev
            merged.pop(min(pool, key=gap))
    if len(merged) > plan.max_frames:  # same cięcia — zostaw najsilniejsze
        merged = sorted(sorted(merged, key=lambda m: -m.score)[: plan.max_frames], key=lambda m: m.t)
    return merged


def extract_frame(path: Path, t: float, out: Path, width: int = 768) -> Path:
    run([find_tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path),
         "-frames:v", "1", "-vf", f"scale='min({width},iw)':-2", "-q:v", "3", str(out)])
    return out
