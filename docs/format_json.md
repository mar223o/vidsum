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
| `zrodlo` | obiekt | `rodzaj` (`plik`/`link`), `wejscie`, `url`, `tytul`, `autor`, `plik`, `sha256`, `dlugosc_s`, `szerokosc`, `wysokosc`, `audio`, `film` (nazwa pliku w folderze wyników albo pełna ścieżka; od 0.5) |
| `ustawienia` | obiekt | użyte silniki: `whisper`, `jezyk`, `obraz`, `streszczenie`, `limit_kadrow`, `pokrycie_co_s`, `uwagi_techniczne` (lista, od 0.2.2), `tlumaczenia` (lista kodów, od 0.7) |
| `transkrypcja` | `{jezyk, jezyk_nazwa, segmenty: [{start, end, text}], tlumaczenia}` | `segmenty` — ZAWSZE oryginał, w języku mowy (kod Whispera, 100 języków); `jezyk_nazwa` po polsku (od 0.7) |
| `transkrypcja.tlumaczenia` | `{kod: {silnik, segmenty: [{start, end, text}], nieprzetlumaczone}}` | od 0.7. Te same segmenty i czasy co oryginał; `text: null` = linii nie udało się przetłumaczyć (nigdy zgadywany tekst). Domyślnie: oryginał angielski → `pl`; polski → `en`; inny → `pl` i `en` |
| `kadry` | lista | `{t, file, reasons, score, vision}` — `reasons` ⊂ `zmiana_sceny`, `aktywnosc`, `pokrycie`; `vision` = obiekt poniżej albo `null` |
| `os_czasu` | lista beatów | patrz niżej |
| `streszczenie` | `{silnik, markdown, dane}` albo `null` | `dane` = streszczenie strukturalne `vidsum.summary/1` (niżej, od 0.5) albo `null` |
| `napisy_ekranowe` | lista `{start, end, text, score}` | napisy odczytane z ekranu przez OCR (od 0.4) |
| `luki` | lista stringów | ograniczenia analizy (np. odstęp między kadrami, brak audio) |
| `czasy` | obiekt | czasy etapów w sekundach (`tlumaczenie_s` od 0.7) |

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


## Streszczenie strukturalne `vidsum.summary/1` (`streszczenie.dane`)
Wszystkie czasy w sekundach. Pola nieużywane przez dany typ filmu są puste.

| pole | typ | opis |
|---|---|---|
| `typ` | `przepis` / `trening` / `poradnik` / `wyklad` / `inne` | rozpoznany typ filmu |
| `tytul`, `tytul_akcent` | string | tytuł po polsku + druga część (puenta) |
| `teza` | string | jedno zdanie: o co chodzi i co z tego wynika |
| `streszczenie` | lista akapitów | od 0.7.8: cel ok. 1:00–1:25 czytania (krócej, gdy film ma mało treści) |
| `do_zapamietania` | string | od 0.7.8: jedno zdanie — najważniejszy wniosek |
| `czas_czytania_s` | liczba | od 0.7.8: szacowany czas czytania streszczenia (190 słów/min) |
| `metoda` | string | od 0.7.8: `kroki z linii mowy` (przepis, poradnik) albo `fakty z fragmentów` |
| `co_masz_zrobic.skladniki` | `[{nazwa, ilosc, zrodlo}]` | **przepisy → dashboard** |
| `co_masz_zrobic.kroki` | `[{t, tekst, zrodlo}]` | kroki z czasem w filmie; od 0.7.8 dla przepisów i poradników każdy krok powstaje z konkretnych linii mowy, a jego liczby muszą w tych liniach paść |
| `co_masz_zrobic.cwiczenia` | `[{nazwa, serie, powtorzenia, t, technika, zrodlo}]` | **treningi → dashboard** |
| `co_masz_zrobic.sprzet / wskazowki / bledy / wnioski` | listy stringów | |
| `co_masz_zrobic.czas` | string | podany albo szacunek |
| `najwazniejsze` | `[{t, tytul, opis, zrodlo}]` | 3–5 pozycji |
| `momenty` | `[{t, tekst}]` | |
| `cytaty` | `[{t, tekst, tlumaczenie}]` | tylko z mowy |
| `rozdzialy` | `[{start, end, tytul, opis, momenty:[{t, tekst}]}]` | od 0.7.8 przy przepisach/poradnikach: granice na zmianie etapu kroków |
| `szczera_ocena` | string | zawsze szacunek |
| `czego_nie_wiadomo` | lista stringów | |
| `pytania` | lista stringów | podpowiedzi do czatu |

`zrodlo` ∈ `mowa`, `obraz`, `mowa+obraz`, `szacunek`.

## `czat.json` (obok `analiza.json`)
Lista wiadomości `{rola: "user"|"asystent", tekst, czas, silnik?}` — rozmowa z filmem z widoku wyniku.
