# Vidsumly 0.11.7: czat dokładniejszy w czasie, poprawki z przebiegów 0.11.5 (17:36 i 17:38)

## Twoje przebiegi
- **„Najszybciej”: 1:09.** To najlepszy wynik dotąd (cel był 1:15).
- **„Ze wstępnym streszczeniem”: 1:19**, wstępne streszczenie po 7 s.
- Oba modele w 100% na karcie.

## Poprawki wyniku (na zdaniach z Twoich przebiegów)
- **Cytaty po kolei w czasie.** Było 00:00, 00:05, 00:03.
- **Bez urwanych zdań po usunięciu fałszywego „brak temperatury”:**
  - było „o czasie smażenia, proporcjach składników.”, jest „o czasie smażenia i proporcjach składników.”;
  - „…z sodą oczyszczoną podczas ostatecznego smażenia” traci końcówkę, która należała do usuniętej temperatury.
- **Sprzęt po polsku:** „pot” → „garnek” (słownik typowych naczyń).
- „To idealna frytki.” → „To idealna frytka.”
- „Wypuść nasze frytki” → „Wrzuć frytki.”
- „miękkie i pękające frytki bez łamania” → „miękkie frytki, które łamią się, ale nie pękają”.

## Czat
- **Pytanie z czasem** („co robi w 0:47?”, „w 33 sekundzie”) daje modelowi osobny blok: co mówi się dokładnie
  w tej chwili, a co zaraz po niej, z czasem do 0,1 s. Wcześniej czat podał „wyjmuje i układa na tacy”,
  a w 0:47 kucharz miesza; wyjmuje dopiero od 48,5 s.
- **Znaczniki „Wniosek” i „Wiedza ogólna”** tylko przed zdaniami spoza filmu. Fakty z filmu idą pierwsze.
- **Zamienniki:** czat najpierw sprawdza, czy rzecz jest główna, czy tylko dodatkiem („too, for flavour”).
  Jeśli dodatkiem, mówi, że można ją pominąć.

## Testy
146 testów przechodzi, 3 pominięte (tylko Windows).

## Czego nie przetestowałem
- Odpowiedzi czatu z nowymi zasadami na prawdziwej gemmie.
- „bardzo wys zawartość”: model uciął słowo w tłumaczeniu. Nie mam na to reguły.
