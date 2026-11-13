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
    # szybki podgląd: wstępne streszczenie z mowy, potem pełne. None (domyślnie, 0.10.0) = automatycznie, gdy nic nie
    # kosztuje: ten sam model do obrazu i tekstu (nic się nie przeładowuje) albo obraz wyłączony. True = zawsze
    # (model tekstowy przed modelem obrazu, +kilkanaście s na karcie 8 GB). False = nigdy.
    preview: bool | None = None
    # tryb analizy (0.12.0, vidsum/modes.py): "pelna" — jak dotąd; "mowa" — tylko mowa (bez modelu obrazu i OCR);
    # "szybki" — raport z mowy, potem opis wybranych kadrów (wskazane mową, początki rozdziałów, pokrycie)
    mode: str = "pelna"
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


def check_on_gpu(engine, what: str, log, notes: list[str]) -> None:
    """0.11.6: pomiar 0.11.5 — Ollama wczytała oba modele w 0% na kartę przy 6,8 GB wolnych (analiza 14:30 zamiast 1:19);
    po ponownym uruchomieniu Ollamy wróciło 100% GPU. Ostrzegamy od razu, a nie dopiero w raporcie."""
    share = getattr(engine, "gpu_share", lambda: None)()
    if share is None or share >= 0.5:
        return
    try:
        from .cuda import free_vram_mb
        free = free_vram_mb()
    except Exception:
        free = None
    if free is not None and free < 1500:
        return                                   # karta naprawdę pełna — to inny przypadek (inne programy)
    msg = (f"Ollama wczytała {what} tylko w {share:.0%} na kartę, choć karta ma wolne {free or '?'} MB — model liczy się "
           "na procesorze, analiza będzie kilka razy wolniejsza. Zamknij Ollamę (ikona przy zegarze → Quit), "
           "uruchom ją ponownie i powtórz analizę.")
    log("        ⚠ " + msg)
    if msg not in notes:
        notes.append(msg)


def _vision_ollama(opt: "Options") -> Ollama:
    """Model obrazu; gdy to ten sam model co tekstowy — z kontekstem tekstu (bez przeładowań między kadrami a tekstem)."""
    from .llm import TEXT_CTX, VISION_CTX
    same = opt.vision_model == (opt.summary_model or opt.text_model)
    return Ollama(opt.vision_model, opt.ollama_host, vision_ctx=TEXT_CTX if same else VISION_CTX)


