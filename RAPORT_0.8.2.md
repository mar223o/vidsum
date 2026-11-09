# VidSum 0.8.2: szybki podgląd i mapa myśli

## Szybki podgląd: najpierw wstępne, potem pełne
Obok przycisku **Analizuj** jest przełącznik **„Szybki podgląd”**. Domyślnie jest wyłączony, a program zapamiętuje
ustawienie. Z wiersza poleceń: `--szybki-podglad`.

Gdy jest włączony:
1. Gdy tylko jest transkrypcja (z napisów serwisu albo z Whispera), program robi **wstępne streszczenie z samej
   mowy**: tytuł, tezę, 2 akapity i 3–5 najważniejszych punktów z czasem.
2. Wstępne streszczenie pojawia się na stronie wyniku z oznaczeniem **„wstępne”** i dopiskiem, że pełne je zastąpi.
3. Na końcu analizy pełne streszczenie (z obrazem, krokami, rozdziałami) **podmienia** wstępne. Przy nagłówku
   streszczenia zostaje informacja „wstępne po 0:25 → pełne po 1:36”. To samo jest w raporcie (`raport.md`).

Jak to działa i co kosztuje:
- Wstępne robi **model obrazu (qwen3-vl), który i tak jest już wczytany na kartę** do opisu kadrów. Model działa
  z tym samym rozmiarem kontekstu, więc Ollama go nie przeładowuje, a druga kopia nie wchodzi do pamięci karty.
- Z ustawieniem Ollamy „jedno zapytanie naraz” opis kadrów czeka na to jedno zapytanie. Cała analiza wydłuża się
  o czas jednej odpowiedzi modelu. Nie zmierzyłem tego na Twojej karcie (patrz niżej). Dlatego przełącznik jest
  domyślnie wyłączony.
- Te same zabezpieczenia co w pełnym streszczeniu:
  - zdanie z liczbą, której nie ma w mowie, jest usuwane;
  - stałe poprawki terminów (baking soda → soda oczyszczona itd.).
- Długi film: do podglądu idzie równomiernie wybrana część linii, żeby zmieścić się w kontekście modelu.
  Pod wstępnym streszczeniem widać wtedy dopisek „część linii — długi film”.
- Bez modelu obrazu (obraz wyłączony) podgląd robi model tekstowy.

## Mapa myśli
Nowa zakładka **„Mapa myśli”** przy wyniku (gdy są rozdziały albo najważniejsze punkty):
- Środek mapy to temat filmu.
- Gałęzie to rozdziały i „Najważniejsze”.
- Liście to kroki z danego rozdziału (albo momenty rozdziału).
- **Kliknięcie gałęzi** pokazuje szczegóły: opis, czas (od–do dla rozdziału) i zdanie z transkrypcji z tej chwili
  („W filmie mówi: …”). Kliknięcie **przewija film** do tego miejsca.
- **Powiększanie i przesuwanie**:
  - powiększanie: przyciski + / − albo Ctrl + kółko myszy;
  - przesuwanie: przeciąganie;
  - „Dopasuj” wraca do całości.
- Układ zależy od miejsca:
  - w kolumnie obok filmu jest drzewo z wcięciami, czytelne bez powiększania;
  - po **„Pełny ekran”** jest klasyczna mapa myśli z gałęziami po obu stronach środka. Tam samo kółko myszy
    powiększa, a szczegóły pokazują się w rogu.
- Mapa korzysta tylko z tego, co już jest w wyniku (rozdziały, kroki, najważniejsze, transkrypcja). Nie robi
  dodatkowych zapytań do modelu.

## Testy
- Nowe testy:
  - Podgląd idzie na modelu obrazu z tym samym kontekstem (bez przeładowania) i przychodzi przed pełnym
    streszczeniem. Wynik zapisuje, po ilu sekundach podgląd był gotowy.
  - Przy wyłączonym przełączniku program nie wysyła zapytania o podgląd.
  - Zabezpieczenia podglądu: zdanie z liczbą spoza mowy jest usuwane, a długa transkrypcja jest przycinana do
    limitu.
  - Przełącznik zapisuje się w ustawieniach i trafia do analizy.
- Przeglądarka (Chromium), cała ścieżka:
  1. W trakcie analizy widać wstępne streszczenie z oznaczeniem „wstępne”.
  2. Na końcu analizy pełne streszczenie je zastępuje i pojawia się opis „wstępne po … → pełne po …”.
  3. Mapa myśli ma właściwą liczbę węzłów. Kliknięcie rozdziału pokazuje czas, opis i zdanie z filmu.
  4. Ctrl + kółko powiększa, „Dopasuj” wraca do całości.
  5. Pełny ekran działa, bez błędów w konsoli.
- Zrzuty mapy na Twoim wyniku 0.8.0, w kolumnie i na pełnym ekranie.

## Czego nie przetestowałem
- **Szybkiego podglądu na prawdziwym modelu i karcie.** Testy używają atrapy Ollamy. Nie wiem, jak dobre będzie
  wstępne streszczenie z qwen3-vl:4b (to model obrazu, a nie tekstowy), ani ile sekund doda do analizy.
- **Pełnego ekranu mapy w oknie programu (WebView2).** Sprawdzone w Chromium. Jeśli w oknie nie zadziała, mapa
  i tak działa w kolumnie.
- Mapy na filmie bez rozdziałów (trening, wykład) z prawdziwym wynikiem. W teście mapa była zbudowana z samych
  „Najważniejszych”.
