"""Notatka z analizy (0.11.5): cały raport jako czysty tekst do wklejenia w inny LLM, Notatnik albo opis.

Źródło to raport.md (streszczenie, kroki, rozdziały, cytaty, oś czasu mowa+obraz+napisy, pełna transkrypcja i tłumaczenie).
Usuwamy tylko to, co poza programem nic nie znaczy: obrazki kadrów, sekcję o karcie graficznej i twarde łamania wierszy.
"""
from __future__ import annotations

import re

_DROP_SECTIONS = ("## Zasoby komputera",)


def note_text(raport: str) -> str:
    out: list[str] = []
    skip = False
    for line in raport.splitlines():
        if line.startswith("## "):
            skip = line.strip().startswith(_DROP_SECTIONS)
        if skip:
            continue
        if re.match(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$", line):        # ![kadr](kadry/…)
            continue
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)\s*", "", line)
        out.append(line.rstrip())
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
    head = "Notatka z analizy filmu (Vidsumly). Źródła informacji: [mowa], [obraz], [mowa+obraz], [szacunek].\n\n"
    return head + text


# ---------------- plik dla LLM (0.13.0) ----------------
def _ts(t) -> str:
    t = int(round(float(t or 0)))
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def _yaml(v) -> str:
    s = str(v if v is not None else "").replace("\n", " ").replace('"', "'")
    return f'"{s}"'


