"""Postęp analizy na żywo (0.13.2): które etapy są w danym trybie, co program robi teraz, ile procent jest gotowe
i ile zostało — jako liczba, a nie „ok. 3 min”.

Źródło danych to te same linie logu, które program i tak wypisuje (`[1/4] transkrypcja…`, `7/20 kadr…`, `✔ gotowe`),
więc nic w samej analizie się nie zmienia. Zasady:

- Etapy zależą od trybu. „Tylko mowa” i „Sama transkrypcja” nie mają etapu kadrów ani opisu obrazu — w tych trybach
  linia `[2/4] wykrywanie zmian scen…` to tylko kilka miniatur do podglądu i liczy się do przygotowania.
- Etapy idą tylko do przodu (w trybie „Pełna” Whisper pracuje równolegle i jego druga linia `[1/4]` przychodzi po
  `[3/4]` — wtedy ją pomijamy).
- Procent = suma udziałów skończonych etapów + udział bieżącego × jego postęp. Postęp opisu kadrów to liczba
  opisanych kadrów (`7/20`); pozostałe etapy nie podają liczb, więc ich postęp to czas od startu etapu względem
  przewidywanego czasu etapu (najwyżej 95%, dopóki etap się nie skończy).
- Udziały etapów: z poprzednich analiz na tym komputerze (zapisywane razem z czasem całej analizy, vidsum/eta.py),
  a zanim jakieś będą — wartości startowe niżej.
- „Zostało”: na początku prognoza całego czasu z historii (vidsum/eta.py) minus czas, który minął; im dalej, tym
  większą wagę ma tempo tej analizy (czas, który minął × (1 − postęp) / postęp).
"""
from __future__ import annotations

import re
import time

# Wartości startowe udziałów (część całego czasu analizy).
# "pelna": z pomiaru frytki_0114 (tests/data/frytki_0114/analiza.json, film 58 s, razem 78,6 s): pobieranie 5,3 s,
#          opis kadrów z wczytaniem modelu 42,6 s, streszczenie 24,7 s, kadry 1,6 s; reszta to mowa.
# Pozostałe tryby: [szacunek] — bez pomiaru; po pierwszej analizie w danym trybie zastępują je własne pomiary.
DEFAULT_SHARES = {
    "pelna": {"start": 0.07, "mowa": 0.06, "kadry": 0.02, "obraz": 0.54, "streszczenie": 0.31},
    "szybki": {"start": 0.06, "mowa": 0.25, "streszczenie": 0.39, "obraz": 0.30},
    "mowa": {"start": 0.08, "mowa": 0.42, "streszczenie": 0.50},
    "transkrypcja": {"start": 0.10, "mowa": 0.55, "tlumaczenie": 0.35},
}
ORDER = {"pelna": ["start", "mowa", "kadry", "obraz", "streszczenie"],
         "szybki": ["start", "mowa", "streszczenie", "obraz"],
         "mowa": ["start", "mowa", "streszczenie"],
         "transkrypcja": ["start", "mowa", "tlumaczenie"]}
_MODE_BY_LABEL = {"pełna": "pelna", "tylko mowa": "mowa", "mowa + szybki obraz": "szybki",
                  "sama transkrypcja": "transkrypcja"}
_FRAMES = re.compile(r"^\s*(\d+)/(\d+) kadr\b")
_STEP_LINE = re.compile(r"^\s*\[(\d)/4\]\s*(.*)")
_TRAIL = re.compile(r"^\[\s*([\d.]+) s\] (.*)$")


def steps_for(mode: str, summary: bool = True, vision: bool = True, translate: bool = True) -> list[str]:
    """Etapy widoczne w danym trybie (bez tych, które przy tych ustawieniach się nie wykonają)."""
    out = list(ORDER.get(mode, ORDER["pelna"]))
    if not summary:
        out = [s for s in out if s != "streszczenie"]
    if not vision:
        out = [s for s in out if s != "obraz"]
    if not translate:
        out = [s for s in out if s != "tlumaczenie"]
    return out


def normalize_shares(steps: list[str], shares: dict | None, mode: str) -> dict:
    base = DEFAULT_SHARES.get(mode, DEFAULT_SHARES["pelna"])
    raw = {s: float((shares or {}).get(s, base.get(s, 0.1)) or 0.0) for s in steps}
    raw = {s: max(0.01, v) for s, v in raw.items()}
    tot = sum(raw.values()) or 1.0
    return {s: v / tot for s, v in raw.items()}


