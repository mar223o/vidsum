# VidSum 0.7.9 — poprawka ponownego uruchomienia po aktualizacji

- Po aktualizacji z 0.7.7 do 0.7.8 Windows pokazywał „System Windows nie może odnaleźć „\\”” i program nie wstawał
  sam. Przyczyna: polecenie `cmd /c start "" "…pythonw.exe"` przekazane jako lista argumentów — Python zamieniał
  cudzysłowy na `\"`, więc `start` dostawał ścieżkę `\\`. Teraz program uruchamia Pythona bezpośrednio (bez `cmd`),
  a nowy proces sam czeka 2 s i otwiera VidSum.
- Test na Windows (w budowaniu wydania) naprawdę uruchamia tę samą komendę i sprawdza, że Python dostał argumenty
  `vidsum --ui`.
- Uwaga: przy aktualizacji z 0.7.8 do 0.7.9 ponowne uruchomienie wykonuje jeszcze kod 0.7.8 — ten komunikat może
  pojawić się ostatni raz. Kliknij OK i otwórz VidSum skrótem „VidSum”.
