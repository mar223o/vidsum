# Vidsumly 0.11.0: kolejka, porządne zamykanie, Ustawienia, wynik w dwóch językach, czarne pasy

Realizacja „MASTER EXECUTION PROMPT” (19 etapów). Poniżej to, co rzeczywiście jest w kodzie i przetestowane, oraz
uczciwie to, czego nie zrobiłem albo nie mogłem sprawdzić.

## Audyt (skrót)
- **Kolejka:** jeden wątek i kolejka FIFO w pamięci. Brakowało usuwania, kolejności, pauzy, ponawiania i ochrony
  przed dublami. Po zamknięciu programu kolejka znikała.
- **Zamykanie:**
  - X kończył program przez `os._exit`;
  - procesy ffmpeg/ffprobe uruchomione przez `subprocess.run` mogły zostać jako sieroty (Windows nie zabija procesów
    potomnych razem z rodzicem);
  - Ollamy program nie uruchamia, więc jej nie zamyka. To było i zostaje poprawne.
- **Interfejs:**
  - ustawienia schowane w zwijanym bloku na stronie głównej;
  - „Zakończ” jako przycisk w pasku;
  - „Ostatnio” (karty wyników) na stronie głównej;
  - wskaźnik „ffmpeg”;
  - komunikaty błędów z serwera tylko po polsku.
- **Teksty interfejsu:** jeden słownik (`I18N`) już istniał. Sprawdziłem skryptem cały JS: poza słownikiem nie ma
  zaszytych polskich tekstów.
- **Aktualizacja:** opis w sekcji F.

## A. Zrealizowane zmiany
1. **Kolejka filmów** (sekcja D).
2. **Zamykanie programu i procesy potomne** (sekcja E).
3. **Wstępne streszczenie zawsze**, bez przełącznika (sekcja C).
4. **Tłumaczenie wyniku po analizie** (PL → EN): tylko teksty nowe albo zmienione, a oryginał jest źródłem prawdy
   (sekcja C).
5. **Zakładka Ustawienia** zamiast „Zakończ”. Program zamkniesz w Ustawieniach → „Zamknij program” albo krzyżykiem okna.
6. **Strona główna:** pole na film, linki i kompaktowa kolejka. Ostatnie wyniki są tylko w Bibliotece.
7. **„Silnik wideo” zamiast „ffmpeg”** w pasku. Szczegóły (wersja i ścieżka ffmpeg) są w Ustawieniach → Diagnostyka.
8. **Tryb Wideo:** streszczenie po lewej stronie filmu, a rozbicie (zakładki) pod spodem na całą szerokość. Na telefonie
   wszystko jest w jednej kolumnie.
9. **Zakładki „Przepis / Najważniejsze / Momenty…”** są teraz osobnymi przyciskami z odstępami i ikonami. Zaznaczona
   zakładka ma akcent. Logika zakładek bez zmian.
10. **Czarne pasy:** wykrywane ostrożnie i ukrywane w odtwarzaczu. Program sam liczy czarne wiersze i kolumny
    na 5 klatkach, bo filtr `cropdetect` jest tylko w kompilacjach GPL ffmpeg (wyłapał to test na Windows).
    Przycisk „Pokaż cały kadr” je przywraca. Plik filmu
    się nie zmienia.
11. **Czat:** stałe odmowy w języku pytania („Nie mam wystarczających informacji, aby odpowiedzieć na to pytanie.”, „To
    nie wynika z analizowanego nagrania.”). Wnioski mają etykietę „Wniosek (nie pada wprost w filmie):”. Gdy mowa
    i kadr się nie zgadzają, wygrywa transkrypcja, a kadr jest opisany jako niepewny.
12. **Komunikaty błędów z programu po angielsku** w angielskim interfejsie. Szczegół techniczny po dwukropku zostaje bez
    zmian. Pytanie przy zamykaniu okna jest w języku interfejsu.
13. **Ikony SVG** zamiast znaków ☾ ☀ ◐ ◉ ≡ ▤ w pasku, przełączniku trybów i kolejce. Kolejka i ustawienia mają
    widoczny fokus z klawiatury.
14. **Sprzątanie:** przy starcie znikają wysłane filmy spoza kolejki, starsze niż doba.

