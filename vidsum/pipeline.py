"""Cały przebieg analizy jednego filmu i zapis wyników (Markdown + JSON + kadry)."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import __version__
from .analysis import FrameInfo, build_beats, build_summary_prompt, ts
from .summary import build_json_prompt, parse_summary, to_markdown
from .fetch import resolve
from .llm import ClaudeCode, LLMError, Ollama
from .media import (choose_frames, extract_audio, extract_frame, frame_signature, hamming, plan_for, probe,
                    scene_scores)
from .transcribe import SidecarEngine, Transcript, WhisperEngine

SCHEMA = "vidsum.analysis/1"


@dataclass
class Options:
    out_root: Path = Path("vidsum_wyniki")
    language: str | None = None                # None = wykryj; "pl" / "en"
    whisper_model: str = "large-v3-turbo"     # pomiar: PL 5,5% WER (small: 12,3%)
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
    prefer_subtitles: bool = True              # napisy z YouTube zamiast Whispera, jeśli są
    ocr: bool = True                           # gęsty OCR napisów na ekranie (+ podpowiedzi słów dla Whispera)
    move_source: bool = False                  # przenieś plik źródłowy do folderu wyników (wysłane z UI)
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
    t_fetch = round(time.time() - t0, 1)
    name = _safe_name(src.title or src.path.stem)
    out = opt.out_root / f"{name}_{stamp}"
    (out / "kadry").mkdir(parents=True, exist_ok=True)
    log(f"▶ {src.original}\n  wyniki: {out}")

    info = probe(src.path)
    log(f"  długość {ts(info.duration)}, {info.width}x{info.height}, audio: {'tak' if info.has_audio else 'nie'}")
    gaps: list[str] = []
    timings: dict[str, float] = {"pobieranie_s": t_fetch} if src.kind == "link" else {}

    # 0) NAPISY NA EKRANIE (OCR) — przed Whisperem, bo dają mu podpowiedzi słów
    ocr_lines: list = []
    pre_notes: list[str] = []
    if opt.ocr:
        t = time.time()
        log("  [0/4] napisy na ekranie (OCR)…")
        try:
            from .ocr import ensure_models, read_captions
            mdir = ensure_models(Path(opt.whisper_root) if opt.whisper_root else out.parent / "_modele", log)
            ocr_lines = read_captions(src.path, info.duration, mdir, log)
        except Exception as e:     # OCR to dodatek — jego awaria nie zatrzymuje analizy
            pre_notes.append(f"OCR napisów niedostępny ({type(e).__name__}: {str(e)[:100]}).")
            log(f"        ! OCR: {e}")
        timings["ocr_s"] = round(time.time() - t, 1)

    # 1) MOWA — napisy z serwisu (najszybciej), gotowy plik albo Whisper.
    #    Whisper na CPU działa RÓWNOLEGLE z opisem kadrów na GPU (to największy zysk czasu).
    t_speech = time.time()
    tr_box: dict = {}
    speech_thread = None
    speech_job = None
    if opt.transcript_file:
        tr_box["tr"] = SidecarEngine(opt.transcript_file).transcribe(language=opt.language)
    elif not info.has_audio:
        tr_box["tr"] = Transcript(None, "brak", [])
        gaps.append("Brak ścieżki dźwiękowej — wszystko pochodzi tylko z obrazu.")
    elif src.subtitles and opt.prefer_subtitles:
        tr = SidecarEngine(src.subtitles).transcribe(language=opt.language)
        tr.engine = f"napisy serwisu ({src.subtitles_kind})"
        sfx = src.subtitles.suffixes            # np. pobrane_ID.en-orig.vtt → "en"
        if not tr.language and len(sfx) > 1:
            tr.language = sfx[-2].strip(".").split("-")[0]
        tr_box["tr"] = tr
        log(f"  [1/4] mowa z napisów serwisu ({src.subtitles_kind}) — bez Whispera")
    else:
        wav = extract_audio(src.path, out / "_audio.wav")
        # podpowiedzi słów tylko dla dużych modeli — małym szkodzą (pomiar: small WER 13–52%)
        small_model = any(x in Path(opt.whisper_model).name.lower() for x in ("tiny", "base", "small"))
        hot = None
        if ocr_lines and not small_model:
            from .ocr import hotwords
            hot = hotwords(ocr_lines, src.title)
        engine = WhisperEngine(opt.whisper_model, opt.whisper_device, download_root=opt.whisper_root, hotwords=hot)
        engine.coverage_hints = [(l.start, l.end) for l in ocr_lines]
        device, _ = engine.resolve_device()
        log(f"  [1/4] transkrypcja (Whisper {opt.whisper_model}, {device}; za pierwszym razem pobieranie modelu)…")

        def run_whisper() -> None:
            try:
                tr_box["tr"] = engine.transcribe(wav, opt.language)
                if engine.recovered:
                    tr_box["tr"].note = ((tr_box["tr"].note + " ") if tr_box["tr"].note else "") + \
                        f"Odzyskano {engine.recovered} zdań pominiętych przez Whispera (drugi przebieg bez podpowiedzi)."
            except Exception as e:   # błąd mowy nie może zatrzymać analizy obrazu
                tr_box["err"] = e
            finally:
                wav.unlink(missing_ok=True)
                tr_box["s"] = round(time.time() - tr_box.get("t0", t_speech), 1)

        if device == "cpu" and opt.vision == "ollama":
            # start dopiero PO wycięciu kadrów: ffmpeg i Whisper na CPU naraz spowalniały się nawzajem
            # (na komputerze testowym kadry 96 s zamiast kilku); opis kadrów idzie na GPU, więc tam nakładanie się opłaca
            speech_job = run_whisper
        else:                       # Whisper na GPU: po kolei, bo 8 GB VRAM nie zmieści obu modeli
            run_whisper()

    # 2) KADRY
    t = time.time()
    log("  [2/4] wykrywanie zmian scen i wybór kadrów…")
    plan = plan_for(info.duration, opt.max_frames)
    sample_fps = 2.0 if info.duration <= 600 else 1.0
    picks = choose_frames(scene_scores(src.path, sample_fps), info.duration, plan)
    frames: list[FrameInfo] = []
    prev_sig = None
    dropped = 0
    for p in picks:
        fn = f"kadr_{len(frames) + 1:03d}_{ts(p.t).replace(':', '-')}.jpg"
        path = extract_frame(src.path, p.t, out / "kadry" / fn, width=512)
        sig = frame_signature(path)
        # prawie identyczny jak poprzedni kadr (statyczne ujęcie) — bez opisu, oszczędza czas modelu
        if prev_sig is not None and "zmiana_sceny" not in p.reasons and hamming(sig, prev_sig) <= 5:
            path.unlink(missing_ok=True)
            dropped += 1
            continue
        prev_sig = sig
        frames.append(FrameInfo(round(p.t, 2), f"kadry/{fn}", p.reasons, round(p.score, 3), None))
    max_gap = max([b.t - a.t for a, b in zip(frames, frames[1:])] + [info.duration - frames[-1].t if frames else info.duration])
    gaps.append(f"Kadry co najwyżej co {max_gap:.0f} s — krótkie czynności między kadrami mogły zostać pominięte.")
    timings["kadry_s"] = round(time.time() - t, 1)
    log(f"        {len(frames)} kadrów (pominięto {dropped} powtarzających się; limit {plan.max_frames})")
    if speech_job:
        tr_box["t0"] = time.time()
        speech_thread = threading.Thread(target=speech_job, daemon=True)
        speech_thread.start()

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

    if speech_thread:
        log("        czekam na transkrypcję…")
        speech_thread.join()
    if "err" in tr_box:
        raise tr_box["err"]
    tr = tr_box["tr"]
    timings["transkrypcja_s"] = tr_box.get("s", round(time.time() - t_speech, 1))
    if info.has_audio and not tr.segments:
        gaps.append("Nie rozpoznano mowy — film może mieć muzykę lub inne dźwięki, ale nikt nie mówi "
                    "(albo mowa jest niewyraźna / w innym języku).")
    tech_notes = pre_notes + ([tr.note] if tr.note else [])   # sprawy techniczne (np. Whisper na CPU) — nie luki w analizie
    log(f"        mowa: {len(tr.segments)} segmentów, język: {tr.language} ({tr.engine})")

    beats = build_beats(frames, tr.segments, info.duration, ocr_lines)
    meta = {"tytuł": src.title, "autor": src.uploader, "długość": ts(info.duration),
            "język mowy": tr.language}
    prompt = build_summary_prompt(beats, meta, gaps)             # wersja do wklejenia na claude.ai
    (out / "prompt_dla_claude.md").write_text(prompt, encoding="utf-8")
    json_prompt = build_json_prompt(beats, meta, gaps)           # wersja dla programu (dane do widoku)

    # 4) STRESZCZENIE
    t = time.time()
    summary_md, summary_engine, summary_data = None, None, None
    summary_mode = opt.summary
    if summary_mode == "auto":
        # Claude (subskrypcja Pro) daje dużo lepsze streszczenia niż mały model lokalny;
        # bierzemy go, jeśli jest zainstalowany i nie grozi płatnym API.
        try:
            ClaudeCode(allow_api_key=opt.allow_api_key).check()
            summary_mode = "claude"
        except LLMError:
            summary_mode = "ollama"
    if summary_mode != "brak":
        log(f"  [4/4] streszczenie ({summary_mode})…")
        if vision_engine:
            # zwolnij model obrazu: streszczenie ładuje model z innym kontekstem,
            # a dwie kopie naraz nie mieszczą się w 8 GB
            vision_engine.unload()
        try:
            if summary_mode == "claude":
                eng = ClaudeCode(allow_api_key=opt.allow_api_key)
                summary_engine = "claude-code"
            else:
                eng = Ollama(opt.summary_model or opt.vision_model, opt.ollama_host)
                summary_engine = f"ollama:{eng.model}"
            raw = eng.complete(json_prompt, as_json=True)
            summary_data = parse_summary(raw, info.duration)
            summary_md = to_markdown(summary_data) if summary_data else raw
            if not summary_data:
                log("        ! model nie zwrócił poprawnych danych — zapisuję tekst")
        except LLMError as e:
            gaps.append(f"Streszczenie nie powstało: {e}")
            log(f"        ! {e}")
    if vision_engine:
        vision_engine.unload()
    timings["streszczenie_s"] = round(time.time() - t, 1)
    timings["razem_s"] = round(time.time() - t0, 1)
    if speech_thread:
        timings["mowa_rownolegle"] = True

    # film do odtwarzacza w widoku wyniku: pobrany z linku / wysłany z UI → przenosimy do folderu wyników;
    # plik wskazany ścieżką zostaje na miejscu (bez kopiowania dużych plików)
    src_sha = _sha256(src.path)
    if src.kind == "link" or opt.move_source:
        dst = out / ("film" + src.path.suffix.lower())
        try:
            shutil.move(str(src.path), dst)
            film_ref = dst.name
        except OSError:
            film_ref = str(src.path)
    else:
        film_ref = str(src.path)

    result = {
        "schema": SCHEMA,
        "narzedzie": {"nazwa": "VidSum", "wersja": __version__},
        "utworzono": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "zrodlo": {"rodzaj": src.kind, "wejscie": src.original, "url": src.webpage_url,
                   "tytul": src.title, "autor": src.uploader, "plik": src.path.name,
                   "sha256": src_sha, "dlugosc_s": round(info.duration, 2),
                   "szerokosc": info.width, "wysokosc": info.height, "audio": info.has_audio,
                   "film": film_ref},
        "ustawienia": {"whisper": tr.engine, "jezyk": opt.language or "auto",
                       "obraz": f"ollama:{opt.vision_model}" if vision_engine else "brak",
                       "streszczenie": summary_engine or "brak", "limit_kadrow": plan.max_frames,
                       "pokrycie_co_s": plan.base_interval, "uwagi_techniczne": tech_notes},
        "transkrypcja": {"jezyk": tr.language, "segmenty": [asdict(s) for s in tr.segments]},
        "napisy_ekranowe": [asdict(l) for l in ocr_lines],
        "kadry": [asdict(f) for f in frames],
        "os_czasu": beats,
        "streszczenie": {"silnik": summary_engine, "markdown": summary_md, "dane": summary_data} if summary_md else None,
        "luki": gaps,
        "czasy": timings,
    }
    (out / "analiza.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "transkrypcja.srt").write_text(_srt(tr), encoding="utf-8")
    (out / "raport.md").write_text(_report_md(result), encoding="utf-8")
    log(f"  ✔ gotowe w {_dur(timings['razem_s'])} — {_timing_line(timings)}")
    return out


_STAGES = [("pobieranie_s", "pobieranie"), ("ocr_s", "napisy (OCR)"), ("transkrypcja_s", "mowa"), ("kadry_s", "kadry"),
           ("obraz_s", "opis obrazu"), ("streszczenie_s", "streszczenie")]


def _dur(sec: float) -> str:
    sec = float(sec or 0)
    return f"{int(sec // 60)} min {sec % 60:.0f} s" if sec >= 60 else f"{sec:.1f} s"


def _timing_line(c: dict) -> str:
    parts = [f"{lab} {_dur(c[k])}" for k, lab in _STAGES if c.get(k, 0) >= 0.05]   # wyłączone etapy pomijamy
    note = " (mowa liczona równolegle z opisem obrazu)" if c.get("mowa_rownolegle") else ""
    return " · ".join(parts) + note


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
         f"streszczenie `{r['ustawienia']['streszczenie']}`",
         f"- ⏱ Czas analizy: **{_dur(r['czasy'].get('razem_s', 0))}** — {_timing_line(r['czasy'])}", ""]
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
        for k, lab in (("czynnosci", "czynności"), ("obiekty", "obiekty"), ("tekst_na_ekranie", "napisy w filmie"),
                       ("napisy_na_przedmiotach", "napisy na przedmiotach")):
            if w.get(k):
                extra.append(f"{lab}: {', '.join(w[k])}")
        if w.get("cialo"):
            extra.append(f"ciało: {w['cialo']}")
        L.append(f"### {ts(b['start'])}–{ts(b['end'])}")
        L.append(f"![kadr]({b['kadr']})  ")
        L.append(f"**Obraz** _(z obrazu, pewność: {w.get('pewnosc', '—')})_: {seen}" + (f" — {'; '.join(extra)}" if extra else ""))
        if b.get("napisy"):
            L.append(f"**Napisy na ekranie** _(OCR)_: {b['napisy']}  ")
        L.append(f"**Mowa** _(z mowy)_: {b['slychac']['tekst'] or 'brak danych'}")
        L.append("")
    L += ["## Pełna transkrypcja", ""]
    L += [f"`{ts(s['start'])}` {s['text']}" + "  " for s in r["transkrypcja"]["segmenty"]] or ["brak danych"]
    return "\n".join(L) + "\n"
