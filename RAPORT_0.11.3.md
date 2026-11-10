# Vidsumly 0.11.3: wynik na jednym ekranie, link do filmu, nowe Ustawienia

## Link do filmu
W nagłówku wyniku, przed datą, jest **„Otwórz film na YouTube”** (Instagram / TikTok — odpowiednio). Link otwiera
oryginał w przeglądarce, a nie w oknie programu. Pliki z dysku nie mają linku.

## Wynik na jednym ekranie (ekrany od 1000×620 px)
- **Strona się nie przewija.** Wynik zajmuje dokładnie wysokość okna:
  - na górze zwarty nagłówek: tytuł w jednej linii, teza w max 2 liniach, przyciski w jednym rzędzie, a przełącznik
    trybów obok;
  - pod nim trzy kolumny i **każda przewija się sama** (streszczenie, film z czatem, rozbicie).
- **Tryby:**
  - **Wideo:** streszczenie | film + czat | rozbicie.
  - **Zbalansowany:** streszczenie | film + czat | szerokie rozbicie.
  - **Czytaj:** szerokie streszczenie | szerokie rozbicie | mały film + czat.
  - **Tryb kinowy:** film na całe okno, kolumny ukryte.
- **Szersze kafelki:** gdy kolumna ma ≥ 560 px, kroki, punkty, momenty i rozdziały układają się w 2 kolumny (≥ 900 px:
  w 3), a składniki w 2. Mniej przewijania przy tej samej treści.
- Kliknięcie czasu nie przewija już strony do filmu, bo film jest zawsze widoczny.
- Czytany fragment nie skacze przy aktualizacji, także w przewijanej kolumnie (test).
- Mniejsze okna i telefon: jak dotąd, jedna kolumna i przewijana strona.

## Ustawienia od nowa
- Po lewej lista sekcji z ikonami: Interfejs, Analiza, Modele AI, Pliki i pobieranie, Diagnostyka, Aktualizacje,
  O programie, Zamykanie.
- Po prawej jedna sekcja naraz, bez długiej strony do przewijania. Program pamięta ostatnio otwartą sekcję.
- **Zapis od razu po zmianie pola**, bez przycisku „Zapisz”. Pojawia się komunikat „Zapisano” i pole na chwilę świeci
  na zielono.
- Klucz GitHub (niepotrzebny) schowany w „Aktualizacje” pod rozwijanym elementem.
- Na telefonie sekcje układają się w dwie kolumny przycisków nad treścią.

## Testy
- 132 testy przechodzą, 3 pominięte (tylko Windows).
- **Nowe:**
  - na 1280 i 1000 px we wszystkich trzech trybach strona się nie przewija, a kolumny mieszczą się w oknie;
  - link do filmu ma dobry adres;
  - Ustawienia: zmiana pola zapisuje się sama (sprawdzone w ustawieniach programu), sekcje się przełączają, język
    zmienia się w całości.

## Czego nie przetestowałem
- **Wyglądu w oknie programu (WebView2) na Twoim ekranie.** Zrzuty są z Chromium 1280×900 i 1000×900.
- **Ekranów niższych niż 620 px:** wtedy wraca zwykłe przewijanie strony.
