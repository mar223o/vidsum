# Vidsumly 0.11.8: czat — pytanie o chwilę filmu odpowiadane z transkrypcji

## Pomiar 0.11.7 (Twój czat)
- **„co robi w 0:47?”** Czas był już dobry, ale treść zła: „miesza **zioła**”, z błędnego opisu kadru, podane jako „autor mówi”.
  W mowie jest „Stirring constantly for ruffled edges”.
- **„czym zastąpić tłuszcz z kaczki?”** Znacznik „Wniosek (nie pada wprost w filmie)” stał przed zdaniem, które pada w filmie.

## Zmiany
- **Pytania typu „co robi / co się dzieje / co mówi w 0:47”** czat składa sam, bez modelu, z transkrypcji, w kolejności:
  1. co słychać dokładnie w tej chwili, z tłumaczeniem;
  2. co zaraz potem (do 3,5 s);
  3. opis kadru, oznaczony jako automatyczny i możliwie nieprecyzyjny.

  Działa od razu, także bez Ollamy. Inne pytania z czasem (np. „ile stopni w 0:52?”) dalej idą do modelu,
  który dostaje dokładne czasy, a opis kadru jako ostatni i oznaczony jako niepewny.
- **Znacznik „Wniosek” / „Wiedza ogólna” przed zdaniem „W filmie…”** jest usuwany. Przed zdaniami spoza filmu zostaje.

## Testy
147 testów przechodzi, 3 pominięte (tylko Windows).

## Czego nie przetestowałem
- Wyglądu tej odpowiedzi w oknie czatu na Windows.
- Pytań o chwilę, w której nikt nie mówi, na prawdziwym filmie (sprawdzone tylko w kodzie).
