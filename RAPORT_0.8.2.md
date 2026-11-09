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
- Wstępne robi **model tekstowy (gemma3:4b)**, ten sam co pełne streszczenie. Zaraz po transkrypcji, **przed opisem
  kadrów**. Na karcie 8 GB model tekstowy i model obrazu naraz się nie mieszczą, więc opis kadrów czeka na podgląd,
  a model tekstowy jest potem zwalniany z karty. **Cała analiza trwa przez to dłużej**: dochodzi wczytanie modelu
  tekstowego i jedna odpowiedź. Szacuję kilkanaście–kilkadziesiąt sekund, na Twojej karcie tego nie mierzyłem.
  Dlatego przełącznik jest domyślnie wyłączony.
- Najpierw próbowałem na modelu obrazu (qwen3-vl), który i tak jest na karcie, bo byłoby to prawie za darmo. Pomiar
  wykluczył ten pomysł: po polsku pisał „marchewka agria” i „idealne fasolki” zamiast ziemniaków i frytek.
- Polecenie dzieli film na trzy części (początek, środek, koniec), po akapicie na każdą. Bez tego model kończył
  w połowie filmu, przed smażeniem.
- Te same zabezpieczenia co w pełnym streszczeniu:
  - zdanie z liczbą, której nie ma w mowie, jest usuwane;
  - stałe poprawki terminów (baking soda → soda oczyszczona, par-fry → wstępne smażenie itd.).
- Długi film: do podglądu idzie równomiernie wybrana część linii. Pod wstępnym streszczeniem widać wtedy dopisek
  „część linii — długi film”.
- Bez karty NVIDIA (Whisper na procesorze) transkrypcja kończy się dopiero w czasie opisu kadrów. Wtedy podgląd się
  nie robi, bo pełne streszczenie i tak przyjdzie zaraz potem.

### Pomiar podglądu (frytki, ta sama transkrypcja co u Ciebie, u mnie na procesorze)
| | fakty (z 14) | zmyślenia |
|---|---|---|
| qwen3-vl:4b (model obrazu), 2 przebiegi | 7, 5 | „marchewka”, „fasolki” (nie złapane przez listę, przeczytałem wynik) |
| gemma3:4b, pierwsza wersja polecenia | 4, 6 | 0 (kończy w połowie filmu) |
| **gemma3:4b, polecenie „początek / środek / koniec”** | **8, 11** | **0** |

W lepszym przebiegu wstępne streszczenie ma całość: agria, 1 cm, moczenie, gotowanie z sodą, chłodzenie, 140 °C,
wstępne smażenie, 190 °C, sól Maldon. W słabszym urywa się przed smażeniem. Polszczyzna bywa koślawa („soakowane”).
To jest wersja wstępna: pełne streszczenie ma 16/16 faktów.

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

## Poprawka: czytany fragment nie skacze na telefonie
Na wąskim ekranie odtwarzacz jest nad transkrypcją. Gdy po końcu analizy film się wczytywał (albo pojawiała się
informacja, że go nie ma), odtwarzacz zmieniał wysokość i czytany fragment przesuwał się o kilkaset pikseli.
Wyłapał to test w przeglądarce, raz na ~12 uruchomień. Teraz odtwarzacz ma od początku właściwe proporcje
(z analizy), a podmiana na „brak filmu” trzyma czytany fragment w miejscu. 25 uruchomień testu z rzędu bez błędu.

## Testy
- 99 testów przechodzi (2 pominięte — tylko Windows). Nowe testy:
  - Podgląd idzie na modelu tekstowym, przed opisem kadrów, i przychodzi przed pełnym streszczeniem. Wynik
    zapisuje, po ilu sekundach podgląd był gotowy.
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
- **Ile sekund podgląd doda na Twojej karcie** i po ilu sekundach od startu się pojawi. Jakość sprawdziłem na
  prawdziwym modelu, czas tylko u mnie na procesorze (65–125 s na odpowiedź; na karcie będzie wielokrotnie szybciej).
- Całej analizy z podglądem na prawdziwych modelach. Test całej ścieżki używa atrapy Ollamy.
- **Pełnego ekranu mapy w oknie programu (WebView2).** Sprawdzone w Chromium. Jeśli w oknie nie zadziała, mapa
  i tak działa w kolumnie.
- Mapy na filmie bez rozdziałów (trening, wykład) z prawdziwym wynikiem. W teście mapa była zbudowana z samych
  „Najważniejszych”.
