"""Automatyczna kontrola jakości gotowej analizy (0.12.0).

Po co: do 0.11.9 jakość oceniało się oczami, film po filmie (7 załączników na film). Tu są te same pytania zapisane
jako sprawdzenia, które da się policzyć na `analiza.json`:

- czy szablon pasuje do typu filmu (dokument bez „kroków”),
- czy rozdziały obejmują cały film, a „Najważniejsze” pochodzi z różnych jego części,
- czy każda liczba w opisie jest w mowie albo w napisach z ekranu,
- czy w polskim wyniku nie zostały obcojęzyczne zdania,
- czy reklama nie trafiła do faktów,
- czy cytaty padają w filmie,
- czy „Momenty” nie są kopią opisów kadrów,
- czy tłumaczenie nie zgubiło liczb i nazw miejsc.

Wynik: lista uwag {kod, poziom, opis}; poziom „blad” = wynik wprowadza w błąd, „uwaga” = wynik jest słabszy.
Kontrola niczego nie poprawia — tylko mówi, co jest nie tak (poprawki są w summary.py / story.py / translate.py).
"""
from __future__ import annotations

import re

from .analysis import ts

_AD_TEXT = re.compile(r"\d+\s?% (?:off|rabat)|promo code|kod rabatowy|link in the description|link w opisie|"
                      r"\bsponsor", re.I)


def _texts(s: dict) -> list[tuple[str, str]]:
    """(gdzie, tekst) — wszystko, co użytkownik czyta w wyniku."""
    c = s.get("co_masz_zrobic") or {}
    out = [("teza", s.get("teza", ""))] + [("streszczenie", p) for p in s.get("streszczenie", [])]
    out += [("kroki", k.get("tekst", "")) for k in c.get("kroki", [])]
    out += [("fakty", f.get("tekst", "")) for f in c.get("fakty", [])]
    out += [("wskazówki", x) for x in c.get("wskazowki", [])] + [("wnioski", x) for x in c.get("wnioski", [])]
    out += [("najważniejsze", f"{h.get('tytul', '')}. {h.get('opis', '')}") for h in s.get("najwazniejsze", [])]
    out += [("najważniejsze (opis)", h.get("opis", "")) for h in s.get("najwazniejsze", [])
            if len((h.get("opis") or "").split()) >= 6]         # angielski opis pod polskim tytułem (pomiar CI 12.11)
    out += [("momenty", m.get("tekst", "")) for m in s.get("momenty", [])]
    out += [("rozdziały", f"{r.get('tytul', '')}. {r.get('opis', '')}") for r in s.get("rozdzialy", [])]
    return [(k, t) for k, t in out if t and t.strip()]


