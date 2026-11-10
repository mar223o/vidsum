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
    subtitles: Path | None = None      # napisy z serwisu (od autora albo automatyczne)
    subtitles_kind: str | None = None  # "autor" | "automatyczne"
    description: str | None = None     # opis od autora (YouTube itd.) — tekst autora, nie analiza
    chapters: list | None = None       # rozdziały od autora: [{"start", "end", "tytul"}]


def is_url(s: str) -> bool:
    return bool(_URL.match(s.strip()))


def resolve(inp: str, workdir: Path, cookies_from_browser: str | None = None) -> Source:
    if not is_url(inp):
        p = Path(inp).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"Nie ma takiego pliku: {p}")
        return Source("plik", inp, p.resolve())
    return download(inp, workdir, cookies_from_browser)


def download(url: str, workdir: Path, cookies_from_browser: str | None = None, subtitles: bool = True) -> Source:
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
    # napisy wybieramy dopiero po odczytaniu informacji o filmie (język oryginału), zob. choose_subtitle_lang
    if cookies_from_browser:
        # Instagram/TikTok często wymagają zalogowania: np. "chrome", "edge", "firefox"
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get("_type") == "playlist" and info.get("entries"):
                info = info["entries"][0]
            choice = choose_subtitle_lang(info) if subtitles else None
            if choice:
                # tylko napisy w JĘZYKU ORYGINAŁU (od autora albo automatyczne rozpoznanie mowy) — nigdy tłumaczenia
                ydl.params.update({"writesubtitles": True, "writeautomaticsub": True, "subtitlesformat": "vtt",
                                   "subtitleslangs": [choice[0]]})
            info = ydl.process_ie_result(info, download=True)
            files = [Path(d["filepath"]) for d in info.get("requested_downloads", []) if d.get("filepath")]
            path = files[0] if files else Path(ydl.prepare_filename(info))
    except Exception as e:
        if subtitles and "subtitle" in str(e).lower():   # np. HTTP 429 przy napisach — pobierz bez nich
            return download(url, workdir, cookies_from_browser, subtitles=False)
        raise
    if not path.is_file():
        raise RuntimeError("yt-dlp nie zwrócił pobranego pliku.")
    sub, kind = pick_subtitles(info)
    return Source("link", url, path.resolve(), info.get("title"), info.get("uploader"),
                  info.get("webpage_url") or url, sub, kind, (info.get("description") or "").strip()[:5000] or None,
                  author_chapters(info))


def author_chapters(info: dict) -> list | None:
    """Rozdziały, które autor sam podał (YouTube „chapters”) — dokładne, więc pokazywane osobno od rozdziałów modelu."""
    out = []
    for c in info.get("chapters") or []:
        try:
            out.append({"start": round(float(c["start_time"]), 1), "end": round(float(c["end_time"]), 1),
                        "tytul": str(c.get("title") or "").strip()[:200]})
        except (KeyError, TypeError, ValueError):
            continue
    return out or None


def fetch_comments(url: str, limit: int = 40, cookies_from_browser: str | None = None) -> list[dict]:
    """Komentarze widzów (na żądanie, tylko linki): najpopularniejsze, bez pobierania filmu.
    Zwraca [{"autor", "tekst", "polubienia", "odpowiedz"}] — tekst widzów, nie fakty o filmie."""
    import yt_dlp
    opts = {"skip_download": True, "getcomments": True, "quiet": True, "no_warnings": True,
            "extractor_args": {"youtube": {"max_comments": [str(limit), "all", "0"], "comment_sort": ["top"]}}}
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return parse_comments(info.get("comments") or [], limit)


def parse_comments(raw: list[dict], limit: int = 40) -> list[dict]:
    out = []
    for c in raw:
        text = str(c.get("text") or "").strip()
        if not text:
            continue
        out.append({"autor": str(c.get("author") or "").strip(), "tekst": text[:1500],
                    "polubienia": int(c.get("like_count") or 0), "odpowiedz": c.get("parent") not in (None, "root")})
    out.sort(key=lambda x: (x["odpowiedz"], -x["polubienia"]))
    return out[:limit]


def choose_subtitle_lang(info: dict) -> tuple[str, str] | None:
    """Który język napisów pobrać: (kod, "autor"|"automatyczne") albo None (wtedy Whisper).

    Transkrypcja ma być ZAWSZE w języku oryginału. Napisy od autora w innym języku i automatyczne
    tłumaczenia YouTube (np. „pl” dla filmu po angielsku) to przekłady — tych nie bierzemy.
    """
    manual = set((info.get("subtitles") or {}).keys()) - {"live_chat"}
    auto = set((info.get("automatic_captions") or {}).keys())
    orig = (info.get("language") or "").strip()
    ob = orig.split("-")[0].lower()
    if orig:
        for cand in (orig, ob):
            if cand in manual:
                return cand, "autor"
        for cand in (f"{orig}-orig", f"{ob}-orig"):
            if cand in auto:
                return cand, "automatyczne"
    origs = sorted(a for a in auto if a.endswith("-orig"))   # „-orig” = rozpoznanie mowy w języku filmu
    if len(origs) == 1:
        return origs[0], "automatyczne"
    if ob and ob in auto:
        return ob, "automatyczne"
    return None


def pick_subtitles(info: dict) -> tuple[Path | None, str | None]:
    """Pobrany plik napisów i jego rodzaj (po choose_subtitle_lang pobierany jest najwyżej jeden)."""
    req = info.get("requested_subtitles") or {}
    have = {lang: Path(d["filepath"]) for lang, d in req.items() if d.get("filepath") and Path(d["filepath"]).is_file()}
    choice = choose_subtitle_lang(info)
    if not choice or choice[0] not in have:
        return None, None
    return have[choice[0]], choice[1]