def analyze(inp: str, opt: Options, log: Log = print) -> Path:
    t0 = time.time()
    trail: list[str] = []                       # pełny przebieg (co, kiedy, nad czym) → przebieg.log w wynikach
    outer_log = log

    def log(msg: str) -> None:                  # noqa: F811 — ten sam log + zapis z czasem od startu
        trail.append(f"[{time.time() - t0:6.1f} s] {msg}")
        outer_log(msg)

    opt.language = normalize(opt.language)          # nieznany kod → czytelny błąd od razu
    from .modes import MODE_LABEL, normalize_mode
    mode = normalize_mode(opt.mode)
    from .media import AUDIO_EXT
    if Path(str(inp).split("?")[0]).suffix.lower() in AUDIO_EXT and mode != "transkrypcja":
        mode = "mowa"                               # plik dźwiękowy (mp3, m4a, wav…) — obrazu nie ma, liczy się mowa
    asked_mode = mode                               # do prognozy czasu i zapisu w analizie (tryb, który naprawdę liczymy)
    if mode == "transkrypcja":
        # 0.13.1: sama transkrypcja — jak „tylko mowa”, ale bez streszczenia i wstępnego podglądu (model tekstowy
        # liczy najwyżej tłumaczenie, jeśli włączone)
        from dataclasses import replace as _replace0
        opt = _replace0(opt, summary="brak", preview=False)
        log("  tryb: Sama transkrypcja")
        mode = "mowa"
    if opt.vision != "ollama" and mode == "szybki":
        mode = "mowa"                               # „szybki obraz” bez modelu obrazu to po prostu sama mowa
    full_opt = opt                                  # ustawienia użytkownika (model obrazu) — dla drugiej fazy „szybkiego”
    light = mode == "szybki"
    if mode != "pelna":
        # faza 1 w trybach „mowa” i „szybki”: wszystko z mowy — bez modelu obrazu i bez OCR całego filmu
        from dataclasses import replace as _replace
        opt = _replace(opt, vision="brak", ocr=False)
        log(f"  tryb: {MODE_LABEL[mode]}")
    cues: list[dict] = []                           # momenty, w których mowa wskazuje na obraz („look at this”)
    # zasoby karty: stan przed startem (co jeszcze z niej korzysta) + pomiar co 2 s w czasie analizy → raport
    from .cuda import GpuWatch, gpu_snapshot, ollama_models
    zasoby: dict = {"przed": gpu_snapshot(), "modele": {}}
    gpu_watch = GpuWatch().start() if zasoby["przed"] else None
    if zasoby["przed"]:
        g = zasoby["przed"]
        log(f"  karta: {g['karta']} — zajęte {g['zajete_mb']} MB z {g['pamiec_mb']} MB przed startem, wolne {g['wolne_mb']} MB")
        # modele z POPRZEDNIEJ analizy (Ollama trzyma je 5 min) to nie „inne programy”: zwalniamy te, których ta analiza
        # zaraz nie użyje. Pomiar 0.9.0: gemma3:4b po poprzedniej analizie zajmowała 3,1 GB → model obrazu wczytywał się
        # 17 s zamiast ~10 s, kadry czekały na niego, a ostrzeżenie mówiło o „innych programach”.
        first = (opt.summary_model or opt.text_model) if (opt.preview is True and opt.summary in ("auto", "ollama")) \
            else (opt.vision_model if opt.vision == "ollama" else None)
        left = [m for m in ollama_models(opt.ollama_host) if m.get("model") and m["model"] != first]
        if left and (opt.vision == "ollama" or opt.summary in ("auto", "ollama")):
            for m in left:
                Ollama(m["model"], opt.ollama_host).unload()
            mb = sum(round(m["rozmiar_mb"] * (m["na_karcie_proc"] or 0) / 100) for m in left)
            g["modele_poprzednie"] = left
            g["zajete_innych_mb"] = max(0, g["zajete_mb"] - mb)
            log(f"  zwolniono z karty model(e) z poprzedniej analizy: "
                + ", ".join(f"{m['model']} ({m['rozmiar_mb']} MB)" for m in left))
        if g.get("zajete_innych_mb", g["zajete_mb"]) > 1200:
            names = ", ".join(x["nazwa"].rsplit(".", 1)[0] for x in g["programy"][:8])
            log(f"  ! inne programy zajmują {g.get('zajete_innych_mb', g['zajete_mb'])} MB karty ({names}…) — analiza może być wolniejsza; "
                "zamknij przeglądarki, Discorda, Steama albo wyłącz w nich przyspieszanie sprzętowe")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp = opt.out_root / "_pobrane"
    # od 0.7.7: link → model obrazu wczytuje się do karty JUŻ W CZASIE POBIERANIA filmu (na komputerze testowym wczytanie ~11 s,
    # a kadry były gotowe wcześniej i czekały na model)
    early: dict = {}
    early_thread = None
    # szybki podgląd (0.8.3): model tekstowy idzie na kartę PIERWSZY, zaraz po transkrypcji; model obrazu wczytuje się
    # dopiero po podglądzie. Pomiar 0.8.2: wczytany wcześniej model obrazu był wypychany przez tekstowy i wczytywał się
    # drugi raz, a pusta przez chwilę karta myliła decyzję o Whisperze równolegle z kadrami (kadry 3,5 s zamiast 1,9 s).
    pv_first = bool(opt.preview is True and opt.summary in ("auto", "ollama") and opt.vision == "ollama")
    if opt.vision == "ollama" and not pv_first and re.match(r"https?://", str(inp).strip(), re.I):
        def early_preload() -> None:
            t_l = time.time()
            _vision_ollama(opt).preload()
            early["s"] = round(time.time() - t_l, 1)
        early_thread = threading.Thread(target=early_preload, daemon=True)
        early_thread.start()
    if mode != "pelna" and opt.summary in ("auto", "ollama"):
        # sama mowa: model tekstowy idzie na kartę od razu (w czasie pobierania i transkrypcji) — nic z nim nie konkuruje
        def early_text() -> None:
            try:
                from .llm import TEXT_CTX
                tm0 = Ollama(opt.summary_model or opt.text_model, opt.ollama_host)
                if tm0.has_model():
                    t_l = time.time()
                    tm0.preload(TEXT_CTX)
                    early["tekst_s"] = round(time.time() - t_l, 1)
            except LLMError:
                pass
        threading.Thread(target=early_text, daemon=True).start()
    src = resolve(inp, tmp, opt.cookies_from_browser)
    t_fetch = round(time.time() - t0, 1)
    name = _safe_name(src.title or src.path.stem)
    out = opt.out_root / f"{name}_{stamp}"
    (out / "kadry").mkdir(parents=True, exist_ok=True)
    log(f"▶ {src.original}\n  wyniki: {out}")

    info = probe(src.path)
    audio_only = not info.has_video
    if audio_only:
        # 0.12.0: nagranie bez obrazu (podcast, wykład, notatka głosowa) — pełny wynik z samej mowy
        if mode != "mowa":
            from dataclasses import replace as _replace
            mode, light = "mowa", False
            opt = _replace(opt, vision="brak", ocr=False)
        log(f"  długość {ts(info.duration)}, plik dźwiękowy (bez obrazu) — analiza mowy")
    else:
        log(f"  długość {ts(info.duration)}, {info.width}x{info.height}, audio: {'tak' if info.has_audio else 'nie'}")
    _emit(opt, "meta", {"tytul": src.title or src.path.stem, "autor": src.uploader, "dlugosc_s": round(info.duration, 2),
                        "url": src.webpage_url, "szerokosc": info.width, "wysokosc": info.height})
    gaps: list[str] = []
    timings: dict[str, float] = {"pobieranie_s": t_fetch} if src.kind == "link" else {}
    # 0.11.0: czarne pasy wpalone w obraz — tylko do wyświetlania w odtwarzaczu (plik zostaje bez zmian); w tle, CPU
    bars: dict = {}

    def find_bars() -> None:
        if audio_only:
            bars["r"] = None
            return
        try:
            from .media import detect_bars
            bars["r"] = detect_bars(src.path, info.duration, info.width, info.height)
        except Exception:
            bars["r"] = None
    bars_thread = threading.Thread(target=find_bars, daemon=True)
    bars_thread.start()

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
    # SZYBKI PODGLĄD (0.8.2): wstępne streszczenie z samej mowy na modelu TEKSTOWYM, zaraz po transkrypcji, PRZED opisem
    # kadrów. Pomiar: model obrazu (qwen3-vl:4b) po polsku pisał „marchewka agria”, „fasolki” — nie nadaje się.
    # Na karcie 8 GB oba modele naraz się nie mieszczą, więc opis kadrów czeka na podgląd (koszt: kilkanaście sekund).
    pv: dict = {"vision_on": False, "done": False, "thread": None}
    pv_lock = threading.Lock()

    def start_preview() -> None:
        if opt.preview is False or opt.summary not in ("auto", "ollama"):
            return
        tm = opt.summary_model or opt.text_model
        same = opt.vision == "ollama" and opt.vision_model == tm
        if opt.preview is None and opt.vision == "ollama" and not same:
            return                                 # automatycznie tylko bez przerzucania modeli na karcie
        with pv_lock:
            tr0 = tr_box.get("tr")
            if pv["thread"] or pv["done"] or not (tr0 and tr0.segments):
                return
            if pv["vision_on"] and opt.vision == "ollama":   # transkrypcja dopiero w czasie opisu kadrów — za późno
                return
            eng, ctx = Ollama(opt.summary_model or opt.text_model, opt.ollama_host), None
            try:
                if not eng.has_model():
                    log(f"        szybki podgląd pominięty: model {eng.model} jeszcze nie pobrany")
                    pv["done"] = True
                    return
            except LLMError:
                pv["done"] = True
                return
            segs = [asdict(x) for x in tr0.segments]

            def job() -> None:
                from .summary import quick_summary
                t_p = time.time()
                log(f"        szybki podgląd: wstępne streszczenie z mowy ({eng.model})…")
                try:
                    d = quick_summary(eng, segs, f"Title: {src.title or ''}".strip(), info.duration, log, num_ctx=ctx)
                except LLMError as e:
                    d = None
                    log(f"        ! szybki podgląd: {str(e)[:100]}")
                pv["s"] = round(time.time() - t_p, 1)
                if d:
                    pv["po_s"] = round(time.time() - t0, 1)
                    _emit(opt, "wstepne", d)
                    log(f"        szybki podgląd gotowy ({pv['s']:.1f} s; {pv['po_s']:.0f} s od startu)")
                    check_on_gpu(eng, "model tekstowy (podgląd)", log, pre_notes)
                pv["done"] = True
                if opt.vision == "ollama" and not same:
                    eng.unload()                   # miejsce na karcie dla modelu obrazu (inny model niż tekstowy)
            pv["thread"] = threading.Thread(target=job, daemon=True)
            pv["thread"].start()

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
    if opt.vision == "ollama" and not pv_first:
        def preload() -> None:
            if need_whisper and device == "cuda" and speech_thread:
                speech_thread.join()       # najpierw Whisper na karcie (oba naraz mogłyby nie zmieścić się w 8 GB)
            t_l = time.time()
            _vision_ollama(opt).preload()
            timings["obraz_wczytanie_s"] = round(time.time() - t_l, 1)
            log(f"        model obrazu wczytany do karty ({time.time() - t_l:.1f} s)")
            check_on_gpu(_vision_ollama(opt), "model obrazu", log, pre_notes)
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
                _vision_ollama(opt).unload()
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
        start_preview()                          # napisy serwisu są od razu — podgląd startuje teraz, w czasie OCR i kadrów
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
                start_preview()                    # CPU: transkrypcja kończy się w czasie opisu kadrów
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
            check_on_gpu(_vision_ollama(opt), "model obrazu", log, pre_notes)
        threading.Thread(target=note_early, daemon=True).start()

    # 2) KADRY
    t = time.time()
    log("  [2/4] wykrywanie zmian scen i wybór kadrów…")
    plan = plan_for(info.duration, opt.max_frames)
    sample_fps = 2.0 if info.duration <= 600 else 1.0
    if audio_only:
        picks = []                                  # plik dźwiękowy — nie ma z czego robić kadrów
    elif mode == "pelna":
        picks = choose_frames(scene_scores(src.path, sample_fps), info.duration, plan)
    else:                                           # bez analizy scen (na dokumencie 24:50 trwała 34 s) — same miniatury
        from .media import FramePick
        from .modes import thumbnail_times
        picks = [FramePick(t_, ["pokrycie"], 0.0) for t_ in thumbnail_times(info.duration)]
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
    if mode == "pelna":
        gaps.append(f"Kadry co najwyżej co {max_gap:.0f} s — krótkie czynności między kadrami mogły zostać pominięte.")
    timings["kadry_s"] = round(time.time() - t, 1)
    log(f"        {len(frames)} kadrów (pominięto {dropped} powtarzających się; limit {plan.max_frames})"
        if mode == "pelna" else "        plik dźwiękowy — bez kadrów" if audio_only
        else f"        {len(frames)} miniatur (bez analizy scen)")
    if ocr_deferred:
        start_ocr()
    if speech_job:
        speech_thread = threading.Thread(target=speech_job, daemon=True)
        speech_thread.start()

    if speech_thread and not speech_job and opt.vision == "ollama":     # GPU: zwolnij kartę przed modelem obrazu
        log("        czekam na transkrypcję (GPU)…")
        speech_thread.join()

    def find_cues(segs: list[dict], ads: list[dict] | None = None) -> list[dict]:
        from .modes import speech_cues
        if ads is None:                              # streszczenia jeszcze nie ma — reklamy po pewnych sygnałach
            from .story import ad_spans
            from .summary import speech_lines
            ads = ad_spans(speech_lines(segs), set())
        return speech_cues(segs, info.duration, [(a["start"], a["end"]) for a in ads])

    # 0.12.0: kadry WSKAZANE MOWĄ („look at this”, „right here”, „spójrzcie”) — dokładane do wybranych po zmianach sceny
    if mode == "pelna" and opt.vision == "ollama" and tr_box.get("tr") is not None and tr_box["tr"].segments:
        from .modes import extra_cue_picks
        cues = find_cues([asdict(x) for x in tr_box["tr"].segments])
        extra = extra_cue_picks([f.t for f in frames], cues)
        for c in extra:
            fn = f"kadr_{len(frames) + 1:03d}_{ts(c['t']).replace(':', '-')}.jpg"
            extract_frame(src.path, c["t"], out / "kadry" / fn, width=512)
            frames.append(FrameInfo(c["t"], f"kadry/{fn}", ["wskazany_w_mowie"], 0.0, None))
        if extra:
            frames.sort(key=lambda f: f.t)
            log(f"        + {len(extra)} kadr(y) wskazane mową: " + ", ".join(f"{ts(c['t'])} „{c['zwrot']}”" for c in extra))

    # POPRAWKA MOWY (Whisper GPU z podpowiedziami z napisów na ekranie) — od 0.7.6 w czasie opisu kadrów,
    # jeśli na karcie jest miejsce obok modelu obrazu; inaczej po opisie kadrów (jak wcześniej)
    use_hot = not small_model
    ref_box: dict = {}

    def refine_job() -> None:
        if ocr_thread and ocr_thread.is_alive():
            # 0.12.0: w długim filmie Whisper nie czeka w nieskończoność na OCR (pomiar 0.11.9: karta stała 160 s);
            # po 20 s idzie bez podpowiedzi z ekranu — napisy i tak trafią na oś czasu, gdy OCR skończy
            ocr_thread.join(timeout=20 if info.duration > 900 else None)
            if ocr_thread.is_alive():
                log("        poprawka mowy bez podpowiedzi z napisów (OCR jeszcze trwa — długi film)")
        tr0 = tr_box.get("tr")
        if not (wav and device == "cuda" and tr0 and tr0.segments):
            return
        lines = ocr_box.get("lines", []) if opt.ocr and not (ocr_thread and ocr_thread.is_alive()) else []
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
            tm = eng2.timings
            log(f"        poprawka mowy gotowa ({time.time() - t_r:.1f} s"
                + (f": wczytanie Whispera {tm.get('wczytanie_s')} s, rozpoznanie {tm.get('rozpoznanie_s')} s, "
                   f"drugi przebieg {tm.get('drugi_przebieg_s', 0)} s" if tm else "") + ")")
            ref_box["czasy"] = tm
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
        vision_engine = _vision_ollama(opt)
        vision_engine.check()
        if preload_thread and preload_thread.is_alive():
            log("        model obrazu jeszcze się wczytuje…")
            preload_thread.join()
        start_preview()                          # transkrypcja jest (GPU / napisy serwisu) — podgląd teraz
        if pv["thread"] and pv["thread"].is_alive():
            log("        czekam na szybki podgląd (model tekstowy na karcie)…")
            pv["thread"].join(timeout=180)
        pv["vision_on"] = True
        if pv_first:                             # model obrazu na kartę PRZED decyzją o Whisperze obok niego
            t_l = time.time()
            try:
                vision_engine.preload()
                timings["obraz_wczytanie_s"] = round(time.time() - t_l, 1)
                log(f"        model obrazu wczytany do karty ({time.time() - t_l:.1f} s, po podglądzie)")
                check_on_gpu(vision_engine, "model obrazu", log, pre_notes)
            except LLMError:
                pass
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
                    # OCR czyta napisy → model obrazu ich nie przepisuje (krótsza odpowiedź, szybciej)
                    f.vision = (vision_engine.describe_frame(out / f.file, ts(f.t), light=True) if opt.ocr
                                else vision_engine.describe_frame(out / f.file, ts(f.t)))
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
                _emit(opt, "kadry", [{"t": x.t, "file": x.file, "scena": (x.vision or {}).get("scena", "")} for x in frames])

        # dwa kadry naraz tylko, gdy Ollama obsługuje kilka zapytań (OLLAMA_NUM_PARALLEL ≥ 2); inaczej to tylko kolejka
        from concurrent.futures import ThreadPoolExecutor
        workers = min(VISION_WORKERS, vision_engine.parallel)
        _emit(opt, "kadry", [{"t": f.t, "file": f.file, "scena": ""} for f in frames])   # miniatury od razu
        refine_thread = start_refine()             # poprawka mowy (Whisper, GPU) RÓWNOLEGLE z opisem kadrów
        t_v = time.time()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(describe, frames))
        pv["done"] = True                              # po opisie kadrów pełne streszczenie i tak zaraz będzie
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
        if mode == "pelna":
            gaps.append("Analiza obrazu wyłączona — kadry zapisane, ale bez opisów.")
        elif audio_only:
            gaps.append("Plik dźwiękowy: nie ma obrazu — wynik pochodzi z samej mowy.")
        elif mode == "mowa":
            gaps.append("Tryb „Tylko mowa”: obraz i napisy na ekranie nie były analizowane — wynik pochodzi z samej mowy "
                        "(kadry to tylko miniatury).")
        start_preview()
    timings["obraz_s"] = round(time.time() - t, 1)
    if opt.vision == "ollama":
        zasoby["modele"]["opis_kadrow"] = ollama_models(opt.ollama_host)

    if speech_thread and speech_thread.is_alive():
        log("        czekam na transkrypcję…")
        speech_thread.join()
    if info.duration <= 900:
        finish_ocr()
    # długi film: na OCR czekamy dopiero po poprawce mowy — Whisper i wczytanie modelu tekstowego idą w tym czasie
    if "err" in tr_box:
        if wav:
            wav.unlink(missing_ok=True)
        raise tr_box["err"]
    tr = tr_box["tr"]
    timings["transkrypcja_s"] = tr_box.get("s", round(time.time() - t_speech, 1))
    # druga, dokładniejsza transkrypcja: podpowiedzi słów z napisów na ekranie (nazwy, liczby) —
    # pomiar: WER 5,5% → 0–1,4% po polsku. Na GPU to kilka sekund.
    # od 0.7.7: model tekstowy wczytuje się do karty RÓWNOLEGLE z poprawką mowy (Whisper) — na komputerze testowym samo
    # wczytanie trwało ~10 s. Jeśli przez Whispera nie zmieścił się cały na karcie, wczytujemy go ponownie.
    summary_mode = "ollama" if opt.summary == "auto" else opt.summary
    text_box: dict = {}
    text_thread = None
    will_refine = bool(refine_thread) or bool(wav and device == "cuda" and tr.segments)
    if summary_mode == "ollama" and will_refine and vision_engine:
        tmodel = Ollama(opt.summary_model or opt.text_model, opt.ollama_host)
        try:
            ready = tmodel.has_model()
        except LLMError:
            ready = False
        if ready:
            vision_engine.unload()

            def text_preload() -> None:
                from .llm import TEXT_CTX
                t_l = time.time()
                tmodel.preload(TEXT_CTX)
                text_box["s"] = round(time.time() - t_l, 1)
            text_thread = threading.Thread(target=text_preload, daemon=True)
            text_thread.start()
            log("        model tekstowy wczytuje się w tle, w czasie poprawki mowy…")
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
    if info.duration > 900:
        finish_ocr()
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
    if tr.segments:
        from .transcribe import split_long_segments
        n0 = len(tr.segments)
        tr.segments = split_long_segments(tr.segments)
        if len(tr.segments) > n0:
            log(f"        długie zdania podzielone po przecinkach: {n0} → {len(tr.segments)} linii")
            _emit(opt, "transkrypcja", {"jezyk": tr.language, "segmenty": [asdict(x) for x in tr.segments]})
    if wav:
        wav.unlink(missing_ok=True)
    if info.has_audio and not tr.segments:
        gaps.append("Nie rozpoznano mowy — film może mieć muzykę lub inne dźwięki, ale nikt nie mówi "
                    "(albo mowa jest niewyraźna / w innym języku).")
    tech_notes = pre_notes + ([tr.note] if tr.note else [])   # sprawy techniczne (np. Whisper na CPU) — nie luki w analizie
    log(f"        mowa: {len(tr.segments)} segmentów, język: {tr.language} ({tr.engine})")

    if audio_only:
        from .analysis import audio_beats
        beats = audio_beats(tr.segments, info.duration)
    else:
        beats = build_beats(frames, tr.segments, info.duration, ocr_lines)
    meta = {"tytuł": src.title, "autor": src.uploader, "długość": ts(info.duration),
            "język mowy": f"{name_pl(tr.language)} ({tr.language})" if tr.language else None}
    prompt = build_summary_prompt(beats, meta, gaps)             # wersja do wklejenia na claude.ai
    (out / "prompt_dla_claude.md").write_text(prompt, encoding="utf-8")
    json_prompt = build_json_prompt(beats, meta, gaps)           # wersja dla programu (dane do widoku)

    # 4) STRESZCZENIE + TŁUMACZENIA — samodzielnie, lokalnym modelem tekstowym (Claude tylko jako dodatek)
    t = time.time()
    summary_md, summary_engine, summary_data = None, None, None
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
                from .llm import TEXT_CTX
                t_l = time.time()
                if text_thread:
                    text_thread.join()
                    share = text_engine.gpu_share()
                    if share is not None and share < 0.99:
                        log(f"        model tekstowy tylko w {share:.0%} na karcie (obok był Whisper) — wczytuję ponownie")
                        text_engine.unload()
                        text_engine.preload(TEXT_CTX)
                        timings["tekst_wczytanie_s"] = round(text_box.get("s", 0) + time.time() - t_l, 1)
                    else:
                        timings["tekst_wczytanie_s"] = text_box.get("s", 0.0)
                        log(f"        model tekstowy wczytany ({text_box.get('s', 0.0):.1f} s, w tle"
                            + (f", {share:.0%} na karcie" if share is not None else "") + ")")
                else:
                    text_engine.preload(TEXT_CTX)
                    timings["tekst_wczytanie_s"] = round(time.time() - t_l, 1)
                    log(f"        model tekstowy wczytany ({time.time() - t_l:.1f} s)")
                check_on_gpu(text_engine, "model tekstowy", log, tech_notes)
            zasoby["modele"]["streszczenie"] = ollama_models(opt.ollama_host)
        except LLMError as e:
            gaps.append(f"Model tekstowy niedostępny ({e}) — bez streszczenia i tłumaczeń.")
            log(f"        ! {e}")
            text_engine = None
    def run_translations() -> None:
        t_tr = time.time()
        from .translate import translate_segments
        seg_dicts = [asdict(s) for s in tr.segments]
        # słownik terminów piłkarskich, gdy film jest o piłce (pomiar 0.11.9: „juggle” → „gra zręcznościowa”, „foot” → „stop”)
        from .summary import SPORT_TERMS, type_from_content
        sport = type_from_content("", " ".join(x["text"] for x in seg_dicts) + " " + (src.title or "")) == "sport"
        for lang in targets:
            log(f"        tłumaczenie transkrypcji: {tr.language} → {lang} ({len(seg_dicts)} segmentów)…")
            try:
                segs, failed = translate_segments(text_engine, seg_dicts, tr.language, lang, log,
                                                  terms=SPORT_TERMS if sport and lang == "pl" else "")
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
                def polish():                      # polskie linie tylko, jeśli tłumaczenie już gotowe (bez czekania)
                    segs_pl = (translations.get("pl") or {}).get("segmenty")
                    return [x.get("text") for x in segs_pl] if segs_pl else None

                summary_data = staged_summary(text_engine, compact_timeline(src_beats), meta_txt, info.duration, log,
                                              trace=trace, segments=[asdict(x) for x in tr.segments],
                                              ocr=[asdict(l) for l in ocr_lines],
                                              on_partial=lambda k, v: _emit(opt, k, v), polish=polish)
                # kroki pośrednie (fakty, uzupełnienie, opis) — żeby było widać, gdzie coś zginęło
                (out / "streszczenie_kroki.json").write_text(json.dumps(trace, ensure_ascii=False, indent=1),
                                                            encoding="utf-8")
            if summary_data:
                bad = verify_quotes(summary_data, [asdict(x) for x in tr.segments])
                if bad:
                    log(f"        usunięto {bad} cytat(y), których nie ma w transkrypcji")
                from .summary import tidy
                # długi film: więcej rozdziałów i cytatów (0.12.0; do 0.11.9 zawsze najwyżej 6 i 4)
                tidy(summary_data, info.duration, max_quotes=4 if info.duration < 600 else 8,
                     max_chapters=max(6, min(12, round(info.duration / 300))))
            summary_md = to_markdown(summary_data) if summary_data else (raw or None)
            summary_engine = text_name
            if light and summary_data:               # raport z mowy od razu w interfejsie; obraz dojdzie za chwilę
                _emit(opt, "streszczenie_mowa", summary_data)
                timings["raport_z_mowy_po_s"] = round(time.time() - t0, 1)
                log(f"        raport z mowy gotowy ({timings['raport_z_mowy_po_s']:.0f} s od startu) — teraz szybki obraz")
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
    # fakty i cytaty po polsku z tłumaczenia TYCH SAMYCH linii transkrypcji (0.11.10) — nie z przeróbki modelu
    pl_segs = (translations.get("pl") or {}).get("segmenty")
    if summary_data and pl_segs:
        from .story import localize
        n_loc = localize(summary_data, [asdict(x) for x in tr.segments], pl_segs)
        if n_loc:
            log(f"        fakty i cytaty: {n_loc} pozycji po polsku z tłumaczenia linii")
            summary_md = to_markdown(summary_data)
    if text_engine and isinstance(text_engine, Ollama):
        text_engine.unload()

    # ---- TRYB „MOWA + SZYBKI OBRAZ”, faza 2 (0.12.0): opis tylko wybranych kadrów + napisy z tych kadrów ----
    if light:
        try:
            from concurrent.futures import ThreadPoolExecutor
            from .media import FramePick  # noqa: F401
            from .modes import light_picks
            t_v = time.time()
            segs_d = [asdict(x) for x in tr.segments]
            ads = (summary_data or {}).get("reklamy") if summary_data else None
            cues = find_cues(segs_d, ads) if segs_d else []
            starts = [float(c["start"]) for c in (summary_data or {}).get("rozdzialy", [])]
            picks2 = light_picks(info.duration, cues, starts, plan.max_frames)
            vision_engine = _vision_ollama(full_opt)
            vision_engine.check()
            log(f"  [3/4] szybki obraz: {len(picks2)} kadrów ({sum(1 for x in picks2 if 'wskazany_w_mowie' in x['reasons'])} wskazanych mową, "
                f"{sum(1 for x in picks2 if 'poczatek_rozdzialu' in x['reasons'])} na początki rozdziałów, reszta równo) — {full_opt.vision_model}…")
            pre = threading.Thread(target=lambda: vision_engine.preload(), daemon=True)
            pre.start()
            old = {round(f.t, 2): f for f in frames}                    # miniatury z fazy 1 — te same chwile zostają
            new_frames: list[FrameInfo] = []
            for i, pk in enumerate(picks2, 1):
                f0 = old.pop(round(pk["t"], 2), None)
                if f0 is not None:
                    f0.reasons = pk["reasons"]
                    new_frames.append(f0)
                    continue
                fn = f"kadr_s{i:03d}_{ts(pk['t']).replace(':', '-')}.jpg"
                extract_frame(src.path, pk["t"], out / "kadry" / fn, width=512)
                new_frames.append(FrameInfo(pk["t"], f"kadry/{fn}", pk["reasons"], 0.0, None))
            for f0 in old.values():                                      # miniatury, które nie weszły do wyboru
                (out / f0.file).unlink(missing_ok=True)
            frames = new_frames
            _emit(opt, "kadry", [{"t": f.t, "file": f.file, "scena": ""} for f in frames])

            ocr_fast: list = []

            def ocr_frames() -> None:                # napisy tylko z wybranych kadrów (CPU, równolegle z opisem na karcie)
                if not full_opt.ocr:
                    return
                t_o = time.time()
                try:
                    import tempfile
                    from .ocr import CaptionOCR, OcrLine, ensure_models, is_overlay_junk
                    mdir = ensure_models(Path(opt.whisper_root) if opt.whisper_root else out.parent / "_modele", log)
                    reader = CaptionOCR(mdir)
                    with tempfile.TemporaryDirectory(prefix="vidsum_ocr_") as td:
                        for i, f in enumerate(list(frames)):
                            img = extract_frame(src.path, f.t, Path(td) / f"o_{i:03d}.jpg", width=720)
                            for text, score in reader.read(img):
                                if not is_overlay_junk(text):
                                    ocr_fast.append(OcrLine(round(f.t, 2), round(f.t + 1.0, 2), text, round(score, 3)))
                except Exception as e:                # OCR to dodatek
                    tech_notes.append(f"OCR napisów niedostępny ({type(e).__name__}: {str(e)[:100]}).")
                    log(f"        ! OCR: {e}")
                timings["ocr_s"] = round(time.time() - t_o, 1)
            ocr_t = threading.Thread(target=ocr_frames, daemon=True)
            ocr_t.start()
            pre.join()
            timings["obraz_wczytanie_s"] = round(time.time() - t_v, 1)
            check_on_gpu(vision_engine, "model obrazu", log, tech_notes)
            failed2: list[str] = []
            done2 = [0]
            lock2 = threading.Lock()

            def describe2(f: FrameInfo) -> None:
                for _ in (1, 2):
                    try:
                        f.vision = vision_engine.describe_frame(out / f.file, ts(f.t), light=full_opt.ocr)
                        break
                    except LLMError:
                        continue
                with lock2:
                    done2[0] += 1
                    if f.vision is None:
                        failed2.append(ts(f.t))
                    log(f"        {done2[0]}/{len(frames)} kadr {ts(f.t)}: {(f.vision or {}).get('scena', '! błąd')[:90]}")
                    _emit(opt, "kadry", [{"t": x.t, "file": x.file, "scena": (x.vision or {}).get("scena", "")} for x in frames])
            with ThreadPoolExecutor(max_workers=min(VISION_WORKERS, vision_engine.parallel)) as pool:
                list(pool.map(describe2, frames))
            ocr_t.join()
            ocr_lines = sorted(ocr_fast, key=lambda l: l.start)
            if ocr_lines:
                _emit(opt, "napisy", [asdict(l) for l in ocr_lines])
            timings["obraz_s"] = round(time.time() - t_v, 1)
            zasoby["modele"]["opis_kadrow"] = ollama_models(opt.ollama_host)
            if failed2:
                gaps.append(f"Nie udało się opisać kadrów: {', '.join(sorted(failed2))} — w tych miejscach obraz = brak danych.")
            gaps.append(f"Tryb „Mowa + szybki obraz”: streszczenie powstało z mowy; opisano {len(frames)} wybranych kadrów, "
                        "a napisy z ekranu odczytano tylko z nich — to, co było na ekranie między nimi, mogło zostać pominięte.")
            beats = build_beats(frames, tr.segments, info.duration, ocr_lines)
            (out / "prompt_dla_claude.md").write_text(build_summary_prompt(beats, meta, gaps), encoding="utf-8")
            log(f"        szybki obraz gotowy ({timings['obraz_s']:.1f} s: {len(frames)} kadrów, {len(ocr_lines)} napisów z ekranu)")
        except LLMError as e:                         # brak modelu obrazu itp. — raport z mowy zostaje
            gaps.append(f"Szybki obraz nie powstał ({e}) — wynik pochodzi z samej mowy.")
            log(f"        ! szybki obraz: {e}")
    # „Pokazane na ekranie”: co widać, gdy mowa wskazuje na obraz (oba tryby z obrazem)
    if summary_data and not cues and tr.segments and any(f.vision for f in frames):
        cues = find_cues([asdict(x) for x in tr.segments], summary_data.get("reklamy"))   # transkrypcja była po kadrach
    if summary_data and cues and any(f.vision for f in frames):
        from .modes import shown_items
        shown = shown_items(cues, [f for f in frames if f.vision], ocr_lines, [asdict(x) for x in tr.segments])
        if shown:
            summary_data["pokazane"] = shown
            if pl_segs:
                from .story import localize
                localize(summary_data, [asdict(x) for x in tr.segments], pl_segs)
            summary_md = to_markdown(summary_data)
    if vision_engine:
        vision_engine.unload()
    if gpu_watch:
        gpu_watch.stop()
        zasoby["w_trakcie"] = {"najmniej_wolnej_mb": gpu_watch.min_free, "najwiecej_zajetej_mb": gpu_watch.max_used}
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
        "narzedzie": {"nazwa": "Vidsumly", "wersja": __version__},
        "utworzono": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "zrodlo": {"rodzaj": src.kind, "wejscie": src.original, "url": src.webpage_url,
                   "tytul": src.title, "autor": src.uploader, "plik": src.path.name,
                   "sha256": src_sha, "dlugosc_s": round(info.duration, 2),
                   "szerokosc": info.width, "wysokosc": info.height, "audio": info.has_audio, "wideo": info.has_video,
                   "film": film_ref, "opis": src.description, "rozdzialy_autora": src.chapters,
                   "obraz_bez_pasow": (bars_thread.join(timeout=30) or bars.get("r"))},
        "ustawienia": {"whisper": tr.engine, "jezyk": opt.language or "auto", "tlumaczenia": targets, "tryb": asked_mode,
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
        "podglad": {"po_s": pv["po_s"], "s": pv.get("s")} if pv.get("po_s") else None,
        "zasoby": zasoby if zasoby.get("przed") else None,
    }
    # 0.12.0: program sam sprawdza swój wynik (szablon, pokrycie filmu, liczby, obcy język, reklamy, cytaty, tłumaczenie)
    try:
        from . import quality
        issues = quality.check(result)
        result["kontrola"] = {"wynik": quality.score(issues), "uwagi": issues}
        if issues:
            log(f"        kontrola jakości: {quality.score(issues)}/100 — " + "; ".join(i["kod"] for i in issues))
    except Exception as e:                       # kontrola to dodatek — jej błąd nie może zepsuć zapisu analizy
        log(f"        ! kontrola jakości: {type(e).__name__}: {str(e)[:100]}")
    (out / "analiza.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "transkrypcja.srt").write_text(_srt(tr.segments), encoding="utf-8")
    for lang, tdata in translations.items():           # napisy w innych językach (pusta linia = brak tłumaczenia)
        (out / f"transkrypcja.{lang}.srt").write_text(_srt(tdata["segmenty"]), encoding="utf-8")
    (out / "raport.md").write_text(_report_md(result), encoding="utf-8")
    try:                                         # 0.13.1: „Raport z filmu” — dla człowieka i dla innego modelu (note.llm_text)
        from .note import llm_text
        (out / "raport_z_filmu.md").write_text(llm_text(result), encoding="utf-8")
    except Exception as e:
        log(f"        ! plik dla LLM: {type(e).__name__}: {str(e)[:100]}")
    (out / "przebieg.log").write_text("\n".join(trail) + "\n", encoding="utf-8")
    try:                                         # nauka prognozy czasu na tym komputerze (vidsum/eta.py)
        from . import eta
        eta.record(opt.out_root, asked_mode, info.duration, timings.get("razem_s", 0), __version__)
    except OSError:
        pass
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


def _resources_md(z: dict | None) -> list[str]:
    """Raport zasobów karty: co było zajęte przed startem, ile zostało na modele, ile modeli było na karcie."""
    if not z or not z.get("przed"):
        return []
    g = z["przed"]
    L = ["## Zasoby komputera (karta graficzna)", "",
         f"- Karta: **{g['karta']}**, pamięć {g['pamiec_mb']} MB",
         f"- Przed startem: zajęte **{g['zajete_mb']} MB** przez inne programy, wolne na modele **{g['wolne_mb']} MB**"]
    if g.get("modele_poprzednie"):
        L[-1] = (f"- Przed startem: zajęte **{g['zajete_mb']} MB**, z tego modele z poprzedniej analizy (zwolnione na starcie): "
                 + ", ".join(f"`{m['model']}` {m['rozmiar_mb']} MB" for m in g["modele_poprzednie"])
                 + f"; inne programy **{g['zajete_innych_mb']} MB**")
    w = z.get("w_trakcie") or {}
    if w.get("najmniej_wolnej_mb") is not None:
        L.append(f"- W trakcie analizy: najmniej wolnej pamięci {w['najmniej_wolnej_mb']} MB, "
                 f"najwięcej zajętej {w['najwiecej_zajetej_mb']} MB")
    for etap, nazwa in (("opis_kadrow", "Opis kadrów"), ("streszczenie", "Streszczenie")):
        ms = (z.get("modele") or {}).get(etap) or []
        if ms:
            L.append(f"- {nazwa}: " + "; ".join(
                f"`{m['model']}` {m['rozmiar_mb']} MB, na karcie {m['na_karcie_proc']}%"
                + (" (reszta na procesorze — wolniej)" if (m["na_karcie_proc"] or 0) < 99 else "") for m in ms))
    progs = [p["nazwa"] + (f" ({p['pamiec_mb']} MB)" if p.get("pamiec_mb") else "") for p in g.get("programy", [])]
    if progs:
        L.append(f"- Programy korzystające z karty przed startem ({len(progs)}): " + ", ".join(progs))
        L.append("  _Windows nie podaje, ile pamięci karty zajmuje każdy z nich — widać tylko sumę wyżej._")
    if g.get("zajete_innych_mb", g["zajete_mb"]) > 1200:
        L.append(f"- ⚠ Inne programy zajmowały ponad 1,2 GB karty — zamknięcie przeglądarek, Discorda, Steama "
                 "albo wyłączenie w nich przyspieszania sprzętowego zwykle przyspiesza analizę.")
    return L + [""]


def _report_md(r: dict) -> str:
    z = r["zrodlo"]
    L = [f"# {z['tytul'] or z['plik']}", "",
         f"- Źródło: {z['url'] or z['wejscie']}",
         f"- Długość: {ts(z['dlugosc_s'])} · " + ("plik dźwiękowy (bez obrazu)" if z.get("wideo") is False else
                                                  f"obraz {z['szerokosc']}×{z['wysokosc']} · audio: {'tak' if z['audio'] else 'nie'}"),
         f"- Silniki: mowa `{r['ustawienia']['whisper']}`, obraz `{r['ustawienia']['obraz']}`, "
         f"streszczenie `{r['ustawienia']['streszczenie']}`",
         f"- ⏱ Czas analizy: **{_dur(r['czasy'].get('razem_s', 0))}** — {_timing_line(r['czasy'])}"]
    if r.get("podglad"):
        L.append(f"- Szybki podgląd (wstępne streszczenie z mowy): po {_dur(r['podglad']['po_s'])} od startu "
                     f"({r['podglad'].get('s') or 0:.1f} s pracy modelu)")
    L.append("")
    if r["streszczenie"]:
        L += [r["streszczenie"]["markdown"], ""]
    else:
        L += ["## Streszczenie", "", "_Brak — wklej `prompt_dla_claude.md` do Claude albo uruchom z `--streszczenie`._", ""]
    L += ["## Ograniczenia analizy", ""] + [f"- {g}" for g in r["luki"]] + [""]
    k = r.get("kontrola")
    if k is not None:
        L += ["## Kontrola jakości (automatyczna)", ""]
        L += [f"Wynik: **{k['wynik']}/100**" + (" — bez uwag." if not k["uwagi"] else "")]
        L += [f"- {'❌' if i['poziom'] == 'blad' else '⚠'} {i['opis']}" for i in k["uwagi"]] + [""]
    L += _resources_md(r.get("zasoby"))
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
        if b.get("kadr"):                             # plik dźwiękowy nie ma kadrów ani opisu obrazu
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
