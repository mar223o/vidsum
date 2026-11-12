# Vidsumly — instrukcja (wersja 0.12.0)

## 1. Instalacja i pierwsze uruchomienie
1. Uruchom `VidSum-Setup-<wersja>.exe`. Windows może pokazać ostrzeżenie SmartScreen (program nie jest podpisany):
   „Więcej informacji” → „Uruchom mimo to”.
2. Otwórz **Vidsumly** z menu Start. Na stronie startowej pojawi się karta **Pierwsze uruchomienie**:
   - **Zainstaluj Ollamę** — program pobiera oficjalny instalator i otwiera go; w jego oknie kliknij „Install”;
   - **Pobierz modele** — jednorazowo kilka GB, z paskiem postępu;
   - opcjonalnie **Włącz 2 zapytania naraz** — szybszy opis kadrów.
3. Przy pierwszej analizie program pobierze jeszcze model mowy (ok. 1,6 GB) i — przy karcie NVIDIA — biblioteki CUDA.

## 2. Co można analizować
- pliki wideo: MP4, MOV, MKV, WEBM;
- pliki dźwiękowe: MP3, M4A, WAV, OGG, FLAC (streszczenie z samej mowy);
- linki, np. YouTube i Instagram.
Przeciągnij plik na stronę startową albo wklej link i kliknij **Analizuj**.

## 3. Tryby analizy (przełącznik pod polem na link)
| Tryb | Co robi | Kiedy |
|---|---|---|
| **Pełna** | mowa + opis kadrów + napisy z ekranu | przepisy, ćwiczenia, krótkie filmy |
| **Mowa + szybki obraz** | najpierw pełny raport z mowy, potem kilkanaście kadrów (początki rozdziałów i miejsca, gdzie ktoś mówi „spójrz tutaj”) | długie filmy: dokumenty, wykłady |
| **Tylko mowa** | sam raport z mowy | podcasty, rozmowy, słabszy komputer |

Program podpowiada tryb na podstawie karty graficznej i pokazuje **przewidywany czas** analizy.

## 4. Wynik
- **W skrócie** — typ filmu, teza, streszczenie.
- Zakładka zależna od typu: **Przepis** (składniki, kroki), **Ćwiczenia i technika**, **Kroki**, **Fakty** (liczby, osoby, daty).
- **Najważniejsze**, **Momenty**, **Cytaty**, **Rozdziały**, **Mapa**, **Transkrypcja**, **Kadry**.
- Kliknięcie znacznika czasu przewija film do tej chwili.
- **Kontrola jakości** pod streszczeniem mówi, co program sam sprawdził i co mogło pójść źle.
- Fakty i cytaty to dosłowne zdania z nagrania. Streszczenie pisze mały model i może przekręcić szczegół.
- Reklamy sponsorów są oznaczane i pomijane w faktach.

## 5. Czat z filmem
Zadaj pytanie pod wynikiem, np. „Jakie składniki?”, „Przelicz na 4 porcje”, „Co mówi w 0:47?”.
Odpowiedź o chwili filmu zaczyna się od tego, co słychać, a potem podaje opis kadru.

## 6. Kopiowanie i eksport
**Kopiuj notatkę** (pełna notatka tekstowa, także do wklejenia innemu modelowi), **Kopiuj prompt**, **Kopiuj transkrypcję**,
**Otwórz folder** (raport.md, analiza.json, napisy .srt, kadry).

## 7. Gdy coś nie działa
| Objaw | Co zrobić |
|---|---|
| Karta „Pierwsze uruchomienie” nie znika | „Sprawdź ponownie”; gdyby instalator nie ruszył — pobierz Ollamę z https://ollama.com/download |
| Analiza jest wolna | zamknij przeglądarki, Discorda i gry (zajmują pamięć karty); wybierz „Tylko mowa” |
| W wyniku jest uwaga „model liczony na procesorze” | uruchom ponownie Ollamę (ikona lamy → Quit) i analizę |
| Link się nie pobiera | serwis mógł zmienić zabezpieczenia — zaktualizuj program; pobrany plik można wrzucić ręcznie |
| Inny problem | dziennik: `%LOCALAPPDATA%\VidSum\vidsum.log` |

## 8. Wiersz poleceń (dla dociekliwych)
```
VidSum.exe "C:\film.mp4"                       analiza pliku
VidSum.exe --tryb mowa "C:\nagranie.mp3"       tryb: pelna | szybki | mowa
VidSum.exe --kontrola "C:\…\folder analizy"    kontrola jakości gotowej analizy
VidSum.exe --streszcz-ponownie "folder"        nowe streszczenie bez pobierania i opisu kadrów
VidSum.exe --zestaw "lista.txt"                cały zestaw filmów → jeden plik z czasami i kontrolą
VidSum.exe --zmierz-czasy "folder"             pomiar etapów (Whisper, kadry, model)
```
