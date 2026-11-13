"""Pomiar, gdzie da się odzyskać czas (0.11.9) — na komputerze użytkownika, na gotowej analizie.

Uruchomienie:  Vidsumly.exe --zmierz-czasy "folder analizy"   →  pomiar_czasow.md / .json w tym folderze.

Co mierzy (każdy krok osobno; błąd jednego nie przerywa reszty):
1. Whisper sam na karcie: float16 (tak jak dziś) i int8_float16 — wczytanie, rozpoznanie, zajęta pamięć karty,
   zgodność tekstu z transkrypcją z analizy (żeby nie przyspieszyć kosztem jakości).
2. Whisper RÓWNOLEGLE z opisem kadrów (qwen na karcie, 2 kadry naraz — jak w programie): czy się mieści,
   ile trwa całość, czy opis kadrów zwalnia.
3. Wczytanie modelu tekstowego (dziś ~13 s po opisie kadrów): okno 8192 (jak w programie) i 4096, zimne i ciepłe.
"""
from __future__ import annotations

import difflib
import json
import re
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


class _VramWatch:
    """Najmniej wolnej pamięci karty w czasie pomiaru (nvidia-smi co 0,5 s)."""

    def __init__(self, free_fn):
        self.free_fn, self.min, self._stop = free_fn, None, threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            v = self.free_fn()
            if v is not None:
                self.min = v if self.min is None else min(self.min, v)
            self._stop.wait(0.5)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._t.join(timeout=2)


def similarity(a: str, b: str) -> float:
    """Zgodność słów (0–1) dwóch transkrypcji, bez wielkości liter i interpunkcji."""
    wa, wb = (re.findall(r"[\w']+", x.lower()) for x in (a, b))
    return round(difflib.SequenceMatcher(None, wa, wb).ratio(), 3) if wa and wb else 0.0


