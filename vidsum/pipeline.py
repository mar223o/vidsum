"""Cały przebieg analizy jednego filmu i zapis wyników (Markdown + JSON + kadry)."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import __version__
from .analysis import FrameInfo, build_beats, build_summary_prompt, ts
from .fetch import resolve
from .llm import ClaudeCode, LLMError, Ollama
from .media import choose_frames, extract_audio, extract_frame, plan_for, probe, scene_scores
from .transcribe import SidecarEngine, Transcript, WhisperEngine

SCHEMA = "vidsum.analysis/1"


@dataclass
class Options:
    out_root: Path = Path("vidsum_wyniki")
    language: str | None = None                # None = wykryj; "pl" / "en"
    whisper_model: str = "small"
    whisper_device: str = "auto"
    whisper_root: str | None = None
    transcript_file: Path | None = None        # gotowe napisy zamiast Whispera
    vision: str = "ollama"                     # "ollama" | "brak"
    vision_model: str = "qwen3-vl:4b-instruct"
    summary: str = "auto"                      # "auto" | "ollama" | "claude" | "brak"
    summary_model: str | None = None           # domyślnie ten sam co vision_model
    ollama_host: str | None = None
    max_frames: int | None = None
    cookies_from_browser: str | None = None
    allow_api_key: bool = False
    extra: dict = field(default_factory=dict)


Log = Callable[[str], None]


def _safe_name(s: str) -> str:
    # zachowuje polskie litery, usuwa tylko znaki zabronione w nazwach plików Windows
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s).strip(" .")
    return s[:80] or "film"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def analyze(inp: str, opt: Options, log: Log = print) -> Path:
    t0 = time.time()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp = opt.out_root / "_pobrane"
    src = resolve(inp, tmp, opt.cookies_from_browser)
    name = _safe_name(src.title or src.path.stem)
    out = opt.out_root / f"{name}_{stamp}"
    (out / "kadry").mkdir(parents=True, exist_ok=True)
    log(f"▶ {src.original}\n  wyniki: {out}")

    info = probe(src.path)
    log(f"  długość {ts(info.duration)}, {info.width}x{info.height}, audio: {'tak' if info.has_audio else 'nie'}")
    gaps: list[str] = []
    timings: dict[str, float] = {}

    # 1) MOWA
    t = time.time()
    if opt.transcript_file:
        tr = SidecarEngine(opt.transcript_file).transcribe(language=opt.language)
    elif not info.has_audio:
        tr = Transcript(None, "brak", [], "Film nie ma ścieżki dźwiękowej.")
        gaps.append("Brak ścieżki dźwiękowej — wszystko pochodzi tylko z obrazu.")
    else:
        log(f"  [1/4] transkrypcja (Whisper {opt.whisper_model})…")
        wav = extract_audio(src.path, out / "_audio.wav")
        try:
            tr = WhisperEngine(opt.whisper_model, opt.whisper_device, download_root=opt.whisper_root
                               ).transcribe(wav, opt.language)
        finally:
            wav.unlink(missing_ok=True)
    if info.has_audio and not tr.segments:
        gaps.append("Nie rozpoznano mowy (cisza, sama muzyka albo inny język).")
    if tr.note and tr.note not in " ".join(gaps):
        gaps.append(tr.note)
    timings["transkrypcja_s"] = round(time.time() - t, 1)
    log(f"        {len(tr.segments)} segmentów, język: {tr.language}")

    # 2) KADRY
    t = time.time()
    log("  [2/4] wykrywanie zmian scen i wybór kadrów…")
    plan = plan_for(info.duration, opt.max_frames)
    sample_fps = 2.0 if info.duration <= 600 else 1.0
    picks = choose_frames(scene_scores(src.path, sample_fps), info.duration, plan)
    frames: list[FrameInfo] = []
    for i, p in enumerate(picks, 1):
        fn = f"kadr_{i:03d}_{ts(p.t).replace(':', '-')}.jpg"
        extract_frame(src.path, p.t, out / "kadry" / fn)
        frames.append(FrameInfo(round(p.t, 2), f"kadry/{fn}", p.reasons, round(p.score, 3), None))
    max_gap = max([b.t - a.t for a, b in zip(frames, frames[1:])] + [info.duration - frames[-1].t if frames else info.duration])
    gaps.append(f"Kadry co najwyżej co {max_gap:.0f} s — krótkie czynności między kadrami mogły zostać pominięte.")
    timings["kadry_s"] = round(time.time() - t, 1)
    log(f"        {len(frames)} kadrów (pokrycie bazowe co {plan.base_interval} s, limit {plan.max_frames})")

    # 3) OBRAZ
    t = time.time()
    vision_engine = None
    if opt.vision == "ollama":
        vision_engine = Ollama(opt.vision_model, opt.ollama_host)
        vision_engine.check()
        log(f"  [3/4] opis kadrów ({opt.vision_model})…")
        failed: list[str] = []
        for i, f in enumerate(frames, 1):
            for attempt in (1, 2):   # Ollama sama podnosi model po awarii — jedna ponowna próba
                try:
                    f.vision = vision_engine.describe_frame(out / f.file, ts(f.t))
                    break
                except LLMError as e:
                    err = e
            if f.vision is None:
                failed.append(ts(f.t))
                log(f"        {i}/{len(frames)} {ts(f.t)} ! błąd: {str(err)[:90]}")
            else:
                log(f"        {i}/{len(frames)} {ts(f.t)} {f.vision.get('scena', '')[:70]}")
        if failed:
            gaps.append(f"Nie udało się opisać kadrów: {', '.join(failed)} — w tych miejscach obraz = brak danych.")
    else:
        gaps.append("Analiza obrazu wyłączona — kadry zapisane, ale bez opisów.")
    timings["obraz_s"] = round(time.time() - t, 1)

    beats = build_beats(frames, tr.segments, info.duration)
    meta = {"tytuł": src.title, "autor": src.uploader, "długość": ts(info.duration),
            "język mowy": tr.language}
    prompt = build_summary_prompt(beats, meta, gaps)
    (out / "prompt_dla_claude.md").write_text(prompt, encoding="utf-8")

    # 4) STRESZCZENIE
    t = time.time()
    summary_md, summary_engine = None, None
    if opt.summary == "auto":
        # Claude (subskrypcja Pro) daje dużo lepsze streszczenia niż mały model lokalny;
        # bierzemy go, jeśli jest zainstalowany i nie grozi płatnym API.
        try:
            ClaudeCode(allow_api_key=opt.allow_api_key).check()
            opt.summary = "claude"
        except LLMError:
            opt.summary = "ollama"
    if opt.summary != "brak":
        log(f"  [4/4] streszczenie ({opt.summary})…")
        if vision_engine:
            # zwolnij model obrazu: streszczenie ładuje model z innym kontekstem,
            # a dwie kopie naraz nie mieszczą się w 8 GB
            vision_engine.unload()
        try:
            if opt.summary == "claude":
                eng = ClaudeCode(allow_api_key=opt.allow_api_key)
                summary_engine = "claude-code"
            else:
                eng = Ollama(opt.summary_model or opt.vision_model, opt.ollama_host)
                summary_engine = f"ollama:{eng.model}"
            summary_md = eng.complete(prompt)
        except LLMError as e:
            gaps.append(f"Streszczenie nie powstało: {e}")
            log(f"        ! {e}")
    if vision_engine:
        vision_engine.unload()
    timings["streszczenie_s"] = round(time.time() - t, 1)
    timings["razem_s"] = round(time.time() - t0, 1)

    result = {
        "schema": SCHEMA,
        "narzedzie": {"nazwa": "VidSum", "wersja": __version__},
        "utworzono": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "zrodlo": {"rodzaj": src.kind, "wejscie": src.original, "url": src.webpage_url,
                   "tytul": src.title, "autor": src.uploader, "plik": src.path.name,
                   "sha256": _sha256(src.path), "dlugosc_s": round(info.duration, 2),
                   "szerokosc": info.width, "wysokosc": info.height, "audio": info.has_audio},
        "ustawienia": {"whisper": tr.engine, "jezyk": opt.language or "auto",
                       "obraz": f"ollama:{opt.vision_model}" if vision_engine else "brak",
                       "streszczenie": summary_engine or "brak", "limit_kadrow": plan.max_frames,
                       "pokrycie_co_s": plan.base_interval},
        "transkrypcja": {"jezyk": tr.language, "segmenty": [asdict(s) for s in tr.segments]},
        "kadry": [asdict(f) for f in frames],
        "os_czasu": beats,
        "streszczenie": {"silnik": summary_engine, "markdown": summary_md} if summary_md else None,
        "luki": gaps,
        "czasy": timings,
    }
    (out / "analiza.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "transkrypcja.srt").write_text(_srt(tr), encoding="utf-8")
    (out / "raport.md").write_text(_report_md(result), encoding="utf-8")
    log(f"  ✔ gotowe w {timings['razem_s']} s")
    return out


def _srt(tr: Transcript) -> str:
    def f(t: float) -> str:
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"
    return "\n".join(f"{i}\n{f(s.start)} --> {f(s.end)}\n{s.text}\n" for i, s in enumerate(tr.segments, 1))


def _report_md(r: dict) -> str:
    z = r["zrodlo"]
    L = [f"# {z['tytul'] or z['plik']}", "",
         f"- Źródło: {z['url'] or z['wejscie']}",
         f"- Długość: {ts(z['dlugosc_s'])} · obraz {z['szerokosc']}×{z['wysokosc']} · audio: {'tak' if z['audio'] else 'nie'}",
         f"- Silniki: mowa `{r['ustawienia']['whisper']}`, obraz `{r['ustawienia']['obraz']}`, "
         f"streszczenie `{r['ustawienia']['streszczenie']}`", ""]
    if r["streszczenie"]:
        L += [r["streszczenie"]["markdown"], ""]
    else:
        L += ["## Streszczenie", "", "_Brak — wklej `prompt_dla_claude.md` do Claude albo uruchom z `--streszczenie`._", ""]
    L += ["## Ograniczenia analizy", ""] + [f"- {g}" for g in r["luki"]] + [""]
    L += ["## Oś czasu (mowa + obraz)", ""]
    for b in r["os_czasu"]:
        w = b["widac"]
        seen = w.get("scena") or "brak danych"
        extra = []
        for k in ("czynnosci", "obiekty", "tekst_na_ekranie"):
            if w.get(k):
                extra.append(f"{k.replace('_', ' ')}: {', '.join(w[k])}")
        if w.get("cialo"):
            extra.append(f"ciało: {w['cialo']}")
        L.append(f"### {ts(b['start'])}–{ts(b['end'])}")
        L.append(f"![kadr]({b['kadr']})  ")
        L.append(f"**Obraz** _(z obrazu, pewność: {w.get('pewnosc', '—')})_: {seen}" + (f" — {'; '.join(extra)}" if extra else ""))
        L.append(f"**Mowa** _(z mowy)_: {b['slychac']['tekst'] or 'brak danych'}")
        L.append("")
    L += ["## Pełna transkrypcja", ""]
    L += [f"`{ts(s['start'])}` {s['text']}" + "  " for s in r["transkrypcja"]["segmenty"]] or ["brak danych"]
    return "\n".join(L) + "\n"
