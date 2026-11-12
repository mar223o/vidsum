# Vidsumly 0.12.0: jakość, trzy tryby, pliki dźwiękowe, pierwsze uruchomienie bez PowerShella

Jedno wydanie ze wszystkim z planu trzech wydań (zlecenie z 12.11, 00:23). Prace szły na gałęzi `wip-0.12.0`
(10 commitów), a jakość streszczeń była sprawdzana na **prawdziwym modelu gemma3:4b** na serwerze GitHuba
(bez karty graficznej) na 4 Twoich filmach: tortilla, pancake touch, reel o ubraniach, dokument 24:50.

## Co nowego

### Jakość wyników
- **Typ filmu ustalany raz**, z początku, środka i końca nagrania. Sport rozpoznawany po treści (piłka, żonglerka, przyjęcie).
- **Szablon według typu.** Dokument, wykład i „inne” nie mają już kroków, sprzętu ani składników. Sport: ćwiczenia i technika,
  bez kroków. Słowniczek kuchenny tylko dla przepisów.
- **Długie filmy streszczane część po części** (≈ 4 min). Rozdziały obejmują cały film, a „Najważniejsze” pochodzą
  z różnych jego części. W 0.11.9 opis całości widział tylko ~2,5 minuty z 25.
- **Fakty i cytaty to dosłowne zdania z nagrania**, po polsku z tłumaczenia tych samych linii. Model nie przerabia ich
  własnymi słowami, więc „10 razy cieńsze” nie zamieni się w „grubsze”.
- **Reklamy sponsora** są wykrywane (słowa reklamy, nazwa sponsora, wstęp reklamy), oznaczane jako
  „Reklama mm:ss–mm:ss” i nie trafiają do faktów, wskazówek ani streszczenia.
- **Napisy z ekranu:** bez powtórzeń i bez śmieci z TikToka/Instagrama (liczniki, hashtagi, „Contains:”, daty).
  Poprawki mowy z ekranu tylko wtedy, gdy na ekranie są napisy do mowy.
- **Straże tłumaczenia:** liczby i nazwy miejsc muszą zostać, obce alfabety są usuwane. Błędna linia jest tłumaczona
  drugi raz, a gdy dalej jest zła, zostaje oryginał.
- **Polskie przepisy mówione w 2. osobie** („położysz wrapa”, „dodasz sól”) to kroki, a nie wskazówki.
  Długie zdania z wyliczanką dzielone po przecinkach.
- **Kontrola jakości w każdym wyniku** (ocena 0–100 i lista uwag), w raporcie i w interfejsie.

### Tryby i szybkość
- **Przełącznik przy linku: Pełna / Mowa + szybki obraz / Tylko mowa.** Domyślnie „Pełna”, jak dotąd. Program
  proponuje „Tylko mowa”, gdy nie ma karty NVIDIA albo karta ma mało pamięci.
- **Kadry wskazane mową** („look at this”, „right here”, „zobaczcie”, „tutaj”…) w obu trybach z obrazem.
- **Długie filmy:** OCR jednym przebiegiem (najwyżej 240 klatek), a Whisper nie czeka na OCR.
- **Przewidywany czas do końca analizy** w interfejsie.

### Nowe możliwości
- **Pliki dźwiękowe: mp3, m4a, wav, ogg, opus, flac, aac.** Pełny raport z samej mowy, bez kadrów.
- **Pierwsze uruchomienie bez PowerShella.** Karta na stronie głównej:
  1. instalacja Ollamy: pobranie oficjalnego instalatora, w jego oknie klikasz „Install”;
  2. uruchomienie Ollamy;
  3. pobranie modeli z paskiem postępu;
  4. opcjonalnie „2 zapytania naraz”.
- **Narzędzia:** `--kontrola` (kontrola jakości gotowych analiz → jeden plik), `--streszcz-ponownie` (nowe streszczenie
  zapisanej analizy bez pobierania i kadrów), `--zestaw LISTA.txt`, `--tryb pelna|szybki|mowa`.
- **Dokumenty:** `docs/INSTRUKCJA.md`, `docs/PRYWATNOSC.md`, `docs/licencje.md`, `docs/badania_0.12.md`
  (konkurencja, Whisper, Ollama, reklamy, podpis instalatora — ze źródłami).

## Pomiar na prawdziwym modelu (gemma3:4b, serwer GitHuba bez karty graficznej)

| Film | Kontrola jakości | Uwagi |
|---|---|---|
| Dokument 24:50 | 100/100 | 2 reklamy Delete Me wykryte (05:00–06:16 i 24:20–24:48), fakty z całego filmu |
| Tortilla (PL) | 100/100 | 5 kroków z mowy, ilość „3 jajka” |
| Reel o ubraniach | 100/100 | bez kroków, ćwiczeń i sprzętu |
| Pancake touch | 95/100 | typ „sport”; 1 moment po angielsku (w programie tłumaczony po zakończeniu tłumaczenia linii) |

Po tym pomiarze poprawiłem jeszcze jedną rzecz: model przepisywał czasem angielski fakt jako opis „Najważniejszych”.
Teraz opis jest zastępowany tym faktem po polsku, a kontrola jakości to wykrywa.

**Czasy z serwera nie są Twoimi czasami.** Serwer liczy na procesorze (dokument: streszczenie 14,7 min). U Ciebie liczy karta.

## Testy
211 testów przechodzi, 3 pominięte (tylko Windows). W tym testy „na odtworzeniu”: nowy kod dostaje dokładnie te
odpowiedzi, które prawdziwy model dał na 4 filmach (`tests/data/model_0120`).

## Czego nie przetestowałem
- **Na Twojej karcie nic z 0.12.0 nie było uruchomione.** Nie znam więc prawdziwych czasów trybów
  „Mowa + szybki obraz” i „Tylko mowa”.
- **Instalacji Ollamy przyciskiem** na prawdziwym Windows. Testy sprawdzają logikę na atrapach. Gdyby przycisk zawiódł,
  karta podaje link do ollama.com/download.
- **Pliku mp3 z prawdziwym nagraniem.** Testy używają krótkiego, wygenerowanego pliku.
- **Drugiego komputera** (zwłaszcza bez karty NVIDIA).
- **Granic małego modelu.** Model 4B nadal potrafi źle zrozumieć kontekst. W reelu o ubraniach streszczenie mówi
  o „rozmowie kobiety z mężczyzną”, a w filmie jest jeden mężczyzna i komentarz na ekranie. Poprawiłem opis napisów
  z ekranu w zapytaniu, ale nie sprawdziłem tego ponownie na prawdziwym modelu.
- **Celowo niezrobione:**
  - Whisper int8 (czeka na `--zmierz-czasy` na Twojej karcie);
  - większy model do czatu (brak pomiaru);
  - podpis instalatora (koszt, patrz `docs/badania_0.12.md`).
