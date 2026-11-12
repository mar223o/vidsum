"""Przewidywany czas analizy (0.12.0) — „zostało ok. 3 min” w interfejsie.

Model jest celowo prosty: czas całej analizy ≈ a + b × długość filmu, osobno dla każdego trybu. Program uczy się
na TYM komputerze: po każdej analizie zapisuje (tryb, długość, czas) do `czasy_trybow.json` w folderze wyników i od
trzech analiz w danym trybie liczy a i b z własnej historii (ostatnie 30). Wcześniej używa wartości startowych:

- „pelna”: a = 50 s, b = 0,35 — dopasowane do pięciu pomiarów użytkownika na RTX 3070 Ti (0.11.5–0.11.9):
  14 s → 54 s, 58 s → 69 s, 62 s → 82 s, 88 s → 85 s, 1490 s → 568 s;
- „mowa” i „szybki”: NIEZMIERZONE — ostrożne szacunki (25 s + 0,12 × długość; 40 s + 0,20 × długość), które pierwsze
  trzy analizy zastąpią prawdziwymi liczbami.

To prognoza, nie obietnica: interfejs pokazuje ją jako „ok.”, a gdy analiza trwa dłużej — „jeszcze chwila”.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {"pelna": (50.0, 0.35), "mowa": (25.0, 0.12), "szybki": (40.0, 0.20)}
FILE = "czasy_trybow.json"
KEEP = 60


def _load(root: Path) -> list[dict]:
    try:
        d = json.loads((Path(root) / FILE).read_text(encoding="utf-8"))
        return [x for x in d if isinstance(x, dict)] if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def record(root: Path, mode: str, duration: float, total: float, version: str = "") -> None:
    """Dopisuje pomiar po udanej analizie (najwyżej KEEP ostatnich)."""
    if not (duration and total and duration > 0 and total > 0):
        return
    rows = _load(root) + [{"tryb": mode, "dlugosc_s": round(float(duration), 1), "razem_s": round(float(total), 1),
                           "wersja": version}]
    Path(root).mkdir(parents=True, exist_ok=True)
    (Path(root) / FILE).write_text(json.dumps(rows[-KEEP:], ensure_ascii=False), encoding="utf-8")


def fit(samples: list[tuple[float, float]], default: tuple[float, float]) -> tuple[float, float]:
    """a, b z pomiarów (najmniejsze kwadraty); przy < 3 pomiarach albo filmach tej samej długości — wartości startowe
    przeskalowane do średniej z pomiarów (ten komputer jest po prostu szybszy albo wolniejszy)."""
    a0, b0 = default
    if not samples:
        return default
    if len(samples) >= 3:
        n = len(samples)
        mx = sum(x for x, _ in samples) / n
        my = sum(y for _, y in samples) / n
        sxx = sum((x - mx) ** 2 for x, _ in samples)
        if sxx > 1e-6 and (max(x for x, _ in samples) / max(1.0, min(x for x, _ in samples))) >= 1.5:
            b = sum((x - mx) * (y - my) for x, y in samples) / sxx
            a = my - b * mx
            if a >= 3.0 and b >= 0.01:
                return round(a, 1), round(b, 4)
    ratio = sum(y / max(1.0, a0 + b0 * x) for x, y in samples) / len(samples)
    ratio = max(0.3, min(4.0, ratio))
    return round(a0 * ratio, 1), round(b0 * ratio, 4)


def predict(root: Path | None, mode: str, duration: float) -> dict:
    """→ {"razem_s": prognoza całej analizy, "z_pomiarow": ile własnych pomiarów stoi za prognozą}."""
    mode = mode if mode in DEFAULTS else "pelna"
    rows = [x for x in (_load(root) if root else []) if x.get("tryb") == mode][-30:]
    samples = [(float(x["dlugosc_s"]), float(x["razem_s"])) for x in rows
               if isinstance(x.get("dlugosc_s"), (int, float)) and isinstance(x.get("razem_s"), (int, float))]
    a, b = fit(samples, DEFAULTS[mode])
    return {"razem_s": round(max(10.0, a + b * max(0.0, float(duration))), 1), "z_pomiarow": len(samples)}
