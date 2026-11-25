# Vidsumly 0.15.1: żywa strona główna, dźwięki, animacje

## Żywe logo i żywa podpowiedź
- Pod polem linku jest duże logo, które spokojnie „oddycha”: play lekko pulsuje, linie streszczenia wysuwają się i chowają, a gwiazdka mruga. Podczas analizy animacja przyspiesza.
- Na stronie głównej nie ma już drugiego znaku wodnego w rogu, bo jest żywe logo. Na pozostałych ekranach znak wodny został.
- Podpowiedź w polu wypisuje się na żywo, zdanie po zdaniu („Wklej link z YouTube…”, „Przeciągnij tu plik wideo albo audio…” itd.). Przy MP4/MP3 zdania są inne.
- Gdy coś wpiszesz, podpowiedź się zatrzymuje. Czytnik ekranu dostaje stałą etykietę.

## Dźwięki (Ustawienia → Interfejs → Dźwięki, domyślnie włączone)
- Koniec analizy: dwa tony w górę.
- Błąd: dwa tony w dół.
- Dodanie do kolejki: krótkie „blip”.
- Kliknięcia przełączników, zakładek i menu: bardzo cichy „tik”.
- Dźwięki są generowane w programie (Web Audio). Nie ma żadnych plików i nic nie jest pobierane.

## Animacje
Zasady z filmów Kole Jaina: mało, krótko i tylko po to, żeby pokazać zmianę.
- Ekran wjeżdża przy przejściu (0,18 s).
- Okienko „Opcje” otwiera się od rogu.
- Nowy wiersz w kolejce lekko wjeżdża, a gotowa konwersja raz błyska błękitem.
- Wiersze „Ostatnich” pojawiają się kolejno po rozwinięciu.
- Przyciski lekko się wciskają.
- Pasek postępu przesuwa się płynnie.
- Przy ustawieniu systemu „ogranicz ruch” animacje i wypisywanie podpowiedzi są wyłączone.

## Testy
- `tests/test_0151.py`: ustawienie dźwięków, dźwięki przy zdarzeniach i ich wyłączenie, żywe logo, wypisywanie podpowiedzi, ograniczony ruch, okienko Opcje.

## Czego nie przetestowałem
- Dźwięku w głośnikach. Test sprawdza tylko, że program wywołuje właściwy dźwięk. Nie słyszałem go w oknie Vidsumly (WebView2).
- Czy WebView2 pozwala zagrać dźwięk końca analizy, jeśli od uruchomienia nic nie kliknąłeś. Przeglądarki blokują dźwięk przed pierwszym kliknięciem.
