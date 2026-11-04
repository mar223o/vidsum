# Wybór lokalnego modelu tekstowego (faza 6)

Model tekstowy robi w VidSum trzy rzeczy: **streszczenie**, **czat z filmem** i **tłumaczenie transkrypcji**.
Ma działać na karcie z 8 GB VRAM (RTX 3070 Ti) obok Whispera i modelu obrazu (po kolei, nie naraz)
i mieć licencję pozwalającą także na sprzedaż.

## Jak mierzone

- Dane: prawdziwa analiza filmu „The Perfect French Fry” (58 s, mowa po angielsku, z błędami rozpoznawania,
  np. „grilled potatoes” zamiast odmiany Agria, „molding chocolate” zamiast soli Maldon).
- Wzorzec: streszczenie Claude z tych samych danych — 14/14 faktów (`tests/bench/data/frytki_wzorzec_claude.json`).
- **Wynik** = liczba znalezionych faktów (z 14: 140 °C, 190 °C, soda, sól, zimna woda, płukanie do czystej wody,
  skrobia ziemniaczana, dużo skrobi w odmianie, tłuszcz z kaczki, 1 cm, lodówka/zamrażarka, dwa smażenia,
  gotowanie do miękkości, mieszanie) **minus 2 za każde zmyślenie** (bakterie, czekolada, węglowodany, grill, piekarnik, ocet).
- Tłumaczenia: 4 zadania (EN→PL, PL→EN, DE→PL, DE→EN), miara chrF (0–100, podobieństwo do wzorca).
- Środowisko: GitHub Actions ubuntu, 4 rdzenie CPU, bez GPU — czasy są więc wielokrotnie dłuższe niż na karcie;
  porównywać można tylko jakość. Skrypt: `tests/bench/llm_bench.py`, workflow `pomiar-modeli-tekstowych`.

## Runda 1 — jeden duży prompt (sposób z 0.6)

| model | rozmiar | fakty | zmyślenia | wynik | typ filmu |
|---|---|---|---|---|---|
| qwen3:8b | 5,2 GB | 7/14 | — | **7** | przepis |
| gemma3:4b | 3,3 GB | 5–6/14 | piekarnik (1 z 2 prób) | 4–5 | przepis |
| Bielik 4.5B v3 (Q8) | 4,8 GB | 8/14 | czekolada, piekarnik | 4 | poradnik |
| Bielik Minitron 7B v3 (Q4) | 4,5 GB | 4/14 | — | 4 | przepis |
| llama3.1:8b | 4,9 GB | 4/14 | — | 4 | przepis |
| qwen3-vl:4b (model obrazu, do 0.6 też streszczał) | 3,3 GB | 4–5/14 | bakterie, czekolada, węglowodany | −2…3 | **trening** (źle) |
| qwen3:4b | 2,5 GB | 3–4/14 | węglowodany | 1–2 | **trening** (źle) |

Wniosek: jeden wielki prompt (oś czasu + ogromny schemat JSON) przerasta małe modele.

## Runda 2 — etapami (od 0.7)

1. **Fakty** — model przechodzi przez zwięzłą oś czasu (mowa, napisy, krótko obraz) i wypisuje kroki, składniki,
   liczby, porady (długie filmy porcjami).
2. **Opis całości** — tytuł, teza, streszczenie, najważniejsze, rozdziały, cytaty — na podstawie gotowych faktów.

| model | fakty | zmyślenia | wynik |
|---|---|---|---|
| qwen3:8b | 10/14 | — | **10** |
| Bielik 4.5B v3 | 9/14 | czekolada* | 7 |
| qwen3:4b | 4/14 | czekolada* | 2 |
| gemma3:4b, qwen3-vl:4b | błędny JSON w drugim etapie → naprawione w 0.7 (ponowna próba, fakty zapisane mimo to); wynik gemma po naprawie niżej | | |
| Granite 3.3 8B | 6/14 | — | 6 (słaby polski: „napekanki”, chrF DE→PL 33) |

\* „czekolada” pochodzi z błędu rozpoznawania mowy („molding chocolate” = sól Maldon), nie z wyobraźni modelu —
ale dla użytkownika to nadal błąd.

## Runda 3 — najpierw tłumaczenie mowy na polski, potem etapy

Pomysł: mały model gubi fakty, bo naraz tłumaczy i streszcza — więc najpierw tłumaczenie mowy na polski.
Wynik (ten sam film, modele po naprawie z rundy 2; „etapy” powtórzone dla porównania):

| model | rozmiar | etapy (oryginał EN) | etapy z polskim tłumaczeniem | tłumaczenia chrF (EN→PL / PL→EN / DE→PL / DE→EN) |
|---|---|---|---|---|
| **gemma3:4b** | 3,3 GB | **11/14, bez zmyśleń → 11** | 10/14, „grill” → 8 | **67 / 81 / 74 / 85** |
| qwen3:8b | 5,2 GB | 10/14 → 10 | 8/14, czekolada → 6 | 48 / 79 / 61 / 88 |
| Bielik Minitron 7B v3 | 4,5 GB | 11/14, czekolada → 9 | 10/14, czekolada → 8 | 46 / 75 / 73 / 86 |
| Bielik 4.5B v3 | 4,8 GB | 9/14, czekolada → 7 | 10/14, czekolada + grill → 6 | 66 / 70 / 67 / 57 |

Tłumaczenie przed streszczeniem **nie pomogło** — przenosi błędy rozpoznawania mowy („grilled potatoes” →
„grillowane ziemniaki”), a z angielskiego oryginału model sam je pomija. Program streszcza więc z oryginału,
a tłumaczenia robi osobno (do transkrypcji i napisów).

Wszystkie lokalne modele nadal czasem dopisują drobiazgi spoza filmu (np. gemma: „ok. 1 kg ziemniaków”, odmiana
„rzepakowa” w tytule; qwen3: „nie przesadzaj z myciem”). Od 0.7 prompt zabrania szacowania ilości i nazw, a źródła są
normalizowane (NAPISY → obraz). To jest główna różnica względem Claude (14/14, bez dopisków).

## Decyzja

**Domyślny model tekstowy: `gemma3:4b`** — najwięcej faktów bez zmyśleń w pomiarze, najlepsze tłumaczenia,
najmniejszy (3,3 GB: mieści się w 8 GB VRAM z dużym zapasem, więc jest też najszybszy na karcie).
Licencja: Gemma Terms of Use — użycie prywatne i komercyjne dozwolone, z zasadami zakazanego użycia Google;
VidSum modelu nie rozprowadza (pobiera go Ollama na komputer użytkownika).

Alternatywy (opcja `--model-tekstowy`): `qwen3:8b` (Apache 2.0, podobna jakość streszczeń, słabsze tłumaczenie na polski,
czasem wtrąca chińskie znaki — program je odrzuca i ponawia), Bielik Minitron 7B (Apache 2.0, polski model).
Do najlepszej jakości: `--streszczenie claude` (dodatek).

Niesprawdzone: jakość na filmach treningowych i wykładach (pomiar tylko na przepisie) oraz czasy na prawdziwej karcie.
