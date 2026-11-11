# Vidsumly 0.11.6: ostrzeżenie „Ollama nie używa karty” i poprawki z przebiegu 0.11.5

## Co się stało w przebiegu 0.11.5 (14:30 zamiast 1:19)
- **Przyczyna: Ollama wczytała oba modele w 0% na kartę** (raport: „na karcie 0%”), choć karta miała wolne 6801 MB.
  Opis kadrów trwał 35,7 s/kadr zamiast 1,8 s.
- Kod obsługujący kartę i Ollamę nie zmienił się między 0.11.4 a 0.11.5 (sprawdzone w różnicach w kodzie).
- Po Twoim `ollama run` było `100% GPU`. Z ustawieniami programu (`--zapytaj`, okno kontekstu 8192) też `100% GPU`.
  Wniosek: to był chwilowy stan Ollamy, nie ustawienia programu.

## Zmiany
- **Ostrzeżenie w trakcie analizy:**
  - kiedy: Ollama wczyta model (obrazu, tekstowy albo podgląd) poniżej 50% na kartę, a karta ma ≥ 1500 MB wolnego;
  - co: w logu od razu pojawia się „⚠ … zamknij Ollamę (ikona przy zegarze → Quit), uruchom ją ponownie”;
  - to samo trafia do uwag technicznych w wyniku.
- **„posypywane miodem i solą Maldon”:** miodu w filmie nie ma, model zrobił go z „maldon”. Teraz miód jest usuwany,
  gdy oryginał mówi „maldon”, a nie mówi „honey”.
- **Mój błąd z 0.11.5:** „idealne frytki francuskie” zmieniało się w „idealna frytka” (tytuł, streszczenie).
  Teraz reguła działa tylko na liczbę pojedynczą i na „idealna frytki”.
- „Użycie duck fat” → „Użycie tłuszczu z kaczki” (wcześniej „Użycie tłuszcz z kaczki”).
- Składnik „Agria” sam, bez słowa „ziemniaki”, przy „agria potatoes” w mowie → „ziemniaki agria”.
- **Przykłady w instrukcji czatu dotyczą teraz innego filmu (naleśniki).** Pytanie o kalorie frytek było w przykładzie
  i model je przepisał, więc Twój test w 0.11.5 nic nie mówił.

## Testy
- 144 testy: 142 przechodzą, 3 pominięte (tylko Windows).
- Nowe:
  - zapisane odpowiedzi modelu z Twojego przebiegu 0.11.5 (miód, liczba mnoga, tłuszcz z kaczki);
  - ostrzeżenie o procesorze: pojawia się raz, milczy przy 100% na karcie i przy pełnej karcie;
  - „Agria” → „ziemniaki agria”.

## Czego nie przetestowałem
- Ostrzeżenia z prawdziwą Ollamą na procesorze. Nie umiem tu wywołać tego stanu, test używa atrapy.
- Odpowiedzi czatu z nowymi przykładami na prawdziwym modelu.
- Przyczyny przejścia Ollamy na procesor. Nie mam jej dziennika z tamtej chwili.
