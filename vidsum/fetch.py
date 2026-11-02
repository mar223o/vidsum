"""Wejście: plik lokalny albo link (YouTube / Instagram / TikTok / inne) przez yt-dlp."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .tools import find_tool

_URL = re.compile(r"^https?://", re.I)


@dataclass
class Source:
    kind: str            # "plik" | "link"
    original: str        # ścieżka albo URL podany przez użytkownika
    path: Path           # lokalny plik do analizy
    title: str | None = None
    uploader: str | None = None
    webpage_url: str | None = None


def is_url(s: str) -> bool:
    return bool(_URL.match(s.strip()))


def resolve(inp: str, workdir: Path, cookies_from_browser: str | None = None) -> Source:
    if not is_url(inp):
        p = Path(inp).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"Nie ma takiego pliku: {p}")
        return Source("plik", inp, p.resolve())
    return download(inp, workdir, cookies_from_browser)


def download(url: str, workdir: Path, cookies_from_browser: str | None = None) -> Source:
    import yt_dlp  # import leniwy — nie potrzebny przy plikach lokalnych

    workdir.mkdir(parents=True, exist_ok=True)
    opts = {
        # nazwa pliku z ID (bez tytułu) — brak problemów ze znakami w nazwach
        "outtmpl": str(workdir / "pobrane_%(id)s.%(ext)s"),
        # do 720p wystarcza do rozpoznania czynności, a jest kilka razy mniejsze
        "format": "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ffmpeg_location": str(Path(find_tool("ffmpeg")).parent),
    }
    if cookies_from_browser:
        # Instagram/TikTok często wymagają zalogowania: np. "chrome", "edge", "firefox"
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info.get("_type") == "playlist" and info.get("entries"):
            info = info["entries"][0]
        files = [Path(d["filepath"]) for d in info.get("requested_downloads", []) if d.get("filepath")]
        path = files[0] if files else Path(ydl.prepare_filename(info))
    if not path.is_file():
        raise RuntimeError("yt-dlp nie zwrócił pobranego pliku.")
    return Source("link", url, path.resolve(), info.get("title"), info.get("uploader"),
                  info.get("webpage_url") or url)
