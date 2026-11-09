# VidSum 0.8.1: ciemny wygląd, nowa ikona, raport karty, rozdziały według treści

## Wygląd
- **Ciemny motyw** domyślnie (jak Vimeo/YouTube). Przycisk ☾/☀ w górnym pasku przełącza: ciemny → jasny → jak
  w systemie. Wybór zostaje zapamiętany.
- **Momenty z miniaturami**: przy każdym momencie jest kadr z tej chwili filmu. Kliknięcie przewija film.
- Pod streszczeniem są przyciski **Kopiuj** (cały tekst do schowka) i **Tłumacz** (pyta czat o tłumaczenie
  streszczenia).
- **„Otwórz w przeglądarce”**: przycisk w górnym pasku okna programu otwiera ten sam widok w domyślnej przeglądarce.
- Wynik na żywo, zakładki i tryby (Wideo / Zbalansowany / Czytaj) działają jak w 0.8.0.

## Nowa ikona
Własny projekt na bazie podesłanych inspiracji (nie kopia żadnego z logo): gradient niebieski → fiolet → róż,
biała ramka kadru, trzy linie streszczenia, trójkąt „play” i żółta iskra. Ikona pojawia się:
- na pasku zadań i w tytule okna,
- na skrócie w menu Start i na pulpicie (przy pierwszym uruchomieniu 0.8.1 program sam podmienia ikonę starych
  skrótów),
- w instalatorze i w „Dodaj lub usuń programy”,
- jako ikonka karty w przeglądarce.

## Raport zasobów karty graficznej
Przed analizą program sprawdza kartę (`nvidia-smi`), a w trakcie co 2 s mierzy wolną pamięć. W raporcie
(`raport.md`) i w programie („Jak to przeanalizowano”) widać:
- kartę i jej pamięć, ile było zajęte przed startem i ile zostało wolne na modele,
- programy, które w tej chwili używały karty (np. Firefox, Discord, Steam),
- najmniej wolnej pamięci w trakcie analizy,
- dla każdego modelu (opis kadrów, streszczenie): rozmiar i jaka część była na karcie (100% = szybko, mniej =
  część liczy procesor, wolniej).

Gdy przed startem inne programy zajmują ponad 1,2 GB, w przebiegu pojawia się ostrzeżenie z ich listą. W 0.7.9
to (~850 MB zajęte przez inne programy) było przyczyną 3:40 zamiast ~1:30.

## Streszczenie: dokładniejsze
Poprawki dla błędów z Twojego pomiaru 0.8.0:
- **Rozdziały przypięte do kroków według treści**, a nie tylko po czasie. Tytuł rozdziału musi pasować do kroku
  w pobliżu (±15 s). Tytuł bez pasującego kroku jest pomijany. W 0.8.0 „Gotowanie ziemniaków” wisiało nad
  krojeniem. Na Twoim wyniku 0.8.0 po zmianie: Wstęp 0:00–0:05, Przygotowanie 0:05–0:14, Krojenie i moczenie
  0:14–0:24, Gotowanie 0:24–0:45, Smażenie 0:45–0:58.
- **„Najważniejsze” przypięte do kroku** po liczbach i treści. W 0.8.0 model wpisał 140 jako czas, przez co
  punkt pokazywał 00:58. Teraz punkt ze 190 °C wskazuje 0:52.
- **Wskazówki z kawałków zdań sklejane w całość.** W 0.8.0 „Posiada bardzo wysoką zawartość skrobi.” i „Bardzo
  niską zawartość wody.” były dwiema osobnymi wskazówkami.
- **Etapy w streszczeniu po kolei, bez mieszania kroków.** Nowe reguły w poleceniu: opisuj etapy w kolejności
  kroków, nie łącz faktów z różnych kroków i nie podawaj proporcji, których nie ma w filmie. W 0.8.0 streszczenie
  łączyło „podsmażanie (par-fry)” z „wodą z sodą”.
- Słowniczek terminów: „par-fry/blanch” to wstępne smażenie **w oleju**, nie gotowanie w wodzie. Dodatkowo stała
  poprawka: gdy w filmie pada „par-fry”, a nie ma mowy o parze, „parzenie/parowanie” w streszczeniu zmienia się na
  „wstępne smażenie” (pomiar pokazał, że model tak tłumaczył).