## B. AI
- **Modele:**
  - mowa: faster-whisper `large-v3-turbo` (CUDA);
  - kadry: `qwen3-vl:4b-instruct`;
  - streszczenie, czat i tłumaczenie: `gemma3:4b` (Ollama).
  - Wszystko działa lokalnie, Claude jest opcją.
- **Pipeline:**
  - OCR (CPU) i Whisper (GPU) od razu;
  - wstępne streszczenie z mowy;
  - kadry i opis obrazu;
  - kroki z linii mowy z kontrolą liczb i terminów;
  - pełne streszczenie i kontrole: cytaty, fałszywe „brakuje”, liczby spoza filmu;
  - na końcu tłumaczenie na EN.
- **Poprawki w tej wersji:**
  - reguły czatu (pkt 11 w sekcji A);
  - w 0.10.x: czat dostaje transkrypcję z czasami, kroki i opisy kadrów zamiast całego streszczenia, a liczba
    z jednostką spoza filmu dostaje ostrzeżenie;
  - przy tym samym modelu do obrazu i tekstu: wspólny kontekst, czyli bez przeładowań.
- **Szybkość: nie mam nowego pomiaru.** Tutaj nie ma karty graficznej ani Ollamy. Ostatni Twój pomiar (0.9.0, frytki
  58 s): 1:20 bez podglądu, 1:36 z podglądem (podgląd po 29 s). Teraz podgląd jest zawsze, więc spodziewam się czasu
  jak w drugim przypadku. To szacunek z Twojego pomiaru, nie nowy wynik.
- **Ograniczenia:**
  - model 4B potrafi pomylić szczegóły; kontrole usuwają część takich błędów, ale nie wszystkie;
  - opisy kadrów z qwen bywają złe i dlatego nie trafiają do kroków.

## C. Streszczenia
- **Pierwsza wersja:** zaraz po transkrypcji, z etykietą „wstępne”, zanim ruszy opis obrazu.
- **Poprawianie:**
  - kroki dochodzą w trakcie etapu 4/4;
  - pełne streszczenie (mowa + obraz + kontrole) zastępuje wstępne w tym samym miejscu, bez przeskoku strony (test
    w przeglądarce);
  - nie ma dodatkowych, niemal identycznych wersji.
- **Tłumaczenie:**
  - po pełnym streszczeniu, w wątku kolejki, zanim ruszy następny film (karta graficzna po kolei);
  - wynik jest już widoczny, tłumaczenie dochodzi w tle;
  - wyłączysz je w Ustawieniach → Modele AI.
- **Synchronizacja:**
  - tłumaczenie ma odcisk oryginału (streszczenie, kadry, transkrypcja);
  - inny odcisk = „nieaktualne”;
  - ponowne tłumaczenie bierze niezmienione teksty z pamięci i tłumaczy tylko zmienione (test).
- **Niezrobione: „cała analiza najpierw w języku oryginału”.**
  - Model czyta transkrypcję w oryginale (bez tłumaczenia przed analizą), ale streszczenie, kroki i opisy kadrów pisze
    od razu po polsku.
  - Przestawienie na „najpierw angielskie streszczenie, potem polskie tłumaczenie” to przepisanie ok. 1500 linii
    dopracowanych poleceń i kontroli. Kontrole są pod polski: odmiany liczebników, poprawki terminów („parzenie” →
    „wstępne smażenie”), „brakuje …”.
  - Bez Ollamy i karty nie mogłem sprawdzić, czy jakość nie spadnie, więc tego nie zmieniłem.
  - Tłumaczenia na żywo w trakcie analizy (np. wstępnego streszczenia) też nie ma, bo konkurowałoby z modelem obrazu
    o pamięć karty.

## D. Interfejs
- **Zmienione widoki:**
  - pasek: Analizuj / Biblioteka / Ustawienia, wskaźniki, język, motyw;
  - strona główna;
  - nowa strona Ustawienia;
  - wynik: tryb Wideo, zakładki, czarne pasy;
  - kolejka.