class Tracker:
    """Stan postępu jednej analizy, karmiony liniami logu."""

    def __init__(self, mode: str = "pelna", summary: bool = True, vision: bool = True, translate: bool = True,
                 clock=time.time):
        self.clock = clock
        self.flags = (summary, vision, translate)
        self.started = clock()
        self.done = False
        self.detail: tuple[int, int] | None = None     # (opisane, wszystkie) przy opisie kadrów
        self._set_mode(mode)

    def _set_mode(self, mode: str) -> None:
        self.mode = mode if mode in ORDER else "pelna"
        self.steps = steps_for(self.mode, *self.flags)
        self.idx = 0
        self.step_start = self.clock()
        self.shares = normalize_shares(self.steps, None, self.mode)

    def set_shares(self, shares: dict | None) -> None:
        self.shares = normalize_shares(self.steps, shares, self.mode)

    @property
    def step(self) -> str:
        return "gotowe" if self.done else self.steps[self.idx]

    def _go(self, name: str) -> None:
        if name in self.steps and self.steps.index(name) > self.idx:
            self.idx = self.steps.index(name)
            self.step_start = self.clock()
            self.detail = None

    def feed(self, line: str) -> None:
        s = str(line)
        low = s.strip().lower()
        if low.startswith("tryb:") and self.idx == 0 and self.mode != "transkrypcja":
            m = _MODE_BY_LABEL.get(low[5:].strip())
            if m and m != self.mode:
                self._set_mode(m)
            return
        if low.startswith("✔ gotowe"):
            self.done = True
            return
        m = _STEP_LINE.match(s)
        if m:
            n, rest = m.group(1), m.group(2)
            target = {"1": "mowa", "2": "kadry", "3": "obraz", "4": "streszczenie"}.get(n)
            if target:
                self._go(target)
            return
        if "tłumaczenie transkrypcji:" in low:
            self._go("tlumaczenie")
            return
        m = _FRAMES.match(s)
        if m and self.step == "obraz":
            self.detail = (int(m.group(1)), int(m.group(2)))

    def fraction(self, total_s: float | None) -> float:
        """Postęp bieżącego etapu 0–1."""
        if self.detail and self.detail[1]:
            return min(1.0, self.detail[0] / self.detail[1])
        if not total_s:
            return 0.0
        expected = self.shares.get(self.step, 0.0) * total_s
        if expected <= 0:
            return 0.0
        return min(0.95, (self.clock() - self.step_start) / expected)

    def percent(self, total_s: float | None) -> float:
        if self.done:
            return 1.0
        before = sum(self.shares[s] for s in self.steps[:self.idx])
        p = before + self.shares[self.step] * self.fraction(total_s)
        return max(0.0, min(0.99, p))

    def remaining(self, total_s: float | None) -> float | None:
        """Sekundy do końca albo None (jeszcze nie wiadomo)."""
        if self.done:
            return 0.0
        elapsed = max(0.0, self.clock() - self.started)
        p = self.percent(total_s)
        forecast = (total_s - elapsed) if total_s else None
        pace = elapsed * (1 - p) / p if p >= 0.05 and elapsed >= 5 else None
        if forecast is None and pace is None:
            return None
        if pace is None:
            return max(0.0, forecast)
        if forecast is None:
            return max(0.0, pace)
        k = min(1.0, p / 0.5)              # do połowy analizy coraz więcej tempa tej analizy, potem już tylko ono
        return max(0.0, (1 - k) * forecast + k * pace)

    def to_dict(self, total_s: float | None) -> dict:
        left = self.remaining(total_s)
        return {"tryb": self.mode, "kroki": self.steps, "teraz": self.step,
                "nr": self.idx + 1 if not self.done else len(self.steps), "z": len(self.steps),
                "proc": round(100 * self.percent(total_s)),
                "szczegol": list(self.detail) if self.detail else None,
                "zostalo_s": None if left is None else round(left, 1)}


def step_times(trail: list[str], mode: str, summary: bool = True, vision: bool = True,
               translate: bool = True) -> dict:
    """Czasy etapów z przebiegu analizy (linie „[  12.3 s] …” z przebieg.log) — do nauki udziałów na tym komputerze."""
    now = [0.0]
    tr = Tracker(mode, summary, vision, translate, clock=lambda: now[0])
    marks: list[tuple[str, float]] = [("start", 0.0)]
    end = None
    for line in trail:
        m = _TRAIL.match(line)
        if not m:
            continue
        now[0] = float(m.group(1))
        for sub in m.group(2).splitlines():
            before_mode, before = tr.mode, tr.step
            tr.feed(sub)
            if tr.mode != before_mode:
                marks = [("start", 0.0)]
            elif tr.done:
                end = now[0]
            elif tr.step != before:
                marks.append((tr.step, now[0]))
    if end is None:
        return {}
    out: dict[str, float] = {}
    for (name, t0), nxt in zip(marks, marks[1:] + [("", end)]):
        out[name] = round(out.get(name, 0.0) + max(0.0, nxt[1] - t0), 1)
    return out