def check(analysis: dict, lang: str = "pl") -> list[dict]:
    from .summary import _FIELDS_BY_TYPE, _NUM, _nums, _norm_words, _OBRAZ, compact_timeline, looks_foreign
    from .translate import clean_script, line_problem
    out: list[dict] = []

    def add(kod: str, poziom: str, opis: str) -> None:
        out.append({"kod": kod, "poziom": poziom, "opis": opis})

    dur = float((analysis.get("zrodlo") or {}).get("dlugosc_s") or 0)
    tr = analysis.get("transkrypcja") or {}
    segs = tr.get("segmenty") or []
    speech = " ".join(x.get("text") or "" for x in segs)
    ocr = " ".join(x.get("text") or "" for x in analysis.get("napisy_ekranowe") or [])
    pl = ((tr.get("tlumaczenia") or {}).get(lang) or {}).get("segmenty") or []
    pl_text = " ".join(x.get("text") or "" for x in pl)
    s = ((analysis.get("streszczenie") or {}).get("dane")) or None
    spoken = len(_norm_words(speech)) >= 25

    if s is None:
        add("brak_streszczenia", "blad", "Analiza nie ma streszczenia (model tekstowy nie zwrócił danych).")
    else:
        typ = s.get("typ", "inne")
        c = s.get("co_masz_zrobic") or {}
        # 1) szablon
        keep = _FIELDS_BY_TYPE.get(typ, _FIELDS_BY_TYPE["inne"])
        wrong = [k for k in ("skladniki", "kroki", "sprzet", "cwiczenia", "fakty") if c.get(k) and k not in keep]
        if wrong:
            add("szablon", "blad", f"Typ „{typ}”, a wynik ma pola: {', '.join(wrong)}.")
        from .summary import type_from_content
        guess = type_from_content(typ, speech + " " + str((analysis.get("zrodlo") or {}).get("opis") or ""))
        if guess != typ:
            add("typ_a_tresc", "uwaga", f"Typ „{typ}”, a z treści wynika „{guess}”.")
        short = [k["tekst"] for k in c.get("kroki", []) if len(_norm_words(k["tekst"])) <= 1]
        if short:
            add("kroki_bez_tresci", "uwaga", "Kroki z jednego słowa: " + ", ".join(f"„{x}”" for x in short[:4]))
        # 2) puste
        if not s.get("streszczenie"):
            add("puste_streszczenie", "blad", "Brak tekstu streszczenia.")
        if spoken and not s.get("najwazniejsze"):
            add("brak_najwazniejszych", "uwaga", "Brak sekcji „Najważniejsze”.")
        # 3) rozdziały
        ch = s.get("rozdzialy") or []
        if dur >= 120 and spoken:
            if not ch:
                add("brak_rozdzialow", "blad", "Film ma ponad 2 minuty, a wynik nie ma rozdziałów.")
            else:
                if ch[0]["start"] > 0.1 * dur or ch[-1]["end"] < 0.9 * dur:
                    add("rozdzialy_pokrycie", "blad",
                        f"Rozdziały obejmują {ts(ch[0]['start'])}–{ts(ch[-1]['end'])}, a film trwa {ts(dur)}.")
                gaps = [f"{ts(a['end'])}–{ts(b['start'])}" for a, b in zip(ch, ch[1:]) if b["start"] - a["end"] > 5]
                if gaps:
                    add("rozdzialy_dziury", "uwaga", "Dziury między rozdziałami: " + ", ".join(gaps))
        # 4) „Najważniejsze” z całego filmu
        hl = s.get("najwazniejsze") or []
        if dur >= 300 and len(hl) >= 3:
            fifths = {min(4, int(5 * h["t"] / dur)) for h in hl}
            if len(fifths) < 3 or max(h["t"] for h in hl) < 0.5 * dur:
                add("najwazniejsze_poczatek", "blad",
                    "„Najważniejsze” pochodzi tylko z części filmu: " + ", ".join(ts(h["t"]) for h in hl) + ".")
        # 5) liczby spoza filmu
        have = _nums(speech + " " + ocr + " " + pl_text + " " + str((analysis.get("zrodlo") or {}).get("tytul") or ""))
        bad_nums = []
        for where, text in _texts(s):
            if where in ("rozdziały",):
                continue
            extra = {n.replace(",", ".") for n in _NUM.findall(clean_script(text, lang))} - have
            extra = {n for n in extra if len(n) >= 2}
            if extra:
                bad_nums.append(f"{where}: {', '.join(sorted(extra))}")
        if bad_nums:
            add("liczby_spoza_filmu", "blad", "Liczby, których nie ma w mowie ani w napisach: " + "; ".join(bad_nums[:6]))
        # 6) obcy język w polskim wyniku
        if lang == "pl":
            foreign = [f"{where}: „{text[:60]}”" for where, text in _texts(s) if looks_foreign(text)]
            if foreign:
                add("obcy_jezyk", "blad" if len(foreign) > 2 else "uwaga",
                    f"{len(foreign)} pozycji nie po polsku, np. " + "; ".join(foreign[:3]))
        # 7) reklama w faktach / najważniejszych
        ads = s.get("reklamy") or []
        inside = lambda t: any(a["start"] - 1 <= t <= a["end"] + 1 for a in ads)      # noqa: E731
        leak = [f"fakt {ts(f['t'])}" for f in c.get("fakty", []) if inside(f["t"]) or _AD_TEXT.search(f.get("oryginal") or f["tekst"])]
        leak += [f"najważniejsze {ts(h['t'])}" for h in hl if inside(h["t"])]
        leak += [f"{where}: „{text[:50]}”" for where, text in _texts(s)
                 if where in ("kroki", "wskazówki", "wnioski") and _AD_TEXT.search(text)]
        if leak:
            add("reklama_w_tresci", "blad", "Reklama w treści wyniku: " + ", ".join(leak[:5]))
        # 8) cytaty
        words = _norm_words(speech)
        joined = " ".join(words)
        fake = [q["tekst"][:60] for q in s.get("cytaty", []) if " ".join(_norm_words(q["tekst"])) not in joined]
        if fake:
            add("cytat_nie_z_filmu", "blad", "Cytaty, których nie ma dosłownie w transkrypcji: " + "; ".join(fake[:3]))
        if spoken and len(words) >= 150 and not s.get("cytaty"):
            add("brak_cytatow", "uwaga", "W filmie się mówi, a wynik nie ma cytatów.")
        # 9) kopie opisów kadrów
        scenes = [set(_norm_words(x)) for x in _OBRAZ.findall(compact_timeline(analysis.get("os_czasu") or []))]
        scenes = [x for x in scenes if len(x) >= 3]
        echo = []
        for where, text in _texts(s):
            if where in ("momenty", "najważniejsze", "kroki"):
                w = set(_norm_words(text.split(". ", 1)[-1] if where == "najważniejsze" else text))
                if len(w) >= 3 and any(len(w & sc) >= 0.8 * len(w) for sc in scenes):
                    echo.append(f"{where}: „{text[:50]}”")
        if echo:
            add("opis_kadru_w_tresci", "uwaga", f"{len(echo)} pozycji to przepisany opis kadru, np. " + "; ".join(echo[:2]))

    # 10) tłumaczenie
    if pl and len(pl) == len(segs):
        none = sum(1 for x in pl if not x.get("text"))
        probs = [(a.get("text") or "", b.get("text") or "") for a, b in zip(segs, pl) if b.get("text")]
        bad = [(a, why) for a, b in probs for why in [line_problem(a, clean_script(b, lang), lang)] if why]
        if bad:
            add("tlumaczenie_bledy", "blad", f"{len(bad)} linii tłumaczenia z błędem, np. {bad[0][1]} („{bad[0][0][:50]}”).")
        if none > max(2, 0.05 * len(pl)):
            add("tlumaczenie_luki", "uwaga", f"{none} z {len(pl)} linii bez tłumaczenia (widać oryginał).")
    return out


def score(issues: list[dict]) -> int:
    """0–100: każdy błąd −15, każda uwaga −5 (do porównywania wersji na tym samym zestawie, nie ocena absolutna)."""
    return max(0, 100 - 15 * sum(1 for i in issues if i["poziom"] == "blad") - 5 * sum(1 for i in issues if i["poziom"] == "uwaga"))


def to_markdown(title: str, issues: list[dict]) -> str:
    if not issues:
        return f"**{title}** — kontrola: bez uwag (100/100)\n"
    L = [f"**{title}** — kontrola: {score(issues)}/100"]
    L += [f"- {'❌' if i['poziom'] == 'blad' else '⚠'} `{i['kod']}` {i['opis']}" for i in issues]
    return "\n".join(L) + "\n"
