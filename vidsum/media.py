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
    has_video: bool = True            # False: plik dźwiękowy (mp3, m4a, wav…) — analiza samej mowy (0.12.0)


AUDIO_EXT = (".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac", ".aac", ".wma", ".oga", ".m4b")


def probe(path: Path) -> MediaInfo:
    out = run([find_tool("ffprobe"), "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", str(path)]).stdout_text
    data = json.loads(out)
    # okładka w pliku mp3/m4a jest w ffprobe „strumieniem wideo” (attached_pic) — to nie film
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    if v is None:
        if not a:
            raise ValueError("Plik nie zawiera ani obrazu, ani dźwięku.")
        # 0.12.0: plik dźwiękowy (podcast, nagranie wykładu, notatka głosowa) — streszczamy samą mowę
        return MediaInfo(float(data.get("format", {}).get("duration") or 0), None, None, True, None, has_video=False)
    fps = None
    if v.get("avg_frame_rate") and v["avg_frame_rate"] != "0/0":
        n, d = v["avg_frame_rate"].split("/")
        fps = float(n) / float(d) if float(d) else None
    dur = float(data.get("format", {}).get("duration") or v.get("duration") or 0)
    return MediaInfo(dur, v.get("width"), v.get("height"), a, fps)


def _gray_frame(path: Path, t: float, w: int, h: int) -> bytes | None:
    """Jedna klatka jako surowe bajty jasności (szarość) w rozmiarze w×h."""
    r = run([find_tool("ffmpeg"), "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", "-an",
             "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"], check=False, timeout=60)
    data = r.stdout if isinstance(r.stdout, bytes) else b""
    return data if len(data) == w * h else None


def _dark_edges(px: bytes, w: int, h: int, limit: int = 32) -> tuple[int, int, int, int]:
    """Ile wierszy od góry/dołu i kolumn od lewej/prawej jest czarnych (prawie wszystkie piksele ≤ limit)."""
    def dark(vals) -> bool:
        vals = sorted(vals)
        return vals[int(len(vals) * 0.98) - 1] <= limit       # 98% pikseli ciemnych (szum, logo w rogu nie psują)
    rows = [dark(px[y * w:(y + 1) * w]) for y in range(h)]
    cols = [dark(px[x::w]) for x in range(w)]

    def lead(seq) -> int:
        n = 0
        for v in seq:
            if not v:
                break
            n += 1
        return n
    return lead(rows), lead(rows[::-1]), lead(cols), lead(cols[::-1])


def detect_bars(path: Path, duration: float, width: int | None, height: int | None,
                points: tuple[float, ...] = (.1, .3, .5, .7, .9)) -> dict | None:
    """Czarne pasy wpalone w obraz (np. film 2,39:1 w kontenerze 16:9, pionowy film z pasami po bokach).

    Własny pomiar (filtr `cropdetect` jest tylko w kompilacjach GPL ffmpeg, a program ma LGPL): 5 klatek
    pomniejszonych do ~200 px, liczone czarne wiersze/kolumny przy krawędziach. Ostrożnie:
    - pasem jest tylko to, co czarne we WSZYSTKICH klatkach (najmniejszy pas) — ciemna scena nie zmniejsza kadru;
    - potrzeba co najmniej 3 udanych klatek;
    - pas musi mieć ≥ 3% wymiaru, a zostać musi ≥ 50% obrazu.
    Zwraca {"x", "y", "w", "h"} obszaru z obrazem (w pikselach oryginału) albo None. Plik zostaje bez zmian."""
    if not (width and height and duration > 0):
        return None
    sw = 200
    sh = max(2, round(height * sw / width / 2) * 2)
    edges = []
    for frac in points:
        try:
            px = _gray_frame(path, max(0.0, duration * frac), sw, sh)
        except Exception:
            px = None
        if px:
            edges.append(_dark_edges(px, sw, sh))
    if len(edges) < 3:
        return None
    top, bot, left, right = (min(e[i] for e in edges) for i in range(4))
    ky, kx = height / sh, width / sw
    # zaokrąglenie do środka obrazu (pomniejszenie rozmywa granicę o ~1 piksel) — raczej zostaw cienki pas niż utnij
    y0 = int((top + 1) * ky) if top else 0
    y1 = height - (int((bot + 1) * ky) if bot else 0)
    x0 = int((left + 1) * kx) if left else 0
    x1 = width - (int((right + 1) * kx) if right else 0)
    y0, x0 = y0 - y0 % 2, x0 - x0 % 2
    w, h = x1 - x0, y1 - y0
    if w < width * 0.5 or h < height * 0.5:
        return None                                   # „zostałoby” za mało — raczej ciemny film niż pasy
    bars_x, bars_y = (width - w) / width, (height - h) / height
    if bars_x < 0.03 and bars_y < 0.03:
        return None                                   # brak pasów (albo kilka pikseli ramki)
    if bars_x < 0.03:
        x0, w = 0, width                              # pas za mały — w tej osi nic nie ruszamy
    if bars_y < 0.03:
        y0, h = 0, height
    return {"x": x0, "y": y0, "w": w, "h": h}


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
        # mniej kadrów = szybciej; większość treści i tak niesie mowa, kadry ją uzupełniają
        # do 2 min: kadr na ~4 s (min. 10, maks. 20). Pomiar 0.8.2 (frytki 58 s): 20 kadrów co 2–3 s, sąsiednie
        # prawie takie same („wycieranie wody z miski” ×3), a opis kadrów był najdłuższym etapem (38 s z 99)
        max_frames = max(10, min(20, int(duration / 4 + 0.5))) if duration <= 120 else 45 if duration <= 600 else 100
    base = max(3.0, min(30.0, duration / max(1, max_frames * 0.7)))
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
    last = max(t, duration - 1.0)   # bez kadru w ostatniej sekundzie (pusty odcinek „05:00–05:00”)
    while t <= last:
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
            # kadr z początku filmu zostaje zawsze — inaczej pierwszy odcinek pokazywałby obraz z dalszej części
            pool = [i for i, m in enumerate(merged) if m.reasons == [drop] and i > 0]
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


def frame_signature(path: Path) -> int:
    """64-bitowy „odcisk” kadru (dHash 9×8 w skali szarości) — do wykrywania prawie identycznych kadrów.

    W procesie (OpenCV) — uruchamianie ffmpeg dla każdej klatki kosztowało na Windows sekundy na klatkę."""
    try:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)   # polskie ścieżki
        if img is not None:
            raw = cv2.resize(img, (9, 8), interpolation=cv2.INTER_AREA).tobytes()
            bits = 0
            for row in range(8):
                for col in range(8):
                    bits = (bits << 1) | (raw[row * 9 + col] > raw[row * 9 + col + 1])
            return bits
    except ImportError:
        pass
    raw = run([find_tool("ffmpeg"), "-v", "error", "-i", str(path), "-vf", "scale=9:8,format=gray",
               "-f", "rawvideo", "-"]).stdout
    if len(raw) < 72:
        return 0
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (raw[row * 9 + col] > raw[row * 9 + col + 1])
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")
