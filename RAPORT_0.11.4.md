# Vidsumly 0.11.4: wybór „wstępne streszczenie / najszybciej”

## Skąd 1:15 i 1:28 (Twoje przebiegi, frytki 58 s)

| | 0.10.0 (20:12) | 0.11.1 (22:46) |
|---|---|---|
| Wstępne streszczenie | nie było (dwa różne modele) | po 20 s |
| Model obrazu wczytany | w czasie pobierania (gotowy po 11 s) | po wstępnym (20 → 33 s) |
| Opis kadrów | 12,8 → 37,4 s | 33,0 → 54,9 s |
| Poprawka mowy | 38,2 → 54,3 s | 55,2 → 66,6 s |
| Streszczenie | 54,4 → 74,6 s | 66,7 → 87,8 s |
| **Całość** | **1:15** | **1:28** |

- Różnicę robi wstępne streszczenie. Gemma (3,1 GB) i qwen (4,3 GB) nie mieszczą się naraz na karcie 8 GB obok innych
  programów. Najpierw więc liczy się wstępne (16 s z wczytaniem gemmy), dopiero potem wczytuje się qwen (12,7 s).
- W 0.10.0 qwen wczytywał się w czasie pobierania filmu.
- Jakości to nie zmienia: pełne streszczenie powstaje tak samo.

## Zmiana
W Ustawieniach → Analiza jest nowe pole **„Wstępne streszczenie”**:
- **Zawsze** (domyślnie): pierwszy wynik po ok. 20 s, całość ok. 1:28.
- **Najszybciej:** jak w 0.10.0. Wstępne streszczenie powstaje tylko wtedy, gdy nic nie kosztuje (ten sam model do obrazu
  i tekstu albo opis obrazu wyłączony). Całość ok. 1:15, a wynik pojawia się na końcu.

Zapis od razu po zmianie, działa od następnego filmu.

## Inne możliwości przyspieszenia, które sprawdziłem i odrzuciłem
- **Poprawka mowy (Whisper) równolegle z opisem kadrów:** program robi to, gdy na karcie jest wolne miejsce. W Twoich
  przebiegach było 950–2049 MB, a to za mało. Zamknięcie Steama, Discorda i przeglądarek może to włączyć, ale nie
  zmieniałem progu bez pomiaru, bo groziłoby brakiem pamięci.
- **Mniej kadrów:** szybciej, ale gorsze pokrycie obrazu (oś czasu, czat). To jest strata jakości, więc nie robiłem.
- **Wstępne streszczenie na qwenie** (już wczytanym): w 0.8.2 zmyślał, więc odpada.

## Testy
- 133 testy przechodzą, 3 pominięte (tylko Windows).
- Nowe:
  - ustawienie zmienia sposób analizy (zawsze → podgląd, najszybciej → tylko gdy darmowy);
  - w przeglądarce zmiana pola zapisuje się sama.

## Czego nie przetestowałem
- **Czasu „najszybciej” na 0.11.4.** Liczba 1:15 pochodzi z Twojego przebiegu 0.10.0, który działał w ten sam sposób.
  Od tamtej pory doszło wykrywanie czarnych pasów (w tle, na CPU) i tłumaczenie wyniku na angielski po analizie (już po
  wyświetleniu wyniku, przed następnym filmem w kolejce).