- **Język:**
  - jeden słownik PL/EN;
  - zmiana w pasku albo w Ustawieniach przerysowuje cały program bez restartu: wskaźniki, kolejkę, ustawienia,
    komunikaty i pytanie przy zamykaniu;
  - test w przeglądarce sprawdza, że po przełączeniu na EN na stronie głównej i w Ustawieniach nie zostaje polski
    tekst, i odwrotnie.
  - **Wyjątek:** surowy dziennik analizy („Na żywo: co teraz analizuje”) i opisy błędów z narzędzi są po polsku,
    bo to zapis techniczny.
- **Strona główna:** krótki nagłówek, pole na pliki i linki, kolejka. Bez statystyk dla ozdoby.
- **Kolejka:**
  - zwijany panel z podsumowaniem („1 w toku · 2 czeka”);
  - każda pozycja ma miniaturę albo ikonę, nazwę, status i etap („Etap 2/4 · kadry”) z czasem;
  - procentów nie pokazuję, bo program ich nie zna; prawdziwy procent jest tylko przy wysyłaniu pliku;
  - akcje: wyżej/niżej, usuń (oczekujące), ponów (błąd/przerwane), podgląd na żywo / otwórz;
  - kolejkę można wstrzymać i wznowić;
  - trwający film jest wyróżniony;
  - ten sam film drugi raz nie trafia do kolejki;
  - analizy idą po jednej, bo dwie naraz nie zmieszczą się w 8 GB karty;
  - stan jest w `%LOCALAPPDATA%\VidSum\kolejka.json` (zapis atomowy).
- **Ustawienia:**
  - Interfejs (język, motyw);
  - Analiza (język mowy, model mowy, OCR, obraz, maks. kadrów);
  - Modele AI (silnik streszczenia, model tekstowy, model obrazu, wersja angielska wyniku);
  - Pliki i pobieranie (folder wyników z przyciskiem „Otwórz”, ciasteczka);
  - Diagnostyka (silnik wideo, Ollama, model tekstowy, karta, Claude Code);
  - Aktualizacje, O programie, Zamykanie.
  - Tylko opcje, które program obsługuje.
- **Wskaźnik „Silnik wideo”** (dawniej „ffmpeg”): pokazuje, czy są `ffmpeg` i `ffprobe`. Bez nich program nie wytnie
  dźwięku ani kadrów i nie odczyta formatu filmu. To wskaźnik dostępności, nie pracy w danej chwili. Brak = czerwony,
  z opisem.

## E. Procesy i stabilność
- **Zamykanie** (krzyżyk okna, „Zamknij program” albo nowsza wersja programu):
  1. kolejka przestaje przyjmować filmy;
  2. kolejka zapisuje się razem z trwającym filmem, który po starcie będzie pierwszy, a kolejka wraca wstrzymana;
  3. kończą się procesy potomne (ffmpeg/ffprobe): najpierw grzecznie, po 3 s twardo;
  4. z karty zwalniane są modele przerwanej analizy (`keep_alive: 0`), a sama Ollama działa dalej;
  5. serwer się zamyka, a proces kończy;
  6. ślad trafia do `zamkniecie.json` (co przerwano, ile procesów zakończono, które modele zwolniono).
- **Windows: obiekt zadania (Job Object)** z „zabij przy zamknięciu”.
  - Gdy program skończy się w dowolny sposób (także awaria albo Menedżer zadań), Windows kończy jego procesy potomne,
    także ffmpeg uruchomiony przez yt-dlp.
  - Poza obiektem zadania startują: nowa instancja po aktualizacji, instalator i okno Edge.
- **Trwająca analiza przy zamknięciu:** okno pyta (w języku interfejsu), a film wraca do kolejki. Analiza zaczyna się
  od nowa, bo etapy w połowie nie są wznawiane. Gotowy film, który właśnie się tłumaczy, nie wraca do kolejki.
- **Ponowne uruchomienie:**
  - stały port i token;
  - kolejka odtworzona i wstrzymana, z komunikatem „wróciła po ponownym uruchomieniu”;
  - wysłany film, którego plik zniknął, jest pomijany.

## F. Optymalizacja i aktualizacje
1. **Czy aktualizacje usuwają stare pliki?** Tak.
   - Aktualizacja „kod” podmienia cały folder `vidsum`: stary przenosi do `vidsum.stare` i usuwa, a resztki sprząta
     przy starcie.
   - Instalator ma `[InstallDelete] {app}\vidsum`.
   - Biblioteki Pythona zmienia tylko pełny instalator.
