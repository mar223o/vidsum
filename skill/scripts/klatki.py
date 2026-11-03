#!/usr/bin/env python3
"""Kadry do obejrzenia przez Claude: zmiany scen + równomierne pokrycie, złożone w arkusze 3×3 z czasem na każdym kadrze.

Użycie: python klatki.py FILM.mp4 FOLDER_WYJŚCIOWY [--max 36]
Wynik: FOLDER/arkusz_01.jpg … (po 9 kadrów, czas mm:ss w rogu), FOLDER/kadry.json, FOLDER/audio.wav
Wymaga tylko ffmpeg/ffprobe.
"""
import json
import re
import subprocess
import sys
from pathlib import Path


def sh(*a, text=True):
    return subprocess.run(a, check=True, capture_output=True, text=text)


def duration(video):
    out = sh("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video).stdout
    return float(out.strip() or 0)


def scene_times(video, thr=0.22):
    err = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-i", video, "-an", "-vf",
                          f"fps=2,scale=320:-2,select='gt(scene,{thr})',showinfo", "-f", "null", "-"],
                         capture_output=True, text=True, errors="replace").stderr
    return [float(x) for x in re.findall(r"pts_time:([0-9.]+)", err)]


def main(video, out, max_frames=36):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    dur = duration(video)
    base = max(1.5, dur / max(1, max_frames * 0.6))
    cand = {round(min(dur - 0.1, t + 0.5), 1) for t in scene_times(video)}         # chwilę po cięciu
    t = 0.3
    while t < dur - 0.3:
        cand.add(round(t, 1))
        t += base
    times = []
    for x in sorted(cand):                                                       # min. 1 s odstępu
        if not times or x - times[-1] >= 1.0:
            times.append(x)
    if len(times) > max_frames:                                                  # równomierne przerzedzenie
        step = len(times) / max_frames
        times = [times[int(i * step)] for i in range(max_frames)]
    frames = []
    for i, x in enumerate(times):
        f = out / f"k_{i:03d}.jpg"
        mm = f"{int(x // 60):02d}\\:{int(x % 60):02d}"
        sh("ffmpeg", "-y", "-v", "error", "-ss", f"{x:.2f}", "-i", video, "-frames:v", "1", "-vf",
           f"scale=480:-2,drawtext=text='{mm}':x=8:y=8:fontsize=26:fontcolor=white:box=1:boxcolor=black@0.7:boxborderw=6",
           str(f))
        frames.append({"t": x, "plik": f.name})
    sheets = []
    for s in range(0, len(frames), 9):
        chunk = frames[s:s + 9]
        sheet = out / f"arkusz_{s // 9 + 1:02d}.jpg"
        inputs = [a for c in chunk for a in ("-i", str(out / c["plik"]))]
        n = len(chunk)
        h = int(sh("ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=height",
                   "-of", "csv=p=0", str(out / chunk[0]["plik"])).stdout.strip() or 270)
        if n == 1:
            sh("ffmpeg", "-y", "-v", "error", "-i", str(out / chunk[0]["plik"]), str(sheet))
        else:
            # kadry w siatce 3 kolumny (xstack); wszystkie przeskalowane do 480×h
            scale = "".join(f"[{i}]scale=480:{h}[s{i}];" for i in range(n))
            layout = "|".join(f"{(i % 3) * 480}_{(i // 3) * h}" for i in range(n))
            sh("ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex",
               scale + "".join(f"[s{i}]" for i in range(n)) + f"xstack=inputs={n}:layout={layout}:fill=black",
               "-q:v", "3", str(sheet))
        sheets.append({"arkusz": sheet.name, "od": chunk[0]["t"], "do": chunk[-1]["t"]})
    has_audio = "audio" in sh("ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", video).stdout
    if has_audio:
        sh("ffmpeg", "-y", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", "16000", str(out / "audio.wav"))
    (out / "kadry.json").write_text(json.dumps({"dlugosc_s": round(dur, 2), "audio": has_audio, "kadry": frames,
                                                "arkusze": sheets}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"dlugosc_s": round(dur, 2), "audio": has_audio, "kadrow": len(frames), "arkusze": [s["arkusz"] for s in sheets]}))


if __name__ == "__main__":
    a = sys.argv[1:]
    mx = int(a[a.index("--max") + 1]) if "--max" in a else 36
    main(a[0], a[1], mx)
