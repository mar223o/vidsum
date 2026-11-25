# Vidsumly 0.15.0 „Komenda”

Nowy wygląd wybrany 24–25.11.2026 z makiet (wersja „Komenda”, paleta „Krem + błękit”, tło „Łupek + błękitne kropki + znak”, logo „Kontur”).

## Strona główna
- Zniknęło duże hasło „Wrzuć film — powiem Ci…”. Pole linku jest pierwszą rzeczą pod paskiem.
- Nad polem jest jeden przełącznik **Analiza / MP4 / MP3**. Przy MP4 i MP3 przycisk zmienia się na „Pobierz MP4” albo „Pobierz MP3”, a pod polem widać folder zapisu.
- Tryb analizy i wstępne streszczenie są w okienku **Opcje** (przycisk z nazwą trybu obok „Analizuj”). Okienko zamyka Esc albo kliknięcie obok.
- Plik dodajesz ikoną strzałki w polu albo przeciągając go na pole. Enter wysyła link, a Shift+Enter dodaje nową linię.
- Kolejka pokazuje się tylko wtedy, gdy coś w niej jest. Trwająca analiza ma tytuł filmu zamiast linku.
- Gotowe analizy są w zwijanej sekcji **Ostatnie** (najnowsze na górze, do 8), a nie w kolejce.

## Pasek u góry
- Zamiast trzech chipów stanu jest jeden wskaźnik: „Gotowy” albo „Coś nie działa: Ollama”. Liczy się to, czego wymaga wybrany silnik: przy silniku Claude to Claude Code zamiast Ollamy. Szczegóły są w dymku.
- Przełącznik PL/EN jest tylko w Ustawieniach. Motyw i „Otwórz w przeglądarce” to małe ikony.

## Kolory i tło
- Ciemny motyw: tło „łupek” `#0f1316`, kremowy tekst `#F5EFE6`, jeden akcent: błękit `#38BDF8` (aktywne i trwające).
- W ciemnym motywie są błękitne kropki w lewym górnym i prawym dolnym rogu oraz mały znak wodny (kształt logo). Na telefonie znak wodny się chowa.
- Jasny motyw jest kremowy jak wcześniej.
- Bez gradientów i poświat. Lawenda została tylko w logo.
- Kontrast tekstu wynosi co najmniej 4,5:1 we wszystkich kombinacjach tła i tekstu (sprawdza to test).

## Logo
- „Kontur”: czarny kwadrat, cienki kremowy kontur kadru z perforacją w środku, kremowy play i linie streszczenia, jedna lawendowa gwiazdka.
- Ikona 16–24 px jest uproszczona: kontur, play i gwiazdka.

## Biblioteka
- Widać tylko kategorie, w których coś jest, z liczbą filmów.
- Karta pokazuje datę analizy zamiast czasu trwania analizy.
- Tytuł biblioteki jest mniejszy i nie ma gradientu.

## Testy
- Nowy plik `tests/test_0150.py`: kontrast, jeden akcent, układ strony głównej, okienko Opcje, „Ostatnie”, wskaźnik stanu, kategorie biblioteki, znak wodny.
- Zaktualizowane testy: `test_0131_ikona.py`, `test_0132.py`, `test_0140.py`, `test_ui_app.py`.

## Czego nie przetestowałem
- Wyglądu w oknie programu na Windowsie (Edge WebView2) i z czcionką Segoe UI. Testy działają w Chromium na Linuksie.
- Ikony na pasku zadań Windows po aktualizacji. Windows może pokazywać starą ikonę z pamięci podręcznej, dopóki nie odepniesz i nie przypniesz programu ponownie.