def run(folder: Path, log=print, whisper_factory=None, ollama_factory=None, free_fn=None,
        extract=None, compute_types=("float16", "int8_float16")) -> Path:
    from .cuda import free_vram_mb
    from .llm import DEFAULT_TEXT_MODEL, TEXT_CTX, VISION_CTX, Ollama
    from .media import extract_audio
    from .ocr import OcrLine, hotwords_targeted
    from .pipeline import Options
    from .transcribe import WhisperEngine

    free_fn = free_fn or free_vram_mb
    extract = extract or extract_audio
    folder = Path(folder)
    a = json.loads((folder / "analiza.json").read_text(encoding="utf-8"))
    opt = Options()
    ust = a.get("ustawienia") or {}
    vis_model = (ust.get("obraz") or "").split("ollama:")[-1] or opt.vision_model
    txt_model = (ust.get("streszczenie") or "").split("ollama:")[-1] or DEFAULT_TEXT_MODEL
    ref_text = " ".join(x.get("text", "") for x in (a.get("transkrypcja") or {}).get("segmenty") or [])
    lines = [OcrLine(x["start"], x["end"], x["text"], x.get("score", 1.0)) for x in a.get("napisy_ekranowe") or []]
    hot = hotwords_targeted(lines, (a.get("zrodlo") or {}).get("tytul"), ref_text) if lines else ""
    lang = (a.get("transkrypcja") or {}).get("jezyk")
    frames = [folder / f["file"] for f in a.get("kadry") or [] if (folder / f["file"]).is_file()][:8]
    video = folder / ((a.get("zrodlo") or {}).get("film") or "film.mp4")
    wf = whisper_factory or (lambda ct: WhisperEngine(opt.whisper_model, "cuda", compute_type=ct,
                                                      download_root=opt.whisper_root, hotwords=hot or None))
    of = ollama_factory or (lambda m, ctx: Ollama(m, opt.ollama_host, timeout=900, vision_ctx=ctx))
    res: dict = {"karta_wolne_na_starcie_mb": free_fn(), "whisper": {}, "rownolegle": {}, "model_tekstowy": {}}

    def unload_all():
        for m in (vis_model, txt_model):
            try:
                of(m, VISION_CTX).unload()
            except Exception:
                pass
        time.sleep(1.5)

    def whisper_once(ct: str, wav: Path) -> dict:
        eng = wf(ct)
        eng.coverage_hints = [(x.start, x.end) for x in lines] if hot else []
        t0 = time.time()
        with _VramWatch(free_fn) as w:
            tr = eng.transcribe(wav, lang)
        text = " ".join(s.text for s in tr.segments)
        return {"razem_s": round(time.time() - t0, 1), **(eng.timings or {}), "najmniej_wolnej_mb": w.min,
                "zgodnosc_z_analiza": similarity(text, ref_text), "segmentow": len(tr.segments)}

    with tempfile.TemporaryDirectory() as td:
        wav = extract(video, Path(td) / "a.wav")
        # 1) Whisper sam
        unload_all()
        for ct in compute_types:
            try:
                log(f"  Whisper {ct} (sam na karcie)…")
                res["whisper"][ct] = whisper_once(ct, wav)
                log(f"    {res['whisper'][ct]}")
            except Exception as e:
                res["whisper"][ct] = {"blad": f"{type(e).__name__}: {str(e)[:160]}"}
                log(f"    ! {res['whisper'][ct]['blad']}")
        # 2) Whisper równolegle z opisem kadrów (qwen, 2 kadry naraz)
        if frames:
            vis = of(vis_model, VISION_CTX)
            for ct in (None,) + tuple(compute_types):
                key = "sam_opis_kadrow" if ct is None else f"opis_kadrow+whisper_{ct}"
                try:
                    unload_all()
                    vis.preload()
                    free_after_vis = free_fn()
                    log(f"  {key} (wolne po wczytaniu qwen: {free_after_vis} MB)…")
                    t0 = time.time()
                    with _VramWatch(free_fn) as w:
                        th, box = None, {}
                        if ct:
                            def wjob(ct=ct):
                                try:
                                    box["r"] = whisper_once(ct, wav)
                                except Exception as e:      # np. brak pamięci karty obok qwen
                                    box["err"] = e
                            th = threading.Thread(target=wjob, daemon=True)
                            th.start()
                        tv = time.time()
                        with ThreadPoolExecutor(2) as ex:
                            list(ex.map(lambda f: vis.describe_frame(f, "00:00", light=True), frames))
                        vis_s = round(time.time() - tv, 1)
                        if th:
                            th.join()
                        if "err" in box:
                            raise box["err"]
                    res["rownolegle"][key] = {"razem_s": round(time.time() - t0, 1), "opis_kadrow_s": vis_s,
                                              "kadrow": len(frames), "wolne_po_qwen_mb": free_after_vis,
                                              "najmniej_wolnej_mb": w.min, "whisper": box.get("r")}
                    log(f"    {res['rownolegle'][key]}")
                except Exception as e:
                    res["rownolegle"][key] = {"blad": f"{type(e).__name__}: {str(e)[:160]}"}
                    log(f"    ! {res['rownolegle'][key]['blad']}")
        # 3) wczytanie modelu tekstowego
        for ctx, warm in ((TEXT_CTX, False), (TEXT_CTX, True), (4096, True)):
            key = f"ctx{ctx}_{'cieply' if warm else 'zimny'}"
            try:
                eng = of(txt_model, ctx)
                if not warm:
                    unload_all()
                else:
                    eng.unload()
                    time.sleep(1)
                t0 = time.time()
                eng.preload(ctx)
                res["model_tekstowy"][key] = {"wczytanie_s": round(time.time() - t0, 1),
                                              "na_karcie": getattr(eng, "gpu_share", lambda: None)()}
                log(f"  model tekstowy {key}: {res['model_tekstowy'][key]}")
            except Exception as e:
                res["model_tekstowy"][key] = {"blad": f"{type(e).__name__}: {str(e)[:160]}"}
        unload_all()
    (folder / "pomiar_czasow.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    out = folder / "pomiar_czasow.md"
    out.write_text(to_markdown(res, len(frames)), encoding="utf-8")
    return out


def to_markdown(res: dict, n_frames: int) -> str:
    L = ["# Pomiar czasów (Vidsumly)", "", f"Wolna pamięć karty na starcie: {res.get('karta_wolne_na_starcie_mb')} MB", "",
         "## Whisper sam na karcie", "", "| Typ | Wczytanie | Rozpoznanie | Drugi przebieg | Razem | Najmniej wolnej | Zgodność |",
         "|---|---|---|---|---|---|---|"]
    for ct, r in res["whisper"].items():
        L.append(f"| {ct} | " + (" | ".join(str(r.get(k, "—")) for k in ("wczytanie_s", "rozpoznanie_s", "drugi_przebieg_s",
                                                                         "razem_s", "najmniej_wolnej_mb",
                                                                         "zgodnosc_z_analiza")) if "blad" not in r
                                  else f"błąd: {r['blad']} | | | | | ") + " |")
    L += ["", f"## Opis {n_frames} kadrów (2 naraz) — sam i z Whisperem w tym samym czasie", "",
          "| Wariant | Razem | Opis kadrów | Whisper razem | Wolne po qwen | Najmniej wolnej | Zgodność Whispera |",
          "|---|---|---|---|---|---|---|"]
    for k, r in res["rownolegle"].items():
        if "blad" in r:
            L.append(f"| {k} | błąd: {r['blad']} | | | | | |")
            continue
        w = r.get("whisper") or {}
        L.append(f"| {k} | {r['razem_s']} | {r['opis_kadrow_s']} | {w.get('razem_s', '—')} | {r['wolne_po_qwen_mb']} | "
                 f"{r['najmniej_wolnej_mb']} | {w.get('zgodnosc_z_analiza', '—')} |")
    L += ["", "## Wczytanie modelu tekstowego", "", "| Wariant | Wczytanie | Na karcie |", "|---|---|---|"]
    for k, r in res["model_tekstowy"].items():
        L.append(f"| {k} | {r.get('wczytanie_s', r.get('blad'))} | {r.get('na_karcie', '—')} |")
    return "\n".join(L) + "\n"