def llm_text(a: dict) -> str:
    """„Raport z filmu” (0.13.1: notatka + plik dla LLM w jednym) — do czytania i do rozmowy z innym modelem
    (NotebookLM, Claude, ChatGPT): metadane, legenda,
    wynik z odwołaniami do numerów linii [L12] i pełna transkrypcja w ponumerowanych liniach (oryginał | tłumaczenie).

    Zasada: wszystko, co jest wnioskiem programu, ma odwołanie do linii albo czasu; opisy kadrów są oznaczone jako
    automatyczne i niepewne. Dzięki temu model, który dostanie ten plik, może cytować dokładne miejsca."""
    z = a.get("zrodlo") or {}
    tr = a.get("transkrypcja") or {}
    segs = tr.get("segmenty") or []
    pl = ((tr.get("tlumaczenia") or {}).get("pl") or {}).get("segmenty") or []
    pl_ok = len(pl) == len(segs)
    s = (a.get("streszczenie") or {}).get("dane") or {}
    starts = [float(x.get("start", 0)) for x in segs]

    def line_of(t) -> int | None:
        if not starts or t is None:
            return None
        t = float(t)
        best = None
        for i, st in enumerate(starts):
            if st <= t + 0.05:
                best = i
            else:
                break
        return (best if best is not None else 0) + 1

    def ref(t, times=None) -> str:
        ns = sorted({line_of(x) for x in (times or [t]) if line_of(x)})
        lab = ",".join(f"L{n}" for n in ns)
        return f"[{lab + ' ' if lab else ''}{_ts(t)}]"

    title = z.get("tytul") or "Analiza filmu"
    src = z.get("url") or z.get("wejscie") or z.get("plik") or ""
    L: list[str] = [f"# Raport z filmu: {title}", "",
                    f"- **Autor:** {z.get('autor') or 'brak danych'}",
                    f"- **Źródło:** {src or 'brak danych'}",
                    f"- **Długość:** {_ts(z.get('dlugosc_s') or 0)} · **język mowy:** {tr.get('jezyk_nazwa') or tr.get('jezyk') or 'brak danych'}"
                    + (f" · **typ filmu:** {s.get('typ')}" if s.get("typ") else ""),
                    f"- **Przygotowane przez:** Vidsumly {(a.get('narzedzie') or {}).get('wersja', '')}, {a.get('utworzono') or ''}".rstrip(", "),
                    "",
                    "> **Jak czytać (dla ludzi i dla AI).** Na górze wynik, na dole pełna transkrypcja w ponumerowanych liniach.",
                    "> `[L12 03:41]` = linia nr 12 transkrypcji, czas 03:41 w filmie — każdy fakt, krok i cytat ma takie odwołanie.",
                    "> Źródła: [mowa] = transkrypcja (automatyczna, możliwe literówki); [napisy] = tekst z ekranu (OCR);",
                    "> [obraz] = automatyczny opis kadru małym modelem (często nieprecyzyjny); [opis] = opis autora pod filmem;",
                    "> [wniosek programu] = streszczenie napisane przez lokalny model — sprawdzaj je z liniami transkrypcji.",
                    "> Fragmenty oznaczone jako reklama nie są treścią filmu. Rozmawiając z AI o tym filmie, proś o odwołania [L…].",
                    ""]
    if s:
        L += ["## Streszczenie [wniosek programu]", ""]
        if s.get("teza"):
            L += [f"**Teza:** {s['teza']}", ""]
        L += [p for x in s.get("streszczenie") or [] for p in (x, "")]
        c = s.get("co_masz_zrobic") or {}
        if c.get("skladniki"):
            L += ["## Składniki"] + [f"- {x.get('nazwa')}: {x.get('ilosc')} [{x.get('zrodlo')}]" for x in c["skladniki"]] + [""]
        if c.get("kroki"):
            L += ["## Kroki"] + [f"{i}. {ref(x.get('t'))} {x.get('tekst')} [{x.get('zrodlo')}]" for i, x in enumerate(c["kroki"], 1)] + [""]
        if c.get("cwiczenia"):
            L += ["## Ćwiczenia"] + [f"- {ref(x.get('t'))} {x.get('nazwa')}" + (f" — {x.get('serie') or '?'} × {x.get('powtorzenia') or '?'}"
                                     if x.get("serie") or x.get("powtorzenia") else "") + (f" — {x['technika']}" if x.get("technika") else "")
                                     for x in c["cwiczenia"]] + [""]
        if c.get("fakty"):
            L += ["## Fakty (dosłownie z transkrypcji)"]
            for x in c["fakty"]:
                orig = x.get("oryginal")
                L.append(f"- {ref(x.get('t'), x.get('czasy'))} ({x.get('rodzaj', 'fakt')}) {x.get('tekst')}"
                         + (f" — oryginał: „{orig}”" if orig and orig != x.get("tekst") else ""))
            L.append("")
        for key, title in (("wskazowki", "Wskazówki"), ("bledy", "Błędy, których unikać"), ("wnioski", "Wnioski [wniosek programu]")):
            if c.get(key):
                L += [f"## {title}"] + [f"- {x}" for x in c[key]] + [""]
        if s.get("rozdzialy"):
            L += ["## Rozdziały"] + [f"- {ref(x.get('start'))}–{_ts(x.get('end'))} **{x.get('tytul')}** — {x.get('opis', '')}"
                                     for x in s["rozdzialy"]] + [""]
        if s.get("najwazniejsze"):
            L += ["## Najważniejsze [wniosek programu]"] + [f"- {ref(x.get('t'))} **{x.get('tytul')}** — {x.get('opis', '')}"
                                                           for x in s["najwazniejsze"]] + [""]
        if s.get("cytaty"):
            L += ["## Cytaty (dosłownie)"] + [f"- {ref(x.get('t'), x.get('czasy'))} „{x.get('tekst')}”"
                                             + (f" (tłum.: {x['tlumaczenie']})" if x.get("tlumaczenie") else "") for x in s["cytaty"]] + [""]
        if s.get("pokazane"):
            L += ["## Pokazane na ekranie, gdy mowa wskazuje na obraz [obraz]"] + [
                f"- {ref(x.get('t'))} mowa: „{x.get('mowa', '')}” → kadr: {x.get('obraz', '')}" for x in s["pokazane"]] + [""]
        if s.get("reklamy"):
            L += ["## Reklamy (nie są treścią filmu)"] + [f"- {_ts(x.get('start'))}–{_ts(x.get('end'))} {x.get('marka', '')}".rstrip()
                                                         for x in s["reklamy"]] + [""]
        if s.get("czego_nie_wiadomo"):
            L += ["## Czego film nie mówi [wniosek programu]"] + [f"- {x}" for x in s["czego_nie_wiadomo"]] + [""]
    if z.get("opis"):
        L += ["## Opis autora pod filmem [opis]", "", str(z["opis"]).strip(), ""]
    if segs:
        L += [f"## Transkrypcja [mowa] — oryginał{' | tłumaczenie na polski' if pl_ok else ''}", ""]
        for i, x in enumerate(segs):
            row = f"[L{i + 1} {_ts(x.get('start'))}] {(x.get('text') or '').strip()}"
            if pl_ok and (pl[i].get("text") or "").strip() and pl[i]["text"].strip() != (x.get("text") or "").strip():
                row += f" | {pl[i]['text'].strip()}"
            L.append(row)
        L.append("")
    ocr = a.get("napisy_ekranowe") or []
    if ocr:
        L += ["## Napisy na ekranie [napisy]", ""]
        seen: set[str] = set()
        for o in ocr:
            key = re.sub(r"\W", "", (o.get("text") or "").lower())
            if not key or key in seen:
                continue
            seen.add(key)
            L.append(f"- {_ts(o.get('start'))} {o.get('text')}")
        L.append("")
    frames = [k for k in a.get("kadry") or [] if (k.get("vision") or {}).get("scena")]
    if frames:
        L += ["## Kadry [obraz] — automatyczny opis, może być nieprecyzyjny", ""]
        L += [f"- {_ts(k.get('t'))} {k['vision']['scena']}" for k in frames]
        L.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(L)).strip() + "\n"