2. **Jak działa aktualizacja?**
   - Sprawdza wydanie na GitHubie (sha256).
   - Jeśli zmienił się tylko kod: paczka ZIP i podmiana folderu z kopią zapasową (przy błędzie wraca stara wersja),
     potem ponowne uruchomienie.
   - W przeciwnym razie: instalator.
3. **Co zoptymalizowałem?**
   - ffmpeg pod kontrolą programu (rejestr procesów zamiast `subprocess.run`);
   - tłumaczenie bez powtórek niezmienionych tekstów;
   - przy tym samym modelu obrazu i tekstu: jeden kontekst (bez przeładowań);
   - sprzątanie starych wysłanych plików;
   - usunąłem martwy kod strony głównej (stare ustawienia w `<details>`, lista „Ostatnio”, przycisk „Zakończ”).
   - Nie usuwałem modułów: każdy ma użycia (sprawdzone importy), np. `vision_bench` (`--pomiar-kadrow`) i `mcp_server`
     (`--mcp`).
4. **Co można jeszcze bezpiecznie zoptymalizować?**
   - Kilka nieużywanych kluczy w słowniku tekstów (`settings`, `recent`).
   - Pojedyncze stare style CSS po dawnym widoku zadań (`.job`).
   - Oba te punkty to kosmetyka.
5. **Czy aktualizacja może uszkodzić dane?** Według kodu nie.
   - Ustawienia, token, kolejka i modele są w `%LOCALAPPDATA%\VidSum`, a wyniki w `Dokumenty\VidSum`; aktualizacja ich
     nie dotyka.
   - Nowe pola są dopisywane do istniejących plików; stare analizy i tłumaczenia (bez odcisku) działają.
   - **Zależności:** bez zmian (`requirements.txt` ten sam).

## G. Testy
- **128 testów zaliczonych, 0 niezaliczonych, 3 pominięte** (tylko Windows: w tym nowy test obiektu zadania; uruchomią
  się w GitHub Actions na Windows).
- **Nowe testy:**
  - kolejka: wstrzymanie, kolejność, usuwanie, bez dubli, błąd jednego filmu i ponowienie, zapis i odtworzenie po
    zamknięciu w trakcie analizy;
  - zamykanie: proces potomny zakończony, przerwany film w kolejce, modele zwolnione, Ollama nietknięta, po zamknięciu
    nic nowego nie startuje;
  - Windows: dziecko ginie z programem, proces „odłączony” przeżywa;
  - tłumaczenie po analizie przed następnym filmem oraz wyłączenie w Ustawieniach;
  - ponowne tłumaczenie tylko zmienionych tekstów i nieaktualność po zmianie oryginału;
  - czarne pasy: wykryte dokładnie (2,4:1 w 16:9); bez pasów i ciemna scena → nic nie ruszane (także na Windows
    z kompilacją LGPL ffmpeg);
  - przeglądarka (1280 i 390 px): kolejka na stronie głównej (przesuń, usuń, wstrzymaj), Ustawienia z diagnostyką,
    pełne przełączenie PL ↔ EN bez polskich tekstów w wersji angielskiej, brak poziomego przewijania; przycisk pasów
    w odtwarzaczu;
  - czat: odmowy i oznaczanie wniosków w obu językach;
  - stare ślady sprzątane, kolejka nietknięta.
- **Benchmarki:** brak nowych (sekcja B).

## H. Wymaga dalszej pracy
1. **Streszczenie najpierw w języku oryginału** (sekcja C): niezrobione, z podanego tam powodu.
2. **Pomiar na Twojej karcie:** czas analizy z podglądem zawsze włączonym, gemma3:4b jako model obrazu (0.10.2),
   jakość czatu z nowymi regułami.
3. **Wznawianie analizy od przerwanego etapu:** teraz przerwany film zaczyna się od nowa.
4. **Zamykanie na prawdziwym Windows z oknem:** test obiektu zadania przejdzie w CI. Zamknięcia okna WebView2
   w trakcie analizy nie sprawdziłem.
5. **Komentarze i opis z prawdziwego YouTube** (z 0.10.0): nadal tylko na atrapie.
6. **Surowy dziennik analizy** jest po polsku także w angielskim interfejsie.
