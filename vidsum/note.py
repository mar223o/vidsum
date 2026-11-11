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
