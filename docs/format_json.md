# Format `analiza.json` — `vidsum.analysis/1`

Stały format wyniku. Zmiana niekompatybilna = nowy numer w polu `schema` (np. `vidsum.analysis/2`).
Wszystkie czasy są w sekundach (liczby), od początku filmu.

## Etykiety źródeł (pole `zrodlo`)
| wartość | znaczenie |
|---|---|
| `mowa` | z transkrypcji (Whisper) |
| `obraz` | z opisu kadru (lokalny model wizyjny) |
| `szacunek` | wniosek, którego nie ma wprost w danych (tylko w streszczeniu) |
| `brak_danych` | nic nie widać / nie słychać — nic nie zostało dopisane |

## Pola główne
| pole | typ | opis |
|---|---|---|
| `schema` | string | zawsze `"vidsum.analysis/1"` |
| `narzedzie` | `{nazwa, wersja}` | |
| `utworzono` | string ISO 8601 | z lokalną strefą czasową |
| `zrodlo` | obiekt | `rodzaj` (`plik`/`link`), `wejscie`, `url`, `tytul`, `autor`, `plik`, `sha256`, `dlugosc_s`, `szerokosc`, `wysokosc`, `audio` |
| `ustawienia` | obiekt | użyte silniki: `whisper`, `jezyk`, `obraz`, `streszczenie`, `limit_kadrow`, `pokrycie_co_s`, `uwagi_techniczne` (lista, od 0.2.2) |
| `transkrypcja` | `{jezyk, segmenty: [{start, end, text}]}` | |
| `kadry` | lista | `{t, file, reasons, score, vision}` — `reasons` ⊂ `zmiana_sceny`, `aktywnosc`, `pokrycie`; `vision` = obiekt poniżej albo `null` |
| `os_czasu` | lista beatów | patrz niżej |
| `streszczenie` | `{silnik, markdown}` albo `null` | |
| `luki` | lista stringów | ograniczenia analizy (np. odstęp między kadrami, brak audio) |
| `czasy` | obiekt | czasy etapów w sekundach |

## `vision` (opis jednego kadru)
`scena` (string), `czynnosci` (lista), `obiekty` (lista), `tekst_na_ekranie` (lista — tylko napisy dodane do filmu), `napisy_na_przedmiotach` (lista — etykiety, opakowania, sprzęt; od 0.2.2), `cialo` (string), `pewnosc` (`wysoka`/`srednia`/`niska`).
Znaki spoza alfabetu łacińskiego wtrącone przez model są zastępowane `[?]`, a `pewnosc` obniżana o jeden poziom.
Puste listy / pusty string = model nic takiego nie rozpoznał.

## Beat (`os_czasu[]`)
```json
{
  "start": 8.5, "end": 16.5,
  "kadr": "kadry/kadr_003_00-08.jpg",
  "powod_kadru": ["zmiana_sceny"],
  "widac":   {"scena": "...", "czynnosci": ["wlewanie"], "obiekty": ["mleko"], "tekst_na_ekranie": [], "cialo": "", "pewnosc": "srednia", "zrodlo": "obraz"},
  "slychac": {"tekst": "Teraz wlewamy dwieście mililitrów mleka.", "zrodlo": "mowa"},
  "zmiana":  {"nowe": ["mleko", "wlewanie"], "zniknely": ["cebula"]}
}
```
Beat trwa od swojego kadru do następnego. Segment mowy należy do beatu, w którym się zaczyna.
`zmiana` jest liczona mechanicznie (różnica zbiorów obiektów i czynności), `null` dla pierwszego beatu lub bez opisu obrazu.

Tryby „przepis” i „ćwiczenia” (faza 3) dodadzą osobne pola (`przepis`, `cwiczenia`) — bez zmiany powyższych.
