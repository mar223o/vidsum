# VidSum 0.8.0: VidSum jako osobny program

- VidSum ma **własne okno programu**, jak Steam albo gry, a nie kartę w przeglądarce. Okno używa WebView2, który jest
  w każdym Windows 10/11, także bez przeglądarki Edge. Ma osobną pozycję na pasku zadań.
  - Dlaczego 0.7.11 tego nie dało: tam okno robił Edge, a gdy Edge'a nie ma (w UE da się go odinstalować), program
    wracał do domyślnej przeglądarki.
- Zamknięcie okna kończy program. Jeśli trwa analiza, program najpierw pyta.
- Okno działa bez przyspieszania sprzętowego, więc nie zabiera pamięci karty modelom.
- Gdy okno nie może wystartować (brak WebView2/.NET), program otwiera się jak dotąd: najpierw Edge w trybie
  aplikacji, potem domyślna przeglądarka.
- Nowa biblioteka (pywebview), więc aktualizacja pobiera **pełny instalator**, a nie samą paczkę kodu. Instalator
  uruchomi się sam: przeklikaj go, Twoje analizy i ustawienia zostają.
- Przy budowaniu wydania instalacja jest sprawdzana na Windowsie: czy zainstalowany Python ładuje okno programu
  (pywebview + .NET + WebView2).

Czego nie sprawdziłem: samego okna na ekranie. Przy budowaniu sprawdzane jest tylko, czy wszystko, czego okno
potrzebuje, się ładuje.