- **Krok z „1 cm” już nie odpada.** Model pisał „około jednego centymetra”. Program rozpoznawał tylko „jeden”, więc
  uznawał, że krok zgubił liczbę, i go usuwał. Teraz rozpoznaje odmiany liczebników („jednego”, „dwóch”, „pięciu”…).

## Pomiar (frytki, ta sama transkrypcja i napisy co z Twojego komputera)
`tests/bench/summary_bench.py`, model gemma3:4b, u mnie na procesorze. Wyniki modelu są takie same jak na karcie,
czasy nie.

| | 0.8.0 (Twój wynik) | 0.8.1 przebieg 1 | 0.8.1 przebieg 2 | 0.8.1 z poprawką „1 cm” |
|---|---|---|---|---|
| fakty | 16/16 | 15/16 (brak 1 cm) | 15/16 (brak 1 cm) | **16/16** |
| zmyślenia | 1 zdanie (podsmażanie w wodzie z sodą) | 0 | 0 | 0 |
| 140 °C / 190 °C w dobrych krokach | tak / tak | tak / tak | tak / tak | tak / tak |
| czas czytania streszczenia | 1 min 04 s | 52 s | 55 s | 45 s |

- Mieszanie etapów z 0.8.0 („podsmażanie w wodzie z sodą”) nie wystąpiło w żadnym przebiegu. W jednym streszczenie
  wprost mówi „blanszowanie frytek w oleju”.
- W dwóch przebiegach model napisał „parzenie”/„parowanie” zamiast „wstępne smażenie”. Poprawkę terminu sprawdziłem
  na tekście z ostatniego przebiegu: „…a następnie wstępne smażenie lub blanszowanie…”.
- Polszczyzna streszczenia bywa koślawa („kroczone”, „wysokoskrębowe”). To granica modelu 4B. Fakty i liczby się
  zgadzają.

## Testy
- 94 testy przechodzą (2 pominięte, bo działają tylko na Windows). Nowe testy obejmują:
  - rozdziały według treści (pomijanie tytułu bez pasującego kroku),
  - przypięcie „najważniejszych”,
  - sklejanie wskazówek,
  - odczyt karty z `nvidia-smi` (zajęte/wolne, programy),
  - modele na karcie,
  - sekcję zasobów w raporcie,
  - przycisk „Otwórz w przeglądarce” (tylko adresy wewnątrz programu),
  - ikonę bez tokenu,
  - odmiany liczebników w kontroli kroków,
  - poprawkę „parzenie” → „wstępne smażenie”.
- Przeglądarka (Chromium): wynik na żywo na 1280 i 390 px. Czytany fragment się nie przesuwa, nie ma błędów
  w konsoli ani poziomego przewijania na telefonie.
- Zrzuty ekranu wyniku w motywie ciemnym i jasnym, na Twoim wyniku 0.8.0 (kadry podstawione).
- Wydanie budowane na Windowsie (GitHub) sprawdza:
  - czy okno programu się ładuje,
  - czy plik ikony jest w instalacji,
  - czy skrót w menu Start ma nową ikonę.

## Czego nie przetestowałem
- **Pomiaru zasobów na prawdziwej karcie NVIDIA.** Testowałem na zapisanym wyjściu `nvidia-smi`, w tym na tym,
  które mi przysłałeś. U mnie nie ma karty.
- **Ikony na Twoim pasku zadań i skrótach.** Windows czasem trzyma starą ikonę w pamięci podręcznej. Jeśli zostanie
  stara, pomaga wylogowanie i ponowne zalogowanie.
- **Przycisku „Otwórz w przeglądarce” w prawdziwym oknie programu** (WebView2). Sprawdziłem go w przeglądarce
  testowej i w testach serwera.
- **Czasu całej analizy na Twojej karcie.** Liczba zapytań do modelu jest taka sama jak w 0.8.0, ale nie
  mierzyłem tego.
- **Innych filmów niż frytki.**
