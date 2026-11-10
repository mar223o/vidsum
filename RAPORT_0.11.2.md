# Vidsumly 0.11.2: wnioski z porównania qwen/gemma, uczciwszy wzorzec, poprawki z przebiegu 0.11.1

## Twój przebieg 0.11.1 (frytki, 22:46)
- Czas 1:28, wstępne streszczenie po 20 s. Inne programy zajmowały 737 MB karty zamiast 1,5 GB.
- Ten przebieg był jeszcze na **qwen3-vl** (`analiza.json` → `"obraz": "ollama:qwen3-vl:4b-instruct"`), więc nie mierzy
  pracy na jednym modelu.
- Poprawki z 0.11.1 zadziałały:
  - krok „Obierz” jest;
  - „łamać się, ale nie pękać”;
  - „przed ostatecznym smażeniem”;
  - „aż będą złote i chrupiące”;
  - „Dodatkowa chrupkość”.
- „Najważniejsze” mówią teraz poprawnie, że ziemniaki rozbija soda (0:25).
- Rozdziały mają lepsze granice: wstępne smażenie 0:45–0:50, smażenie 0:50–0:58.

## Porównanie modeli obrazu (Twój `porownanie_modeli_obrazu.md`)
- Pierwsza ocena dała obu modelom 0,76 i 0 błędów, bo wzorzec znał tylko błędy qwena.
- Twoje opisy sprawdziłem ręcznie z kadrami. Gemma pisze rzeczy, których nie ma:
  - „temperatura żółtka” (0:43): to frytki w oleju;
  - „kremowy płyn i metalowa trzepaczka” (0:48): to frytki na łyżce cedzakowej;
  - „sól do bulionu z widelca” (0:28): to łyżka nad wodą;
  - „Kucharz dodaje napis 'extra crunch'”.
- Dopisałem te słowa do wzorca. Ocena Twoich opisów (scena i czynności):

| | trafność | błędne słowa |
|---|---|---|
| qwen3-vl (pełny opis) | 0,69 | 0 |
| gemma3:4b | 0,76 | 9 |

- **Wniosek: gemma nie zastąpi qwena.** Częściej trafia ogólne słowa (frytki, garnek), ale częściej zmyśla. Jest też
  wolniejsza na kadr (2,58 s wobec 1,99 s). Zostaje qwen3-vl.
- **Nowa hipoteza:** w analizie qwen napisał „zlew”, „nóż”, „czekolada” i „zioła”, a w porównaniu nic z tego. Różnica:
  w analizie z włączonym odczytem napisów program prosi o skrócony opis (max 3 czynności, 5 obiektów).
  - Porównanie ma teraz trzy warianty: `qwen3-vl:4b-instruct@lekki` (jak w analizie), `qwen3-vl:4b-instruct` (pełny),
    `gemma3:4b`.
  - Jeśli pełny opis wyjdzie wyraźnie lepszy przy podobnym czasie, przełączę na niego analizę.
- **Poprawka porównania:** w `porownanie_modeli_obrazu.md` linie „naprawdę” były przesunięte o jeden kadr (np. przy
  0:20 opis kadru 0:19). Sama ocena liczyła się dobrze. Teraz plik pokazuje ten sam przydział co ocena oraz obiekty.

## Poprawki treści (z przebiegu 0.11.1)
- „Powinny łamać się bez pękających” (tłumaczenie transkrypcji) → „Powinny łamać się, ale nie pękać”.
- „solą maldon” → „solą Maldon”.
- „piękna chrupiącą warstwę” → „piękną, chrupiącą warstwę”; „pięknego chrupiącego warstwa” → „pięknej, chrupiącej warstwy”.
- „Połóż na tacę” → „Połóż na tacy”.

## Testy
- 132 testy przechodzą, 3 pominięte (tylko Windows).
- Nowy test: ocena Twoich opisów gemma/qwen z pomiaru 0.11.1 (gemma ≥ 8 błędnych słów w kadrach 0:28, 0:43, 0:48;
  qwen 0) oraz poprawki terminów.

## Czego nie przetestowałem
- **Wariantu `@lekki` na Twojej karcie:** hipoteza o skróconym opisie czeka na Twój pomiar.
- **Ocena z pliku `.md`:** brała tylko scenę i czynności. W JSON-ie są jeszcze obiekty; nowy pomiar policzy je też.
