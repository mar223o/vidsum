# VidSum 0.7.7 — instalator, aktualizacje z GitHuba, szybciej

## Nowe
- **Instalator** `VidSum-Setup-0.7.7.exe`: instalacja bez administratora do `%LOCALAPPDATA%\Programs\VidSum`,
  skrót w menu Start (i na pulpicie), odinstalowanie w Ustawienia → Aplikacje. Uruchamia program bez okna konsoli.
- **Aktualizacje w programie** (Ustawienia → Aktualizacje): klucz GitHub (tylko odczyt, tylko to repozytorium)
  zapisany w Menedżerze poświadczeń Windows — nie w pliku. „Sprawdź aktualizacje” → „Aktualizuj”:
  pobiera sam kod (kilka MB), kasuje stary kod, wstawia nowy, uruchamia program ponownie. Gdy zmieniły się
  biblioteki — pobiera i uruchamia pełny instalator. Suma kontrolna sprawdzana przed instalacją.
  Wyniki, ustawienia i modele zostają.
- Nowsza wersja przy uruchomieniu zamyka starszą, jeśli ta nic nie analizuje.

## Szybciej (bez zmiany jakości)
- Opis kadrów ze schematem JSON — pomiar na komputerze testowym: 29,7 s zamiast 40,4 s, opisy w 89% takie same.
- Model obrazu wczytuje się w czasie pobierania filmu z linku (na komputerze testowym ~11 s czekania mniej).
- Model tekstowy wczytuje się w czasie poprawki mowy (Whisper); jeśli przez to nie zmieścił się cały na karcie,
  wczytuje się ponownie (wpis w logu).

## Porządki w streszczeniu
- Najwyżej 4 cytaty i 6 rozdziałów (bez dziur w czasie), bez podwójnych kroków, „wnioski” nie powtarzają wskazówek.
- Czas „2 min 0 s” zamiast „1 min 60 s”.

## Czego nie przetestowałem
- Czasu na karcie RTX. Szacunek dla frytek: ok. 1:25 (było 2:00 przy wolnym pobieraniu, 1:45 wcześniej).
- Aktualizacji z prawdziwego wydania na GitHubie — w CI sprawdzone: instalacja, podmiana kodu na zainstalowanej
  kopii, odinstalowanie, zapis/odczyt klucza w Menedżerze poświadczeń. Pierwsza prawdziwa aktualizacja: 0.7.7 → 0.7.8.
