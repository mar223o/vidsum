# VidSum 0.7.8: dokładniejsze kroki, dłuższe streszczenie, wynik na żywo

## Streszczenie: bez zmyśleń, liczby w dobrych krokach
Pomiar na komputerze testowym (0.7.7, frytki) pokazał zmyślenia: „wyciśnij nadmiar skrobi”, „papierowy ręcznik”, „świeżo zmielona
sól Maldon”, „nie przesadzaj z solą”, „proszek do pieczenia” zamiast sody. Było też 190 °C przy pierwszym smażeniu
i 140 °C jako osobny krok przy mrożeniu.

**Przepisy i poradniki: kroki linia po linii.** Model zamienia każdą linię mowy na polecenie po polsku albo
wyjaśnienie, w tej samej numeracji. To ten sam format co tłumaczenie, z którym gemma3:4b radzi sobie dobrze.
Dzięki temu każdy krok wie, z której linii i z którego momentu pochodzi. Program sprawdza:
- czy liczby w kroku padły w jego linii (albo na ekranie w tej chwili) i czy liczby z mowy trafiły do kroku;
- czy krok jest po polsku;
- czy linia z poleceniem nie została pominięta.

To, co się nie zgadza, model dostaje jeszcze raz (tylko te linie). Jeśli nadal źle, krok odpada. Lepiej brak
kroku niż zła liczba.

Pozostałe zmiany w krokach:
- Kawałki zdań („To completely cool.”, „Roughly one centimetre.”) doklejają się do kroku.
- Opisy („Posiada dużo skrobi”) trafiają do wskazówek, a „This is it.” do niczego.
- Składniki i sprzęt trafiają do wyniku tylko, gdy padły w mowie. Ilość jest podawana tylko, gdy jej liczba padła
  w filmie.
- Rozdziały dla przepisów i poradników: model podaje tytuły i początki rozdziałów, a program przyciąga każdy początek
  do najbliższego kroku. Opis rozdziału to kroki, które naprawdę są w tym rozdziale. Grupowania kroków w etapy mały
  model nie umiał zrobić w żadnej formie, którą sprawdziłem.
- Momenty powstają z kroków.

**Poprawki w całym streszczeniu:**
- Zdania opisu z liczbą, której nie ma w filmie, są usuwane.
- Stałe poprawki terminów, gdy oryginał jest jednoznaczny: baking soda → soda oczyszczona (także w tłumaczeniu
  transkrypcji), duck fat → tłuszcz z kaczki. Usuwane są też litery cyrylicy wstawione w polskie słowa („sodы”).
- Ścieżka dla treningów i wykładów: uzupełnianie nie podmienia już kroków i nie dopisuje składników ani porad.
- Ponowna próba po zapętleniu modelu („token repeat limit”) idzie z innym ziarnem. Przy tym samym ziarnie model
  zapętlał się identycznie.

## Streszczenie dłuższe: cel 1:00–1:25 czytania
- 4 akapity (temat i cel, etapy z liczbami, wskazówki i uzasadnienia, wniosek) plus pole „Do zapamiętania”.
- Długość zależy od ilości treści w filmie (120–270 słów). Czas czytania widać przy nagłówku streszczenia i w raporcie.

## Wynik na żywo
- Po „Analizuj” program od razu przechodzi na stronę wyniku. Widać tytuł i pasek etapów (pobieranie → mowa →
  kadry → opis obrazu → streszczenie). Transkrypcja jest od pierwszych sekund, najpierw wstępna z napisów serwisu,
  potem dokładna. Dalej pojawiają się kadry, kroki, a na końcu streszczenie.
- Sekcje podmieniają się tylko, gdy zmienia się ich treść. Czytany fragment transkrypcji zostaje w tym samym miejscu.
- Transkrypcja ma przełącznik Oryginał / PL (tłumaczenie) i węższą kolumnę do czytania.
- Na telefonie w trakcie analizy transkrypcja jest zaraz pod nagłówkiem, bez pustego odtwarzacza.
- W kolejce na stronie głównej jest przycisk „Podgląd na żywo”.
- Pasek etapu nie cofa się już przy drugiej transkrypcji ani przy OCR.

## Pomiar (frytki, ta sama transkrypcja i napisy co na komputerze testowym w 0.7.7)
Sprawdzane `tests/bench/summary_bench.py`: 16 faktów z filmu, lista zmyśleń z wyniku 0.7.7 i to, czy 140 °C oraz
190 °C są w dobrych krokach. Model ten sam (gemma3:4b), tylko u mnie na procesorze — wyniki modelu są takie same
jak na karcie, czasy nie.

| | 0.7.7 (wynik z komputera testowego) | 0.7.8, przebieg 1 | 0.7.8, przebieg 2 |
|---|---|---|---|
| fakty | 16/16 | 16/16 | 16/16 |
| zmyślenia | 5 (papierowy ręcznik, wyciśnij skrobię, kacze pióro, nie przesadzaj z solą, kociołek z wodą) | 0 | 0 |
| 140 °C w kroku pierwszego smażenia | nie | tak | tak |
| 190 °C w kroku drugiego smażenia | nie | tak | tak |
| krok „smaż na złoto” / „posyp solą Maldon” | tak / tak | tak / tak | tak / tak |
| rozdziały | 6 (ostatni 0:42–0:58 łączył 3 etapy) | 6 | 6 |
| czas czytania streszczenia | 21 s | 1 min 02 s | 54 s |

## Testy
- 78 testów (2 pominięte — tylko Windows), w tym nowe: kroki linia po linii (zła liczba, krok po angielsku,
  pominięta linia, zmyślona ilość, sprzęt bez źródła), poprawki terminów, usuwanie zdań z obcą liczbą, rozdziały,
  zapas przy zapętleniu, wszystkie linie wysłane do modelu.
- Przeglądarka (Chromium): strona na żywo na 1280 i 390 px — transkrypcja od razu, czytany fragment przesuwa się
  o ≤ 2 px po dojściu kroków i po końcu analizy, brak błędów w konsoli, brak poziomego przewijania na telefonie.

## Znalezione i naprawione przy pomiarach na prawdziwym modelu
- Pierwsze 20 linii w ogóle nie trafiało do modelu (błąd przy dzieleniu na części) — test pilnuje tego teraz.
- Model odpowiadał „przepis (gotowanie)” zamiast „przepis” — typ rozpoznawany z takiej odpowiedzi.
- Składniki pod kluczem „składniki” (z polskimi literami) — czytane też tak.

## Czego nie przetestowałem
- Całej analizy na Twojej karcie: czasu (dochodzą krótkie zapytania o kroki: 2–3 części po ~20 linii równolegle,
  ewentualnie poprawki) i tego, czy na karcie model zapętla się tak samo często jak u mnie na procesorze.
- Innych filmów niż frytki (trening i wykład idą starą ścieżką z poprawkami; poradnik — nową, jak przepis).
- Strony na żywo z prawdziwą analizą — test w przeglądarce używa danych podstawionych, nie prawdziwego modelu.
- Instalatora i aktualizacji 0.7.7 → 0.7.8 — wydanie zbuduje się dopiero po odnowieniu minut na GitHubie.

## Ograniczenia, które zostały
- Polszczyzna kroków bywa koślawa („Wyrzuć w frytki”, „Połóż w tacę”) — to granica modelu 4B; treść i liczby są
  z filmu.
- Tytuły rozdziałów od modelu bywają nietrafione; opisy rozdziałów są z kroków, więc zgadzają się z treścią.
