# Vidsumly 0.11.5: poprawki z przebiegu „najszybciej”, notatka, panele według typu, mądrzejszy czat

## Twój przebieg 0.11.4 „najszybciej” (frytki 58 s)
- **Całość 1:19** (ze wstępnym streszczeniem było 1:42). Ustawienie działa.
- Do 1:15 brakuje ok. 4 s. To mieści się w wahaniach wczytywania modeli (11–15 s).
- Największy zapas, ok. 14 s: poprawka mowy (Whisper) czeka na koniec opisu kadrów. Na karcie było 1641 MB wolnego,
  a próg to 2500 MB. Bez pomiaru tego nie zmieniam.

## Poprawione błędy (sprawdzone na zapisanych odpowiedziach modelu z Twojego przebiegu)
| Było | Jest |
|---|---|
| „technik wstępnego smażenia oraz wstępnego smażenia” (dubel z naszej poprawki) | „technik wstępnego smażenia” |
| „Podsmaż wstępnie (wstępne smażenie) frytek” | „Podsmaż wstępnie frytek” |
| Mowa „Drain just lightly…”, a napis na ekranie „dust lightly with” → w streszczeniu „mąki… do odsączania” | mowa „Dust just lightly…”, a w tłumaczeniu „Oprósz lekko mąką ziemniaczaną” |
| „Rozgrzej olej w garnku, gdy osiągnie około 140 stopni” | „Rozgrzej olej w garnku.” + „Gdy osiągnie około 140 stopni, wrzuć frytki.” |
| „Podsmaż wstępnie, blanszuj w oleju” | „Podsmaż wstępnie albo blanszuj w oleju.” |
| brak oleju w składnikach | „olej — brak danych [mowa]” (tylko gdy olej pada w mowie) |
| „idealny fryk z ziemniaków”, „To idealna frytki francuskie” | „idealna frytka” |
| „I i sól”, „olej na patelni” (w filmie garnek), „Zagotuj garnek wody” | „I sól”, „w garnku”, „Zagotuj wodę w garnku” |
| „Peel.” zginęło, gdy model dostał 2 linie do poprawy naraz | poprawki pojedynczo; krótkie polecenia od razu ze słownika |
| opisy kadrów: „na indukcyjnej plastry”, „wycierka”, „zimniaki”, „garnka” | poprawiona forma słowa; treść (np. „czekolada”) zostaje widoczna |

## Nowe w programie
- **Przy dodawaniu filmu** wybierasz **Najszybciej** albo **Ze wstępnym streszczeniem**. Wybór działa dla tego filmu
  i zostaje na następne. Z Ustawień to pole zniknęło.
- **Kopiuj notatkę** i **⤓ pobierz notatkę (.md)**: cały raport jako czysty tekst do wklejenia w inny LLM, Notatnik albo opis.
  Zawiera streszczenie, kroki, rozdziały, cytaty, oś czasu (mowa, obraz, napisy), pełną transkrypcję i tłumaczenie.
  Nie zawiera obrazków ani sekcji o karcie graficznej.
- **Kopiuj prompt** (wcześniej „Kopiuj prompt dla Claude”): ten sam surowy prompt co dotąd.
- Usunięte: „Podsumuj przez Claude” (Claude zostaje jako opcja silnika w Ustawieniach) i „Pobierz JSON”
  (plik `analiza.json` dalej jest w folderze wyników).
- **Kopiuj transkrypcję** w zakładce transkrypcji: kopiuje w wybranym języku, z czasami.
- **Panele według typu filmu.** Nowe typy:
  - **sport** (np. piłka) → „Ćwiczenia i elementy techniki”;
  - **dokument** → „Fakty, liczby, osoby, daty”, każdy fakt z czasem i rodzajem.

  Przepis dalej pokazuje składniki, a trening ćwiczenia.
- **Czat:**
  - zna składniki z ilościami, sprzęt, ćwiczenia, fakty, wskazówki i rozdziały;
  - ma zasady dla przeliczania porcji (tylko z ilości z filmu, oznaczone jako wniosek);
  - pytania o skład, kalorie i zamienniki oznacza jako wiedzę ogólną z zastrzeżeniem;
  - przy pytaniach o moment odpowiada z czasem;
  - proponuje pytania według typu, np. „Jakie składniki są potrzebne?”, „Przelicz składniki na 4 porcje”,
    „Jaki jest skład i ile to ma kalorii?”.
- `VidSum.exe --zapytaj "folder analizy" "pytanie" [model]` zadaje pytanie do czatu z terminala i podaje czas.
  Posłuży do porównania większego modelu czatu.

## Porównanie modeli obrazu (Twój pomiar)
- qwen lekki: 1,77 s/kadr, 3 błędne słowa.
- qwen pełny: 2,75 s/kadr. Test pokazał 0 błędów, ale ręcznie widać „zupa” i „rękawice”.
- gemma: 9 błędnych słów.

**Decyzja:** zostaje qwen lekki. Błędy obrazu nie trafiają do kroków ani streszczenia.

## Testy
- 143 testy: 140 przechodzi, 3 pominięte (tylko Windows).
- Nowe:
  - odtworzenie Twojego przebiegu 0.11.4 na nowym kodzie;
  - poprawka „Drain → Dust” z napisu (na Twoich danych zmienia tylko to jedno słowo);
  - tryb wybierany przy linku i pliku;
  - notatka;
  - panele „sport” i „dokument” w przeglądarce;
  - propozycje pytań w czacie.

## Czego nie przetestowałem
- Odpowiedzi czatu na prawdziwym modelu: tu nie ma Ollamy ani karty. Sprawdziłem tylko, co trafia do modelu.
- Rozpoznawanie typów „sport” i „dokument” przez gemmę na prawdziwych filmach.
- Kopiowanie do schowka i pobieranie notatki w oknie programu na Windows (WebView2).
- Nowe poprawki tłumaczeń na innych filmach niż frytki (reguły działają tylko, gdy oryginał zawiera dane słowa).
- Czas analizy po zmianach. Kroki mogą trwać 1–2 s dłużej, bo poprawki idą pojedynczo.
