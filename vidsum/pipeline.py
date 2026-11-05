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
from .summary import build_json_prompt, compact_timeline, parse_summary, staged_summary, to_markdown, verify_quotes
from .fetch import resolve
from .languages import DEFAULT_TRANSLATIONS, base as lang_base, name_pl, normalize, translation_targets
from .llm import DEFAULT_TEXT_MODEL, ClaudeCode, LLMError, Ollama
from .media import (choose_frames, extract_audio, extract_frame, frame_signature, hamming, plan_for, probe,
                    scene_scores)
from .transcribe import SidecarEngine, Transcript, WhisperEngine

SCHEMA = "vidsum.analysis/1"
VISION_WORKERS = 2          # ile kadrów naraz opisuje model obrazu


@dataclass
class Options:
    out_root: Path = Path("vidsum_wyniki")
    language: str | None = None                # None = wykryj; kod Whispera (99 języków), np. "pl", "en", "de"
    whisper_model: str = "large-v3-turbo"     # pomiar: PL 5,5% WER (small: 12,3%)
    whisper_device: str = "auto"
    whisper_root: str | None = None
    transcript_file: Path | None = None        # gotowe napisy zamiast Whispera
    vision: str = "ollama"                     # "ollama" | "brak"
    vision_model: str = "qwen3-vl:4b-instruct"
    summary: str = "auto"                      # "auto" = lokalny model (jak "ollama") | "claude" (dodatek) | "brak"
    text_model: str = DEFAULT_TEXT_MODEL       # lokalny model tekstowy: streszczenie, czat, tłumaczenia
    summary_model: str | None = None           # (zgodność wstecz) nadpisuje text_model
    translate: list = field(default_factory=lambda: list(DEFAULT_TRANSLATIONS))   # tłumaczenia (bez oryginału)
    cuda_download: bool = True                 # karta NVIDIA bez bibliotek CUDA → pobierz je (jednorazowo)
    ollama_host: str | None = None
    max_frames: int | None = None
    cookies_from_browser: str | None = None
    allow_api_key: bool = False
    prefer_subtitles: bool = True              # napisy z YouTube zamiast Whispera, jeśli są
    ocr: bool = True                           # gęsty OCR napisów na ekranie (+ podpowiedzi słów dla Whispera)
    move_source: bool = False                  # przenieś plik źródłowy do folderu wyników (wysłane z UI)
    on_partial: Callable | None = None         # wyniki etapów od razu, gdy gotowe (podgląd w UI): (rodzaj, dane)
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


def _emit(opt: Options, kind: str, data) -> None:
    if opt.on_partial:
        try:
            opt.on_partial(kind, data)
        except Exception:
            pass


