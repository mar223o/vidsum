# VidSum 0.8.3: szybciej i dokładniej (po Twoich pomiarach 0.8.2)

## Z czego to wynika: Twoje dwa przebiegi 0.8.2 (frytki, 58 s)
| etap | bez podglądu (1:39) | z podglądem (2:20) |
|---|---|---|
| opis kadrów (20 kadrów) | 38 s, 1,9 s/kadr | 70 s, 3,5 s/kadr |
| dokładna transkrypcja (Whisper) | 16 s, po kadrach | 27 s, równolegle z kadrami |
| szybki podgląd | — | 23,5 s, gotowy po 34 s |
| streszczenie | 30 s | 25 s |

- Najdłuższy etap to opis kadrów. 20 kadrów na 58 s filmu to kadr co 2–3 s, a sąsiednie opisy były prawie takie same
  („wycieranie wody z miski” trzy razy). Model przepisywał też napisy z ekranu, które i tak czyta OCR.
- Z podglądem:
  - model tekstowy wypchnął z karty wcześniej wczytany model obrazu, więc ten wczytywał się drugi raz;
  - w tej chwili karta była prawie pusta, więc program uznał, że Whisper zmieści się obok kadrów, i puścił oba naraz;
  - wszystko się spowolniło.

## Zmiany: szybkość
- **Mniej kadrów w krótkich filmach:** do 2 min kadr na ~4 s (min. 10, maks. 20). Frytki: 15 zamiast 20. Ręczny
  limit kadrów w ustawieniach dalej wygrywa.
- **Krótsza odpowiedź modelu obrazu, gdy działa OCR:**
  - bez przepisywania napisów z ekranu (biorą się z OCR, który jest dokładniejszy);
  - najwyżej 3 czynności i 5 obiektów;
  - bez powtórzeń.

  Pomiar na qwen3-vl (u mnie, ten sam model): odpowiedź na kadr **118 → 73 tokeny (−38%)**. Czas opisu kadru rośnie
  z liczbą tokenów odpowiedzi.
- **Szybki podgląd w nowej kolejności:**
  1. Z napisami serwisu (YouTube) podgląd startuje zaraz po ich pobraniu (~3 s), w czasie OCR i wycinania kadrów.
     Nie czeka już na model obrazu.
  2. Model obrazu wczytuje się dopiero po podglądzie, raz.
  3. O tym, czy Whisper idzie równolegle z kadrami, program decyduje dopiero, gdy model obrazu jest na karcie. To
     usuwa błąd z 0.8.2.

### Czego się spodziewam (szacunek, nie pomiar)
| | 0.8.2 (Twój pomiar) | 0.8.3 (szacunek) |
|---|---|---|
| bez podglądu | 1:39 | ~1:20 |
| z podglądem | 2:20 | ~1:40–1:50, podgląd po ~20–25 s |

Najwięcej zależy od tego, ile karty zajmują inne programy. W Twoim pierwszym przebiegu było to 2,2 GB, w drugim 1,2 GB.

## Zmiany: dokładność (błędy z Twoich przebiegów)
- „posypaniem **miodnym** solą”, „**Miód** z solą Maldon” → „solą Maldon”, „Sól Maldon”. Poprawka działa, gdy w filmie
  pada „maldon”, a nie pada „honey”.
- „parować/blanszować” → „wstępnie smażyć/blanszować” (w 0.8.2 poprawiałem tylko „parowanie”, nie „parować”).
- „Wyrzuć frytki” → „Wrzuć frytki”, gdy w filmie jest „drop in”. „Usuń je” → „Wyjmij je”, gdy w filmie jest „remove them”.
  „Usuń nadmiar skrobi” zostaje.
- Składniki: „Agria” + „ziemniaki” → jeden składnik „ziemniaki agria”. „Maldon salt”/„Maldon sól” → „sól Maldon”.

## Testy
- 102 testy przechodzą (2 pominięte, bo działają tylko na Windows). Nowe testy obejmują:
  - poprawki z Twoich przebiegów (miód, czasowniki, Wrzuć/Wyjmij, agria) i to, że nie psują poprawnych zdań
    („Dodaj miód”, gdy w filmie jest honey; „Wyrzuć skórki” bez „drop in”);
  - liczbę kadrów dla 20 s, 58 s, 80 s, 2 min i 5 min;
  - usuwanie powtórzonych czynności;
  - szybki podgląd: model obrazu nie wczytuje się przed podglądem, a z OCR kadry idą lekką wersją opisu.

## Czego nie przetestowałem
- **Czasów na Twojej karcie.** Liczby wyżej to szacunek z tokenów i liczby kadrów, nie pomiar.
- Jakości opisów kadrów w wersji lekkiej na prawdziwym filmie. Tokeny mierzyłem na kadrach z filmu testowego
  (proste plansze z napisem), nie na frytkach.
- Czy przy 15 kadrach nic ważnego nie wypada. Treść kroków i streszczenia niesie głównie mowa i OCR, ale kadry
  uzupełniają oznaczenia „[mowa+obraz]”.
