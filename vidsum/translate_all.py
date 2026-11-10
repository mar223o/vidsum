"""Tłumaczenie CAŁEJ analizy na żądanie (0.9.0): streszczenie, kroki, składniki, rozdziały, najważniejsze, momenty,
cytaty (ich tłumaczenie), pytania, opisy kadrów i transkrypcja — PL ↔ EN.

Zasady jak w tłumaczeniu transkrypcji: oryginał zostaje nietknięty, czasy bez zmian, a tekst, którego nie udało się
przetłumaczyć, zostaje w oryginale i jest policzony w "nieprzetlumaczone" (nie wstawiamy zgadywanego tekstu).
Wynik ląduje w analiza.json pod "tlumaczenie_calosci"[jezyk].
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
from typing import Callable

from .translate import translate_segments

LANGS = ("pl", "en")

# pola streszczenia do tłumaczenia: ścieżka → tekst (listy napisów i listy słowników z danym kluczem)
_TEXT = ("tytul", "teza", "do_zapamietania", "szczera_ocena")
_STR_LISTS = ("streszczenie", "czego_nie_wiadomo", "pytania")
_DICT_LISTS = (("najwazniejsze", ("tytul", "opis")), ("momenty", ("tekst",)), ("rozdzialy", ("tytul", "opis")),
               ("cytaty", ("tlumaczenie",)))
_TODO_STR = ("sprzet", "wskazowki", "bledy", "wnioski")
_TODO_DICT = (("skladniki", ("nazwa", "ilosc")), ("kroki", ("tekst",)), ("cwiczenia", ("nazwa", "tekst", "opis")))
_KEEP = {"brak danych"}                       # znaczniki programu, nie treść — tłumaczone niżej słownikiem
_MARK = {"en": {"brak danych": "no data"}, "pl": {"no data": "brak danych"}}


def _slots(dane: dict, kadry: list[dict]) -> list[tuple[list, object, str]]:
    """(pojemnik, klucz/indeks, tekst) każdego napisu do tłumaczenia — podmiana w miejscu po tłumaczeniu."""
    out: list[tuple[list, object, str]] = []

    def add(box, key):
        v = box[key] if isinstance(box, list) else box.get(key)
        if isinstance(v, str) and v.strip() and v.strip() not in _KEEP:
            out.append((box, key, v))

    for k in _TEXT:
        add(dane, k)
    for k in _STR_LISTS:
        for i in range(len(dane.get(k) or [])):
            add(dane[k], i)
    for k, keys in _DICT_LISTS:
        for x in dane.get(k) or []:
            if isinstance(x, dict):
                for kk in keys:
                    add(x, kk)
    todo = dane.get("co_masz_zrobic") or {}
    add(todo, "czas")
    for k in _TODO_STR:
        for i in range(len(todo.get(k) or [])):
            add(todo[k], i)
    for k, keys in _TODO_DICT:
        for x in todo.get(k) or []:
            if isinstance(x, dict):
                for kk in keys:
                    add(x, kk)
    for f in kadry:
        v = f.get("vision") or {}
        add(v, "scena")
        for k in ("czynnosci", "obiekty"):
            for i in range(len(v.get(k) or [])):
                add(v[k], i)
    return out


def source_hash(r: dict) -> str:
    """Odcisk oryginału (streszczenie + opisy kadrów + transkrypcja). Inny odcisk = tłumaczenie nieaktualne."""
    d = ((r.get("streszczenie") or {}).get("dane")) or {}
    k = [(f.get("t"), (f.get("vision") or {})) for f in r.get("kadry") or []]
    t = [(x.get("start"), x.get("text")) for x in ((r.get("transkrypcja") or {}).get("segmenty") or [])]
    raw = json.dumps([d, k, t], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def is_current(r: dict, tgt: str) -> bool:
    """Tłumaczenie istnieje i powstało z obecnej wersji oryginału (stare, sprzed 0.11, bez odcisku — uznawane)."""
    res = (r.get("tlumaczenie_calosci") or {}).get(tgt) or {}
    return bool(res) and res.get("zrodlo_hash", source_hash(r)) == source_hash(r)


def translate_analysis(engine, r: dict, tgt: str, log: Callable[[str], None] = lambda s: None,
                       progress: Callable[[str], None] = lambda s: None, cache: dict | None = None) -> dict:
    """Zwraca {"jezyk", "silnik", "dane", "kadry", "transkrypcja", "nieprzetlumaczone", "czas_s"}.

    Streszczenie i opisy kadrów program pisze po polsku: na "pl" zostają bez zmian, na "en" są tłumaczone.
    Transkrypcja: oryginał, gdy już jest w tym języku; gotowe tłumaczenie z analizy, gdy jest; inaczej tłumaczona."""
    if tgt not in LANGS:
        raise ValueError(f"nieobsługiwany język: {tgt}")
    t0 = time.time()
    dane = copy.deepcopy(((r.get("streszczenie") or {}).get("dane")) or {})
    kadry = copy.deepcopy(r.get("kadry") or [])
    failed = 0
    mem = dict(cache or {})                               # oryginał → tłumaczenie z poprzedniego razu
    reused = 0
    if tgt != "pl":
        slots = _slots(dane, kadry)
        todo = [x for x in slots if x[2] not in mem]       # tylko teksty nowe albo zmienione od ostatniego tłumaczenia
        reused = len(slots) - len(todo)
        progress(f"streszczenie i kadry: {len(todo)} tekstów" + (f" (bez zmian: {reused})" if reused else ""))
        if todo:
            uniq = list(dict.fromkeys(x[2] for x in todo))
            segs, failed = translate_segments(engine, [{"start": i, "end": i, "text": t} for i, t in enumerate(uniq)],
                                              "pl", tgt, log, chunk=20)
            for orig, seg in zip(uniq, segs):
                if seg["text"]:
                    mem[orig] = seg["text"]
        for box, key, orig in slots:
            box[key] = mem.get(orig) or orig              # bez tłumaczenia — zostaje oryginał (policzony w failed)
    marks = _MARK[tgt]
    for x in (dane.get("co_masz_zrobic") or {}).get("skladniki") or []:
        if isinstance(x, dict) and x.get("ilosc") in marks:
            x["ilosc"] = marks[x["ilosc"]]

    tr = r.get("transkrypcja") or {}
    segs = tr.get("segmenty") or []
    have = ((tr.get("tlumaczenia") or {}).get(tgt) or {})
    if tr.get("jezyk") == tgt:
        tsegs, tfail, how = segs, 0, "oryginał"
    elif have.get("segmenty") and not have.get("nieprzetlumaczone"):
        tsegs, tfail, how = have["segmenty"], 0, "z analizy"
    elif segs:
        progress(f"transkrypcja: {len(segs)} zdań")
        tsegs, tfail = translate_segments(engine, segs, tr.get("jezyk"), tgt, log)
        tsegs = [{**t, "text": t["text"] if t["text"] else o["text"]} for t, o in zip(tsegs, segs)]
        how = "przetłumaczona"
    else:
        tsegs, tfail, how = [], 0, "brak"
    return {"jezyk": tgt, "silnik": f"ollama:{getattr(engine, 'model', '?')}", "dane": dane,
            "kadry": [{"t": f.get("t"), "file": f.get("file"), "vision": f.get("vision")} for f in kadry],
            "transkrypcja": {"segmenty": tsegs, "zrodlo": how}, "nieprzetlumaczone": failed + tfail,
            "czas_s": round(time.time() - t0, 1), "zrodlo_hash": source_hash(r), "pamiec": mem,
            "z_pamieci": reused}
