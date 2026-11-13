# Vidsumly — prywatność (stan: wersja 0.12.0)

Krótko: **filmy, nagrania, transkrypcje, streszczenia i pytania z czatu zostają na Twoim komputerze.**
Program nie ma kont, nie zbiera statystyk i niczego nie wysyła do autora.

## Co jest liczone lokalnie
- rozpoznawanie mowy (Whisper), opis kadrów i napisy z ekranu (OCR), streszczenie, tłumaczenie i czat — modele działają
  na Twoim komputerze (Ollama, faster-whisper);
- wyniki zapisują się w folderze `Dokumenty\Vidsumly` (zmienisz w Ustawieniach); ustawienia i dziennik w `%LOCALAPPDATA%\Vidsumly`.

## Kiedy program łączy się z internetem
| Kiedy | Z kim | Po co |
|---|---|---|
| Wklejasz link | serwis z linku (np. YouTube, Instagram) | pobranie filmu, napisów i — jeśli poprosisz — komentarzy (yt-dlp) |
| Pierwsze uruchomienie | ollama.com / rejestr modeli Ollamy | instalator Ollamy i modele (jednorazowo) |
| Pierwsza analiza | Hugging Face | model mowy Whisper i model OCR (jednorazowo) |
| Pierwsza analiza z kartą NVIDIA | files.pythonhosted.org | biblioteki CUDA (jednorazowo) |
| Klikasz „Sprawdź aktualizacje” | api.github.com | nowa wersja programu |

Poza tym program nie nawiązuje połączeń. Źródło: adresy w kodzie (`vidsum/update.py`, `vidsum/cuda.py`, `vidsum/ocr.py`,
`vidsum/ollama_setup.py`, `vidsum/fetch.py`).

## Opcja: Claude
Streszczenie przez Claude jest wyłączone, dopóki sam go nie włączysz w Ustawieniach. Po włączeniu treść analizy
(transkrypcja, opisy kadrów) trafia do Anthropic przez program Claude Code zalogowany Twoim kontem.
Przycisk „Kopiuj prompt” niczego nie wysyła — kopiuje tekst do schowka.

## Klucze
Klucz do aktualizacji z prywatnego repozytorium jest przechowywany w Menedżerze poświadczeń Windows —
nie w pliku tekstowym i nie w dzienniku.

## Pobieranie z serwisów
Regulaminy serwisów wideo zwykle ograniczają pobieranie treści. Korzystaj z filmów, do których masz prawo
(więcej: `docs/licencje.md`).
