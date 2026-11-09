# VidSum 0.7.11: własne okno programu

- VidSum otwiera się we **własnym oknie**: bez kart i paska adresu, z własną pozycją na pasku zadań. Do tego służy
  Edge (jest w każdym Windows 10/11) w trybie aplikacji, z osobnym profilem.
- To okno działa **bez przyspieszania sprzętowego**, więc nie zabiera pamięci karty modelom. Pomiar: przeglądarki
  i inne programy zajmowały ok. 850 MB karty, a analiza trwała 3:40 zamiast ok. 1:40.
- Firefox nie jest już potrzebny do VidSum.
- Gdy Edge nie ma, albo gdy ustawisz zmienną `VIDSUM_PRZEGLADARKA=1`, program otwiera się jak dotąd w domyślnej
  przeglądarce.
- Zamknięcie okna nie wyłącza programu (działa w tle). Wyłączasz go przyciskiem „Zakończ”, jak dotąd.

Czego nie sprawdziłem: wyglądu i działania okna na Windowsie. Testy sprawdzają tylko, jakie polecenie jest
uruchamiane.
