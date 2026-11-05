# VidSum 0.7.6 — dokładniejsze streszczenie, krótszy czas

## Co się zmieniło

**Jakość**
- Streszczenie i tłumaczenie bez losowości (temperatura 0): ten sam film daje to samo streszczenie.
- Kontrola kompletności: fragmenty filmu, z których nie powstał żaden krok, model czyta jeszcze raz.
- Kontrola liczb: każda liczba z mowy albo z ekranu (140 °C, 190 °C…), której nie ma w krokach, dostaje
  osobne krótkie zapytanie i trafia do kroków.
- Poprawki słów z napisów na ekranie: „maldon chocolate” → „maldon salt”, „Steering” → „Stirring”
  (tylko 1 słowo na 1, gdy obok zgadzają się ≥2 słowa i napis jest na ekranie w tej chwili). Lista poprawek
  w raporcie i w `analiza.json` (`transkrypcja.poprawki_z_napisow`).
- Plik `streszczenie_kroki.json`: odpowiedzi modelu na każdym etapie streszczenia.

**Czas**
- Kadry wycinane PRZED OCR (wcześniej czekały ~18 s na procesor); OCR liczy się w tle w czasie opisu kadrów.
- Poprawka mowy (Whisper) w czasie opisu kadrów, gdy na karcie jest ≥2,5 GB wolnej pamięci (nvidia-smi);
  inaczej po opisie kadrów, jak wcześniej.
- Opis całości w dwóch częściach naraz (przy OLLAMA_NUM_PARALLEL ≥ 2).
- Stały kontekst modeli (obraz 3072, tekst 8192): Ollama nie przeładowuje modelu między zapytaniami.
- W logu: czas wczytania modelu obrazu i tekstowego, faktyczna równoległość opisu kadrów.

## Pomiar streszczenia (tests/bench/summary_bench.py, gemma3:4b, CPU w GitHub Actions, oś czasu frytek z 0.7.5)

Fakty z 16 (140 °C, 190 °C, soda, sól, zimna woda, płukanie, skrobia, odmiana Agria, sól Maldon, kaczy tłuszcz,
1 cm, lodówka, dwa smażenia, miękkość, mieszanie, dużo skrobi); zmyślenia −2.

| Wersja | Przebieg 1 | 2 | 3 | Kroki | 140 °C w wyniku |
|---|---|---|---|---|---|
| 0.7.5 (stara) | 12 | 12 | 7 | 9–16 | 0 z 3 |
| 0.7.6, jedno zapytanie naraz | **16** | 15 | 15 | 14–19 | 3 z 3 |
| 0.7.6, 3 zapytania naraz | 14 | 14 | 14 | 15–20 | 3 z 3 |

Zmyśleń: 0 we wszystkich przebiegach. Odrzucony pomysł: dzielenie krótkiego zapisu na małe części do liczenia
naraz — 7 kroków zamiast 14–20 (pomiar), wycofane.

## Czego nie przetestowałem
- Czasu na karcie RTX (CI nie ma GPU). Szacunek dla frytek: ok. 1:20–1:30 (było 1:45).
- Czy poprawka mowy zmieści się na karcie obok modelu obrazu — program sprawdza wolną pamięć i w razie
  czego robi ją po opisie kadrów.