def analyze(inp: str, opt: Options, log: Log = print) -> Path:
    t0 = time.time()
    trail: list[str] = []                       # pełny przebieg (co, kiedy, nad czym) → przebieg.log w wynikach
    outer_log = log

    def log(msg: str) -> None:                  # noqa: F811 — ten sam log + zapis z czasem od startu
        trail.append(f"[{time.time() - t0:6.1f} s] {msg}")
        outer_log(msg)

    opt.language = normalize(opt.language)          # nieznany kod → czytelny błąd od razu
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp = opt.out_root / "_pobrane"
    # od 0.7.7: link → model obrazu wczytuje się do karty JUŻ W CZASIE POBIERANIA filmu (na komputerze testowym wczytanie ~11 s,
    # a kadry były gotowe wcześniej i czekały na model)
    early: dict = {}
    early_thread = None
    if opt.vision == "ollama" and re.match(r"https?://", str(inp).strip(), re.I):
        def early_preload() -> None:
            t_l = time.time()
            Ollama(opt.vision_model, opt.ollama_host).preload()
            early["s"] = round(time.time() - t_l, 1)
        early_thread = threading.Thread(target=early_preload, daemon=True)
        early_thread.start()
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

    # Kolejność (od 0.7.2, cel: minutowy film ≈ minuta): OCR na CPU w tle, Whisper na GPU od razu (bez czekania na OCR),
    # kadry równolegle; po opisie kadrów — druga, dokładniejsza transkrypcja z podpowiedziami z napisów (GPU, kilka s).
    ocr_lines: list = []
    pre_notes: list[str] = []
    ocr_box: dict = {}

    def run_ocr() -> None:
        t = time.time()
        try:
            from .ocr import ensure_models, read_captions
            mdir = ensure_models(Path(opt.whisper_root) if opt.whisper_root else out.parent / "_modele", log)
            ocr_box["lines"] = read_captions(src.path, info.duration, mdir, log)
            if ocr_box["lines"]:
                _emit(opt, "napisy", [asdict(l) for l in ocr_box["lines"]])
        except Exception as e:     # OCR to dodatek — jego awaria nie zatrzymuje analizy
            ocr_box["note"] = f"OCR napisów niedostępny ({type(e).__name__}: {str(e)[:100]})."
            log(f"        ! OCR: {e}")
        ocr_box["s"] = round(time.time() - t, 1)

    t_speech = time.time()
    tr_box: dict = {}
    speech_thread = None
    speech_job = None
    need_whisper = info.has_audio and not opt.transcript_file and not (src.subtitles and opt.prefer_subtitles)
    small_model = any(x in Path(opt.whisper_model).name.lower() for x in ("tiny", "base", "small"))
    engine, device, wav = None, "cpu", None
    # automatyczne napisy YouTube to też maszynowe rozpoznawanie mowy (na komputerze testowym „a grilled potatoes” zamiast
    # „Agria”) — na GPU służą tylko za szybki podgląd, a docelową transkrypcję robi Whisper z podpowiedziami z OCR
    auto_caps = (info.has_audio and not opt.transcript_file and bool(src.subtitles) and opt.prefer_subtitles
                 and src.subtitles_kind == "automatyczne")
    caps_then_whisper = False
    if need_whisper or auto_caps:
        engine = WhisperEngine(opt.whisper_model, opt.whisper_device, download_root=opt.whisper_root)
        engine.cuda_download = opt.cuda_download
        device, _ = engine.resolve_device(log)
        caps_then_whisper = auto_caps and device == "cuda"

    # model obrazu wczytuje się do karty W TLE, w czasie OCR i wycinania kadrów
    preload_thread = None
    if opt.vision == "ollama":
        def preload() -> None:
            if need_whisper and device == "cuda" and speech_thread:
                speech_thread.join()       # najpierw Whisper na karcie (oba naraz mogłyby nie zmieścić się w 8 GB)
            t_l = time.time()
            Ollama(opt.vision_model, opt.ollama_host).preload()
            timings["obraz_wczytanie_s"] = round(time.time() - t_l, 1)
            log(f"        model obrazu wczytany do karty ({time.time() - t_l:.1f} s)")
        preload_job = preload
    else:
        preload_job = None
    if early_thread:
        if need_whisper and device == "cuda":
            # Whisper (1. przebieg) na karcie obok modelu obrazu tylko, gdy jest miejsce; inaczej zwolnij kartę
            # i wczytaj model obrazu po Whisperze (jak w 0.7.6)
            early_thread.join()
            from .cuda import free_vram_mb
            free = free_vram_mb()
            if free is None or free < 2500:
                Ollama(opt.vision_model, opt.ollama_host).unload()
                early_thread = None
            else:
                preload_job = None
        else:
            preload_job = None                 # wczytuje się już od startu

    # 0) NAPISY NA EKRANIE (OCR)
    # od 0.7.6: OCR startuje PO wycięciu kadrów — wcześniej oba naraz walczyły o procesor i kadry czekały ~18 s
    # (na komputerze testowym), a opis kadrów (GPU) mógł już trwać. OCR kończy się w tle w czasie opisu kadrów.
    ocr_thread = None
    ocr_deferred = False
    if opt.ocr:
        if need_whisper and device != "cuda":
            log("  [0/4] napisy na ekranie (OCR)…")
            run_ocr()                      # CPU: Whisper i tak czeka (podpowiedzi słów z napisów, pomiar WER)
        else:
            ocr_deferred = True

    def start_ocr() -> None:
        nonlocal ocr_thread
        log("  [0/4] napisy na ekranie (OCR) — w tle, w czasie opisu kadrów…")
        ocr_thread = threading.Thread(target=run_ocr, daemon=True)
        ocr_thread.start()

    def finish_ocr() -> None:
        nonlocal ocr_lines
        if ocr_thread and ocr_thread.is_alive():
            log("        czekam na OCR…")
            ocr_thread.join()
        ocr_lines = ocr_box.get("lines", [])
        if "note" in ocr_box and ocr_box["note"] not in pre_notes:
            pre_notes.append(ocr_box["note"])
        if opt.ocr:
            timings["ocr_s"] = ocr_box.get("s", 0.0)

    if not ocr_deferred:
        finish_ocr()

    # 1) MOWA — napisy z serwisu (najszybciej), gotowy plik albo Whisper.
    if opt.transcript_file:
        tr_box["tr"] = SidecarEngine(opt.transcript_file).transcribe(language=opt.language)
        _emit(opt, "transkrypcja", {"jezyk": tr_box["tr"].language, "segmenty": [asdict(x) for x in tr_box["tr"].segments]})
        tr_box["s"] = round(time.time() - t_speech, 1)
    elif not info.has_audio:
        tr_box["tr"] = Transcript(None, "brak", [])
        gaps.append("Brak ścieżki dźwiękowej — wszystko pochodzi tylko z obrazu.")
    elif not need_whisper:
        tr = SidecarEngine(src.subtitles).transcribe(language=opt.language)
        tr.engine = f"napisy serwisu ({src.subtitles_kind})"
        sfx = src.subtitles.suffixes            # np. pobrane_ID.en-orig.vtt → "en"
        if not tr.language and len(sfx) > 1:
            tr.language = lang_base(sfx[-2].strip("."))
        tr_box["tr"] = tr
        tr_box["s"] = round(time.time() - t_speech, 1)
        _emit(opt, "transkrypcja", {"jezyk": tr.language, "segmenty": [asdict(x) for x in tr.segments]})
        if caps_then_whisper:
            wav = extract_audio(src.path, out / "_audio.wav")
            log(f"  [1/4] mowa: napisy serwisu (automatyczne) jako podgląd; dokładna transkrypcja Whisperem na GPU "
                f"po opisie kadrów")
        else:
            log(f"  [1/4] mowa z napisów serwisu ({src.subtitles_kind}) — bez Whispera")
    else:
        wav = extract_audio(src.path, out / "_audio.wav")
        if device != "cuda" and ocr_lines and not small_model:
            # podpowiedzi słów tylko dla dużych modeli — małym szkodzą (pomiar: small WER 13–52%)
            from .ocr import hotwords
            engine.hotwords = hotwords(ocr_lines, src.title)
            engine.coverage_hints = [(l.start, l.end) for l in ocr_lines]
        log(f"  [1/4] transkrypcja (Whisper {opt.whisper_model}, {device}; za pierwszym razem pobieranie modelu)…")

        def run_whisper() -> None:
            t = time.time()
            try:
                tr_box["tr"] = engine.transcribe(wav, opt.language)
                _emit(opt, "transkrypcja", {"jezyk": tr_box["tr"].language,
                                            "segmenty": [asdict(x) for x in tr_box["tr"].segments]})
                log(f"        transkrypcja gotowa: {len(tr_box['tr'].segments)} zdań, {time.time() - t:.1f} s")
                if engine.recovered:
                    tr_box["tr"].note = ((tr_box["tr"].note + " ") if tr_box["tr"].note else "") + \
                        f"Odzyskano {engine.recovered} zdań pominiętych przez Whispera (drugi przebieg bez podpowiedzi)."
            except Exception as e:   # błąd mowy nie może zatrzymać analizy obrazu
                tr_box["err"] = e
            finally:
                tr_box["s"] = round(time.time() - t, 1)

        if device == "cpu" and opt.vision == "ollama":
            # start dopiero PO wycięciu kadrów: ffmpeg i Whisper na CPU naraz spowalniały się nawzajem
            # (na komputerze testowym kadry 96 s zamiast kilku); opis kadrów idzie na GPU, więc tam nakładanie się opłaca
            speech_job = run_whisper
        elif device == "cuda":
            # Whisper na GPU od razu, RÓWNOLEGLE z OCR i wycinaniem kadrów (CPU); przed opisem kadrów
            # czekamy na koniec — dwa modele naraz nie zmieszczą się w 8 GB VRAM
            speech_thread = threading.Thread(target=run_whisper, daemon=True)
            speech_thread.start()
        else:
            run_whisper()

    if preload_job:
        preload_thread = threading.Thread(target=preload_job, daemon=True)
        preload_thread.start()
    elif early_thread:
        preload_thread = early_thread

        def note_early() -> None:              # czas wczytania do logu, gdy się skończy
            early_thread.join()
            timings["obraz_wczytanie_s"] = early.get("s", 0.0)
            log(f"        model obrazu wczytany do karty ({early.get('s', 0.0):.1f} s, od startu, w czasie pobierania)")
        threading.Thread(target=note_early, daemon=True).start()

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
    if ocr_deferred:
        start_ocr()
    if speech_job:
        speech_thread = threading.Thread(target=speech_job, daemon=True)
        speech_thread.start()

    if speech_thread and not speech_job and opt.vision == "ollama":     # GPU: zwolnij kartę przed modelem obrazu
        log("        czekam na transkrypcję (GPU)…")
        speech_thread.join()

    # POPRAWKA MOWY (Whisper GPU z podpowiedziami z napisów na ekranie) — od 0.7.6 w czasie opisu kadrów,
    # jeśli na karcie jest miejsce obok modelu obrazu; inaczej po opisie kadrów (jak wcześniej)
    use_hot = not small_model
    ref_box: dict = {}

    def refine_job() -> None:
        if ocr_thread and ocr_thread.is_alive():
            ocr_thread.join()
        tr0 = tr_box.get("tr")
        if not (wav and device == "cuda" and tr0 and tr0.segments):
            return
        lines = ocr_box.get("lines", []) if opt.ocr else []
        hot2 = ""
        if use_hot and lines:
            from .ocr import hotwords_targeted
            hot2 = hotwords_targeted(lines, src.title, " ".join(x.text for x in tr0.segments))
        if not (hot2 or caps_then_whisper):
            return
        t_r = time.time()
        log("  [1/4] dokładna transkrypcja Whisperem (GPU)" + (" z podpowiedziami z napisów na ekranie" if hot2 else "")
            + (" — równolegle z opisem kadrów" if ref_box.get("overlap") else "") + "…")
        if hot2:
            log(f"        podpowiedzi z napisów: {hot2[:150]}")
        eng2 = WhisperEngine(opt.whisper_model, "cuda", download_root=opt.whisper_root, hotwords=hot2 or None)
        eng2.coverage_hints = [(l.start, l.end) for l in lines] if hot2 else []
        try:
            tr2 = eng2.transcribe(wav, tr0.language)
            if tr2.segments:
                if eng2.recovered:
                    tr2.note = f"Odzyskano {eng2.recovered} zdań pominiętych przez Whispera (drugi przebieg bez podpowiedzi)."
                ref_box["tr"] = tr2
            log(f"        poprawka mowy gotowa ({time.time() - t_r:.1f} s)")
        except Exception as e:                     # np. brak pamięci karty obok modelu obrazu → po opisie kadrów
            ref_box["err"] = e
            log(f"        ! poprawka transkrypcji: {str(e)[:120]}")
        ref_box["s"] = round(time.time() - t_r, 1)

    def start_refine():
        if not (wav and device == "cuda" and tr_box.get("tr") is not None):
            return None
        from .cuda import free_vram_mb
        free = free_vram_mb()
        if free is None or free < 2500:
            log(f"        poprawka mowy po opisie kadrów (wolna pamięć karty: {free if free is not None else '?'} MB)")
            return None
        ref_box["overlap"] = True
        th = threading.Thread(target=refine_job, daemon=True)
        th.start()
        return th

    # 3) OBRAZ
    t = time.time()
    vision_engine = None
    refine_thread = None
    if opt.vision == "ollama":
        vision_engine = Ollama(opt.vision_model, opt.ollama_host)
        vision_engine.check()
        if preload_thread and preload_thread.is_alive():
            log("        model obrazu jeszcze się wczytuje…")
            preload_thread.join()
        log(f"  [3/4] opis kadrów ({opt.vision_model})…")
        failed: list[str] = []
        done = [0]
        busy = [0.0]
        lock = threading.Lock()

        def describe(f: FrameInfo) -> None:
            err = None
            t_f = time.time()
            for attempt in (1, 2):   # Ollama sama podnosi model po awarii — jedna ponowna próba
                try:
                    f.vision = vision_engine.describe_frame(out / f.file, ts(f.t))
                    break
                except LLMError as e:
                    err = e
            with lock:
                busy[0] += time.time() - t_f
                done[0] += 1
                if f.vision is None:
                    failed.append(ts(f.t))
                    log(f"        {done[0]}/{len(frames)} kadr {ts(f.t)} ! błąd: {str(err)[:90]}")
                else:
                    v = f.vision
                    log(f"        {done[0]}/{len(frames)} kadr {ts(f.t)}: {v.get('scena', '')[:90]}"
                        + (f" | czynności: {', '.join(v['czynnosci'])[:60]}" if v.get("czynnosci") else ""))

        # dwa kadry naraz tylko, gdy Ollama obsługuje kilka zapytań (OLLAMA_NUM_PARALLEL ≥ 2); inaczej to tylko kolejka
        from concurrent.futures import ThreadPoolExecutor
        workers = min(VISION_WORKERS, vision_engine.parallel)
        refine_thread = start_refine()             # poprawka mowy (Whisper, GPU) RÓWNOLEGLE z opisem kadrów
        t_v = time.time()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(describe, frames))
        wall = time.time() - t_v
        if frames and wall > 0:
            # pomiar: ile kadrów model naprawdę liczył naraz (1,0× = po kolei mimo kilku zapytań)
            log(f"        opis kadrów: {wall:.1f} s, {wall / len(frames):.1f} s/kadr, równolegle ~{busy[0] / wall:.1f}× "
                f"({workers} zapytania naraz)")
            timings["obraz_rownoleglosc"] = round(busy[0] / wall, 2)
        failed.sort()
        _emit(opt, "kadry", [{"t": f.t, "file": f.file, "scena": (f.vision or {}).get("scena", "")} for f in frames])
        if failed:
            gaps.append(f"Nie udało się opisać kadrów: {', '.join(failed)} — w tych miejscach obraz = brak danych.")
    else:
        gaps.append("Analiza obrazu wyłączona — kadry zapisane, ale bez opisów.")
    timings["obraz_s"] = round(time.time() - t, 1)

    if speech_thread and speech_thread.is_alive():
        log("        czekam na transkrypcję…")
        speech_thread.join()
    finish_ocr()
    if "err" in tr_box:
        if wav:
            wav.unlink(missing_ok=True)
        raise tr_box["err"]
    tr = tr_box["tr"]
    timings["transkrypcja_s"] = tr_box.get("s", round(time.time() - t_speech, 1))
    # druga, dokładniejsza transkrypcja: podpowiedzi słów z napisów na ekranie (nazwy, liczby) —
    # pomiar: WER 5,5% → 0–1,4% po polsku. Na GPU to kilka sekund.
    if refine_thread:
        if refine_thread.is_alive():
            log("        czekam na poprawkę mowy…")
        refine_thread.join()
        if "err" in ref_box:                       # obok modelu obrazu się nie udało — jeszcze raz, z wolną kartą
            ref_box.clear()
            if vision_engine:
                vision_engine.unload()
            refine_job()
    elif wav and device == "cuda" and tr.segments:
        if vision_engine:
            vision_engine.unload()                 # karta dla Whispera
        refine_job()
    if "tr" in ref_box:
        tr = tr_box["tr"] = ref_box["tr"]
        _emit(opt, "transkrypcja", {"jezyk": tr.language, "segmenty": [asdict(x) for x in tr.segments]})
    if "s" in ref_box:
        timings["transkrypcja_poprawka_s"] = ref_box["s"]
    # pojedyncze słowa, które napis na ekranie w tym samym momencie podaje inaczej („maldon chocolate” → „salt”)
    caption_fixes: list[dict] = []
    if ocr_lines and tr.segments:
        from .ocr import correct_from_captions
        caption_fixes = correct_from_captions(tr.segments, ocr_lines)
        if caption_fixes:
            log("        poprawki z napisów na ekranie: " + ", ".join(f"{x['bylo']} → {x['jest']} ({ts(x['t'])})"
                                                               for x in caption_fixes))
    if wav:
        wav.unlink(missing_ok=True)
    if info.has_audio and not tr.segments:
        gaps.append("Nie rozpoznano mowy — film może mieć muzykę lub inne dźwięki, ale nikt nie mówi "
                    "(albo mowa jest niewyraźna / w innym języku).")
    tech_notes = pre_notes + ([tr.note] if tr.note else [])   # sprawy techniczne (np. Whisper na CPU) — nie luki w analizie
    log(f"        mowa: {len(tr.segments)} segmentów, język: {tr.language} ({tr.engine})")

    beats = build_beats(frames, tr.segments, info.duration, ocr_lines)
    meta = {"tytuł": src.title, "autor": src.uploader, "długość": ts(info.duration),
            "język mowy": f"{name_pl(tr.language)} ({tr.language})" if tr.language else None}
    prompt = build_summary_prompt(beats, meta, gaps)             # wersja do wklejenia na claude.ai
    (out / "prompt_dla_claude.md").write_text(prompt, encoding="utf-8")
    json_prompt = build_json_prompt(beats, meta, gaps)           # wersja dla programu (dane do widoku)

    # 4) STRESZCZENIE + TŁUMACZENIA — samodzielnie, lokalnym modelem tekstowym (Claude tylko jako dodatek)
    t = time.time()
    summary_md, summary_engine, summary_data = None, None, None
    summary_mode = "ollama" if opt.summary == "auto" else opt.summary
    targets = translation_targets(tr.language, opt.translate) if tr.segments else []
    translations: dict = {}
    text_engine, text_name = None, None
    if summary_mode != "brak" or targets:
        if vision_engine:
            # zwolnij model obrazu: model tekstowy ma inny kontekst, a dwa naraz nie mieszczą się w 8 GB
            vision_engine.unload()
        try:
            if summary_mode == "claude":
                text_engine, text_name = ClaudeCode(allow_api_key=opt.allow_api_key), "claude-code"
            else:
                text_engine = Ollama(opt.summary_model or opt.text_model, opt.ollama_host)
                text_name = f"ollama:{text_engine.model}"
                text_engine.ensure(log)                # pierwszy raz: pobranie modelu (jednorazowo)
                t_l = time.time()
                from .llm import TEXT_CTX
                text_engine.preload(TEXT_CTX)
                timings["tekst_wczytanie_s"] = round(time.time() - t_l, 1)
                log(f"        model tekstowy wczytany ({time.time() - t_l:.1f} s)")
        except LLMError as e:
            gaps.append(f"Model tekstowy niedostępny ({e}) — bez streszczenia i tłumaczeń.")
            log(f"        ! {e}")
            text_engine = None
    def run_translations() -> None:
        t_tr = time.time()
        from .translate import translate_segments
        seg_dicts = [asdict(s) for s in tr.segments]
        for lang in targets:
            log(f"        tłumaczenie transkrypcji: {tr.language} → {lang} ({len(seg_dicts)} segmentów)…")
            try:
                segs, failed = translate_segments(text_engine, seg_dicts, tr.language, lang, log)
            except LLMError as e:
                gaps.append(f"Tłumaczenie na {name_pl(lang)} nie powstało: {e}")
                continue
            translations[lang] = {"silnik": text_name, "segmenty": segs, "nieprzetlumaczone": failed}
            _emit(opt, "tlumaczenie_" + lang, segs)
            log(f"        tłumaczenie na {name_pl(lang)} gotowe ({time.time() - t_tr:.1f} s)")
            if failed:
                gaps.append(f"Tłumaczenie na {name_pl(lang)}: {failed} z {len(segs)} linii bez tłumaczenia "
                            "(model nie zwrócił poprawnej odpowiedzi) — w tych miejscach tylko oryginał.")
        timings["tlumaczenie_s"] = round(time.time() - t_tr, 1)

    # tłumaczenie RÓWNOLEGLE ze streszczeniem (ten sam model w Ollamie obsługuje dwa zapytania naraz)
    tr_thread = None
    if text_engine and targets:
        tr_thread = threading.Thread(target=run_translations, daemon=True)
        tr_thread.start()

    t_s = time.time()
    if text_engine and summary_mode != "brak":
        log(f"  [4/4] streszczenie ({text_name})…")
        try:
            if summary_mode == "claude":          # duży model: jeden prompt z pełną osią czasu
                raw = text_engine.complete(json_prompt, as_json=True)
                summary_data = parse_summary(raw, info.duration)
            else:                                  # lokalny 4–8B: etapami (pomiar: dużo więcej faktów, docs/modele.md)
                raw = ""
                meta_txt = "; ".join(f"{k}: {v}" for k, v in meta.items() if v not in (None, ""))
                # z mowy w ORYGINALE: pomiar (docs/modele.md, runda 3) — streszczanie z polskiego tłumaczenia
                # nie dało więcej faktów, a przenosiło błędy rozpoznawania mowy dalej („grilled” → „grillowane”)
                src_beats = beats
                trace: list = []
                summary_data = staged_summary(text_engine, compact_timeline(src_beats), meta_txt, info.duration, log,
                                              trace=trace)
                # kroki pośrednie (fakty, uzupełnienie, opis) — żeby było widać, gdzie coś zginęło
                (out / "streszczenie_kroki.json").write_text(json.dumps(trace, ensure_ascii=False, indent=1),
                                                            encoding="utf-8")
            if summary_data:
                bad = verify_quotes(summary_data, [asdict(x) for x in tr.segments])
                if bad:
                    log(f"        usunięto {bad} cytat(y), których nie ma w transkrypcji")
            summary_md = to_markdown(summary_data) if summary_data else (raw or None)
            summary_engine = text_name
            if not summary_data:
                log("        ! model nie zwrócił poprawnych danych")
                gaps.append("Model tekstowy nie zwrócił poprawnego streszczenia — zostaje oś czasu i transkrypcja.")
        except LLMError as e:
            gaps.append(f"Streszczenie nie powstało: {e}")
            log(f"        ! {e}")

    timings["streszczenie_s"] = round(time.time() - t_s, 1)
    if tr_thread:
        if tr_thread.is_alive():
            log("        czekam na tłumaczenie…")
        tr_thread.join()
        timings["tekst_razem_s"] = round(time.time() - t_s, 1)
    if text_engine and isinstance(text_engine, Ollama):
        text_engine.unload()
    if vision_engine:
        vision_engine.unload()
    timings["razem_s"] = round(time.time() - t0, 1)
    if speech_thread or ocr_thread:
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
        "ustawienia": {"whisper": tr.engine, "jezyk": opt.language or "auto", "tlumaczenia": targets,
                       "obraz": f"ollama:{opt.vision_model}" if vision_engine else "brak",
                       "streszczenie": summary_engine or "brak", "limit_kadrow": plan.max_frames,
                       "pokrycie_co_s": plan.base_interval, "uwagi_techniczne": tech_notes},
        # oryginał ZAWSZE w języku mowy; tłumaczenia obok, z tymi samymi czasami segmentów
        "transkrypcja": {"jezyk": tr.language, "jezyk_nazwa": name_pl(tr.language) if tr.language else None,
                         "segmenty": [asdict(s) for s in tr.segments], "tlumaczenia": translations,
                         "poprawki_z_napisow": caption_fixes},
        "napisy_ekranowe": [asdict(l) for l in ocr_lines],
        "kadry": [asdict(f) for f in frames],
        "os_czasu": beats,
        "streszczenie": {"silnik": summary_engine, "markdown": summary_md, "dane": summary_data} if summary_md else None,
        "luki": gaps,
        "czasy": timings,
    }
    (out / "analiza.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "transkrypcja.srt").write_text(_srt(tr.segments), encoding="utf-8")
    for lang, tdata in translations.items():           # napisy w innych językach (pusta linia = brak tłumaczenia)
        (out / f"transkrypcja.{lang}.srt").write_text(_srt(tdata["segmenty"]), encoding="utf-8")
    (out / "raport.md").write_text(_report_md(result), encoding="utf-8")
    (out / "przebieg.log").write_text("\n".join(trail) + "\n", encoding="utf-8")
    try:
        _append_history(opt.out_root, {**result, "_folder": out.name}, len(ocr_lines))
    except OSError as e:                         # np. plik otwarty w Excelu — analiza i tak jest zapisana
        log(f"        ! historia czasów: {e}")
    log(f"  ✔ gotowe w {_dur(timings['razem_s'])} — {_timing_line(timings)}")
    return out


HISTORY_COLS = ["data", "wersja", "tytul", "dlugosc_s", "zrodlo_mowy", "kadrow", "napisow_ocr", "razem_s", "pobieranie_s",
                "ocr_s", "transkrypcja_s", "transkrypcja_poprawka_s", "kadry_s", "obraz_s", "streszczenie_s",
                "tlumaczenie_s", "folder"]


def _append_history(root: Path, r: dict, n_ocr: int) -> None:
    """Jedna linijka na analizę w historia_czasow.csv (w folderze wyników) — do porównywania wersji i filmów.

    Średnik jako separator i przecinek dziesiętny: plik otwiera się poprawnie w polskim Excelu."""
    import csv
    f = Path(root) / "historia_czasow.csv"
    new = not f.is_file()
    c = r["czasy"]

    def num(v):
        return "" if v in (None, "") else str(v).replace(".", ",")
    row = {"data": r["utworzono"][:19].replace("T", " "), "wersja": r["narzedzie"]["wersja"],
           "tytul": r["zrodlo"].get("tytul") or r["zrodlo"].get("plik"), "dlugosc_s": num(r["zrodlo"]["dlugosc_s"]),
           "zrodlo_mowy": r["ustawienia"]["whisper"], "kadrow": len(r["kadry"]), "napisow_ocr": n_ocr,
           "folder": r.get("_folder", "")}
    for k in HISTORY_COLS:
        if k.endswith("_s") and k != "dlugosc_s":
            row[k] = num(c.get(k))
    with open(f, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=HISTORY_COLS, delimiter=";")
        if new:
            w.writeheader()
        w.writerow(row)


_STAGES = [("pobieranie_s", "pobieranie"), ("ocr_s", "napisy (OCR)"), ("transkrypcja_s", "mowa"), ("kadry_s", "kadry"),
           ("obraz_s", "opis obrazu"), ("transkrypcja_poprawka_s", "poprawka mowy"),
           ("streszczenie_s", "streszczenie"), ("tlumaczenie_s", "tłumaczenie")]


def _dur(sec: float) -> str:
    sec = float(sec or 0)
    if sec < 60:
        return f"{sec:.1f} s"
    whole = int(round(sec))                       # 119,5 s → „2 min 0 s”, nie „1 min 60 s”
    return f"{whole // 60} min {whole % 60} s"


def _timing_line(c: dict) -> str:
    parts = [f"{lab} {_dur(c[k])}" for k, lab in _STAGES if c.get(k, 0) >= 0.05]   # wyłączone etapy pomijamy
    note = " (część etapów idzie równolegle, więc suma jest większa niż całość)" if c.get("mowa_rownolegle") or c.get("tekst_razem_s") else ""
    return " · ".join(parts) + note


def _srt(segments: list) -> str:
    def f(t: float) -> str:
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"
    rows = [s if isinstance(s, dict) else asdict(s) for s in segments]
    return "\n".join(f"{i}\n{f(s['start'])} --> {f(s['end'])}\n{s['text'] or ''}\n" for i, s in enumerate(rows, 1))


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
    tr = r["transkrypcja"]
    L += [f"## Pełna transkrypcja (oryginał: {tr.get('jezyk_nazwa') or 'język nieznany'})", ""]
    if tr.get("poprawki_z_napisow"):
        L += ["_Poprawione według napisów na ekranie: " + ", ".join(
            f"„{x['bylo']}” → „{x['jest']}” ({ts(x['t'])})" for x in tr["poprawki_z_napisow"]) + "._", ""]
    L += [f"`{ts(s['start'])}` {s['text']}" + "  " for s in tr["segmenty"]] or ["brak danych"]
    for lang, t in (tr.get("tlumaczenia") or {}).items():
        L += ["", f"## Tłumaczenie: {name_pl(lang)} _(maszynowe, {t['silnik']})_", ""]
        L += [f"`{ts(s['start'])}` {s['text'] if s['text'] else '_[brak tłumaczenia]_'}  " for s in t["segmenty"]]
    return "\n".join(L) + "\n"
