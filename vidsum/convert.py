"""Tryb „Konwersja” (0.14.0): film albo piosenka z linku (YouTube, Instagram, TikTok, …) albo z pliku → MP4 albo MP3.

Bez modeli — tylko yt-dlp (pobieranie) i ffmpeg (konwersja), więc działa także bez Ollamy i karty graficznej.

MP4 (film):
- z linku pobieramy od razu wersję H.264 + AAC (tak YouTube podaje filmy do 1080p), więc zwykle wystarczy złożyć
  obraz z dźwiękiem bez przekodowania — szybko i bez utraty jakości;
- gdy obraz jest w innym kodeku (VP9, AV1 — np. 4K), przekodowujemy do H.264 pierwszym dostępnym koderem w ffmpeg
  (libx264, libopenh264, h264_mf z Windows, sprzętowe NVENC / Quick Sync / AMF). Taki MP4 odtworzy każdy odtwarzacz;
- dźwięk spoza MP4 (np. Opus) → AAC 192 kb/s.
MP3 (dźwięk): libmp3lame, VBR jakość 2 (ok. 190 kb/s), z tytułem i autorem w tagach.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

from .fetch import is_url
from .tools import ToolError, find_tool, run

FORMATS = ("mp4", "mp3")
H264_ENCODERS = ("libx264", "libopenh264", "h264_mf", "h264_nvenc", "h264_qsv", "h264_amf")
MP4_AUDIO = {"aac", "mp3", "alac"}
MP4_VIDEO_PASS = {"hevc", "av1", "vp9"}          # mieszczą się w MP4, gdy nie ma czym przekodować (gorsza zgodność)
# z YouTube: H.264 + AAC do 1080p (bez przekodowania), potem cokolwiek do 1080p, na końcu cokolwiek
FMT_MP4 = ("bv*[vcodec^=avc1][height<=1080]+ba[acodec^=mp4a]/b[vcodec^=avc1][acodec^=mp4a]"
           "/bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b")
FMT_MP3 = "ba/b"
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class ConvertError(RuntimeError):
    pass


_enc_cache: dict[str, set[str]] = {}


def encoders() -> set[str]:
    """Kodery w tym ffmpeg (różne kompilacje mają różne — np. LGPL bez libx264)."""
    ff = find_tool("ffmpeg")
    if ff not in _enc_cache:
        out = run([ff, "-hide_banner", "-encoders"], check=False).stdout_text  # type: ignore[attr-defined]
        _enc_cache[ff] = {m.group(1) for m in re.finditer(r"^\s*[VAS][.\w]{5}\s+(\S+)", out, re.M)}
    return _enc_cache[ff]


def pick_h264(encs: set[str]) -> str | None:
    return next((e for e in H264_ENCODERS if e in encs), None)


def safe_name(title: str | None, fallback: str = "plik") -> str:
    """Nazwa pliku z tytułu: bez znaków zakazanych w Windows, bez kropek/spacji na końcu, najwyżej 120 znaków."""
    s = _ILLEGAL.sub(" ", str(title or "")).strip()
    s = re.sub(r"\s+", " ", s)[:120].rstrip(" .")
    if s.upper().split(".")[0] in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                                   *(f"LPT{i}" for i in range(1, 10))}:
        s = "_" + s
    return s or fallback


def unique(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(2, 1000):
        p = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not p.exists():
            return p
    raise ConvertError("Za dużo plików o tej samej nazwie.")


def streams(path: Path) -> dict:
    """Kodek obrazu i dźwięku oraz długość (ffprobe). Okładka w mp3/m4a to nie obraz filmu."""
    out = run([find_tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
               str(path)]).stdout_text  # type: ignore[attr-defined]
    d = json.loads(out or "{}")
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    try:
        dur = float((d.get("format") or {}).get("duration") or 0)
    except ValueError:
        dur = 0.0
    return {"video": v.get("codec_name") if v else None, "audio": a.get("codec_name") if a else None,
            "duration": dur, "tags": (d.get("format") or {}).get("tags") or {}}


_ENC_OPTS = {"libx264": ["-preset", "veryfast", "-crf", "20"], "libopenh264": ["-b:v", "8M"], "h264_mf": ["-b:v", "8M"],
             "h264_nvenc": ["-cq", "21", "-b:v", "0"], "h264_qsv": ["-global_quality", "21"],
             "h264_amf": ["-qp_i", "20", "-qp_p", "22"]}


def mp4_plans(info: dict, encs: set[str]) -> list[tuple[list[str], str]]:
    """Kolejne sposoby zapisu MP4 (argumenty ffmpeg, opis) — od najlepszego. Koder sprzętowy albo Windowsowy może być
    w ffmpeg, a mimo to nie działać na danym komputerze (brak karty, brak Media Foundation), więc konwersja próbuje po
    kolei, a na końcu — gdy kodek się mieści w MP4 — zapisuje obraz bez przekodowania."""
    v, a = info["video"], info["audio"]
    if not v:
        raise ConvertError("Ten plik nie ma obrazu — wybierz MP3.")
    base = ["-map", "0:v:0"] + (["-map", "0:a:0"] if a else [])
    aud = ([] if not a else ["-c:a", "copy"] if a in MP4_AUDIO else ["-c:a", "aac", "-b:a", "192k"])
    tail = aud + ["-movflags", "+faststart"]
    if v == "h264":
        return [(base + ["-c:v", "copy"] + tail, "bez przekodowania obrazu")]
    plans = [(base + ["-c:v", e, "-pix_fmt", "yuv420p", *_ENC_OPTS.get(e, [])] + tail,
              f"przekodowanie obrazu {v} → H.264 ({e})") for e in H264_ENCODERS if e in encs]
    if v in MP4_VIDEO_PASS:
        plans.append((base + ["-c:v", "copy"] + tail,
                      f"obraz {v} bez przekodowania (brak działającego kodera H.264 — starsze odtwarzacze mogą go nie otworzyć)"))
    if not plans:
        raise ConvertError(f"Obrazu {v} nie da się zapisać w MP4, a ten ffmpeg nie ma kodera H.264.")
    return plans


def mp4_args(info: dict, encs: set[str]) -> tuple[list[str], str]:
    return mp4_plans(info, encs)[0]


def mp3_args(info: dict, encs: set[str], title: str | None, artist: str | None) -> list[str]:
    if not info["audio"]:
        raise ConvertError("Ten plik nie ma dźwięku.")
    if "libmp3lame" not in encs:
        raise ConvertError("Ten ffmpeg nie ma kodera MP3 (libmp3lame).")
    meta = []
    if title:
        meta += ["-metadata", f"title={title}"]
    if artist:
        meta += ["-metadata", f"artist={artist}"]
    return ["-map", "0:a:0", "-vn", "-c:a", "libmp3lame", "-q:a", "2", "-id3v2_version", "3", *meta]


def ffmpeg(src: Path, dst: Path, args: list[str], duration: float, on_frac=None) -> None:
    """ffmpeg z postępem (-progress): on_frac(0–1) w trakcie. Błąd → ConvertError z końcówką komunikatu."""
    from . import procs
    if procs.closing.is_set():
        raise ToolError("Program się zamyka — nie uruchamiam nowych procesów.")
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-i", str(src), *args,
           "-progress", "pipe:1", "-nostats", str(dst)]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    procs.register(p)
    err: list[bytes] = []
    t = threading.Thread(target=lambda: err.append(p.stderr.read()), daemon=True)   # stderr osobno — bez blokady
    t.start()
    try:
        for raw in p.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("out_time_us=") and duration > 0 and on_frac:
                try:
                    on_frac(max(0.0, min(1.0, int(line.split("=", 1)[1]) / 1e6 / duration)))
                except ValueError:
                    pass
        p.wait()
    finally:
        procs.unregister(p)
        t.join(5)
    if p.returncode != 0:
        dst.unlink(missing_ok=True)
        tail = b"".join(err).decode("utf-8", "replace").strip().splitlines()[-4:]
        raise ConvertError("ffmpeg: " + " | ".join(tail))


def download(url: str, fmt: str, workdir: Path, cookies_from_browser: str | None = None, on_frac=None) -> tuple[Path, dict]:
    import yt_dlp
    workdir.mkdir(parents=True, exist_ok=True)
    state = {"files": 0}

    def hook(d):
        if d.get("status") == "downloading" and on_frac:
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                on_frac(min(1.0, d.get("downloaded_bytes", 0) / total), state["files"])
        elif d.get("status") == "finished":
            state["files"] += 1
    opts = {"outtmpl": str(workdir / "pobrane_%(id)s.%(ext)s"), "format": FMT_MP4 if fmt == "mp4" else FMT_MP3,
            "noplaylist": True, "quiet": True, "no_warnings": True, "progress_hooks": [hook],
            "ffmpeg_location": str(Path(find_tool("ffmpeg")).parent)}
    if fmt == "mp4":
        opts["merge_output_format"] = "mp4"
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info.get("_type") == "playlist" and info.get("entries"):
            info = info["entries"][0]
        files = [Path(d["filepath"]) for d in info.get("requested_downloads", []) if d.get("filepath")]
        path = files[0] if files else Path(ydl.prepare_filename(info))
    if not path.is_file():
        raise ConvertError("yt-dlp nie zwrócił pobranego pliku.")
    return path, {"title": info.get("title"), "artist": info.get("artist") or info.get("uploader") or info.get("channel")}


def convert(inp: str, fmt: str, out_dir: Path, cookies_from_browser: str | None = None, log=print,
            progress=None) -> Path:
    """Link albo plik → `out_dir/<tytuł>.mp4|mp3`. progress(etap, ułamek): etap „pobieranie” (tylko link) i „konwersja”."""
    if fmt not in FORMATS:
        raise ConvertError(f"Nieznany format: {fmt}")
    progress = progress or (lambda stage, frac: None)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f".vidsumly_tmp_{os.getpid()}_{threading.get_ident()}"
    try:
        if is_url(inp):
            log(f"▶ {inp}")
            log(f"  pobieranie ({fmt.upper()})…")
            n_parts = 2 if fmt == "mp4" else 1           # MP4 z YouTube: osobno obraz i dźwięk

            def dl(frac, done_files):
                progress("pobieranie", min(1.0, (min(done_files, n_parts - 1) + frac) / n_parts))
            src, meta = download(inp.strip(), fmt, tmp, cookies_from_browser, dl)
            progress("pobieranie", 1.0)
        else:
            src = Path(inp.strip().strip('"')).expanduser()
            if not src.is_file():
                raise ConvertError(f"Nie ma takiego pliku: {src}")
            log(f"▶ {src.name}")
            meta = {"title": src.stem, "artist": None}
        info = streams(src)
        meta["title"] = meta.get("title") or info["tags"].get("title") or src.stem
        meta["artist"] = meta.get("artist") or info["tags"].get("artist")
        dst = unique(out_dir / f"{safe_name(meta['title'])}.{fmt}")
        encs = encoders()
        plans = mp4_plans(info, encs) if fmt == "mp4" else \
            [(mp3_args(info, encs, meta["title"], meta["artist"]), "MP3 (VBR, jakość 2)")]
        part = dst.with_name(dst.stem + ".part" + dst.suffix)
        for i, (args, how) in enumerate(plans):
            log(f"  konwersja: {how}")
            progress("konwersja", 0.0)
            try:
                ffmpeg(src, part, args, info["duration"], lambda f: progress("konwersja", f))
                break
            except ConvertError as e:
                if i == len(plans) - 1:
                    raise
                log(f"  ✖ {e} — próbuję inaczej")
        os.replace(part, dst)
        progress("konwersja", 1.0)
        log(f"  zapisano: {dst}")
        return dst
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
