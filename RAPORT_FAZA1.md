# Raport — Faza 1: prototyp CLI (VidSum 0.1.0)

Data: 2026-11-02 · środowisko testowe: Linux, 2 rdzenie CPU, 8 GB RAM, **bez GPU**

## Co powstało
Program wiersza poleceń: **plik MP4 albo link** → transkrypcja z czasami (faster-whisper) → kadry przy zmianach
scen + gęściej w ruchu + równomierne pokrycie (ffmpeg) → opis każdego kadru lokalnym modelem (Ollama, Qwen3-VL 4B
Instruct) → oś czasu „mowa + obraz” → streszczenie z oznaczeniem źródła → `raport.md`, `analiza.json`
(format: `docs/format_json.md`), `prompt_dla_claude.md`, `transkrypcja.srt`, `kadry/`.

Streszczenie: `--streszczenie auto` (domyślnie) wybiera Claude Code na Twojej subskrypcji Pro, jeśli jest
zainstalowany i **nie** jest ustawiony `ANTHROPIC_API_KEY`; inaczej lokalny model. Zawsze powstaje też
`prompt_dla_claude.md` do wklejenia na claude.ai.

## Dowody — co uruchomiłem i z jakim wynikiem
1. **Testy automatyczne:** `python -m pytest -q` → **14 passed**. Obejmują: polskie znaki w ścieżkach pliku
   i folderu wyników; wykrycie 3 cięć scen (8/16/26 s); gęstsze kadry w ruchu; limit kadrów dla 40 min;
   łączenie mowy z obrazem i etykiety źródeł; pobieranie z linku przez yt-dlp (lokalny serwer HTTP);
   film bez dźwięku; paczka z błędnym plikiem; awaria modelu na jednym kadrze (ponowna próba → „brak danych”);
   streszczenie przez `claude -p` (atrapa); blokada, gdy ustawiony `ANTHROPIC_API_KEY` (klucz nie trafia
   do wyników); automatyczny wybór silnika streszczenia.
2. **Prawdziwe modele** na syntetycznym filmie 32 s z polską mową (syntezator Piper):
   `python -m vidsum "tests/data/Filmy testowe ąęś/przepis z mową.mp4" --max-kadrow 5`
   - Whisper small (CPU): 4/4 zdania rozpoznane, czasy zgodne z nagraniem (np. „Gotowe” 26,4 s vs nagrane 26,5 s).
     Literówki: „krujmy” (kroimy), „wywamy” (wlewamy), „obniu” (ogniu).
   - Qwen3-VL 4B Instruct (CPU): 5/5 kadrów opisanych, napisy przepisane bezbłędnie
     (np. „Krok 2 - Wlej 200 ml mleka”), kolory i kształty poprawne.
   - Oś czasu (ostatni przebieg): każdy napis i każde zdanie w swojej scenie (0–8, 8–16, 16–25, 26–32 s).
   - Czas na CPU: transkrypcja ~7 s, **opis kadru ~90 s**. Lokalne streszczenie: raz ~3 min (słabe, patrz
     niżej), raz przekroczyło 600 s — program zapisał wszystkie wyniki i wpisał to w luki. Dodałem limit
     długości odpowiedzi + karę za powtórzenia (**nie sprawdzone na prawdziwym modelu**).
     Na RTX 3070 Ti powinno być wielokrotnie szybciej — **nie zmierzone**.
   - Przykładowy wynik: `przyklad_wyniku/` (ostatni przebieg + log konsoli + wcześniejszy raport ze streszczeniem lokalnym).

## Błędy znalezione na prawdziwych danych i poprawione
| problem | poprawka |
|---|---|
| cięcie między ciemnymi scenami pomijane (wynik 0,255 < próg 0,30) | próg 0,22 |
| `qwen3-vl:4b` to wariant „myślący” — minuty na kadr, pusta odpowiedź | domyślnie `qwen3-vl:4b-instruct` |
| PyAV 19 niezgodny z faster-whisper 1.2.1 | audio wczytywane bez PyAV (WAV z ffmpeg) |
| mowa trafiała do poprzedniej sceny (odcinek zaczynał się od kadru, nie od cięcia) | granica odcinka = moment cięcia; test regresji |
| zły czas ostatniego zdania (19,3 s zamiast 26,4 s) | czasy liczone z pierwszego/ostatniego słowa |
| awaria modelu na 1 kadrze przerywała cały film | ponowna próba, potem „brak danych” + wpis w lukach |
| model ładowany drugi raz do streszczenia bez zwolnienia pamięci | zwolnienie przed streszczeniem, kontekst dopasowany do długości |
| przekroczenie czasu odpowiedzi Ollamy kończyło film **bez żadnych wyników** | łapane jak inne błędy modelu; test regresji |

## Ocena jakości (szczerze)
- **Lokalne streszczenie modelem 4B jest słabe:** dopisało „napój z cebuli i mleka” bez oznaczenia
  [szacunek], skleiło kroki, wszystko oznaczyło jako [obraz], powtarzało punkty. Dlatego domyślnie wybieram
  Claude (Pro). Lokalny model zostaje do opisu kadrów, w czym radzi sobie dobrze.
- Whisper small myli polskie słowa na syntetycznym głosie — na Twoim GPU warto użyć `--whisper medium`.

## Czego nie przetestowałem
- Niczego na Windowsie (ścieżki `C:\…`, konsola PowerShell, CUDA dla Whispera i Ollamy).
- Prędkości na GPU i zużycia VRAM przy 8 GB.
- Prawdziwego Claude Code (`claude -p`) — tylko atrapa.
- Prawdziwych linków z YouTube / Instagrama / TikToka (serwisy niedostępne z mojego środowiska).
- Prawdziwych filmów kulinarnych / siłowni (tylko syntetyczne) i filmu 30–40 min.
- Whisper `medium` / `large-v3`, model `qwen3-vl:8b-instruct`.

## Jak sprawdzić na Windowsie (PowerShell)
Kroki w `README.md` → „Uruchomienie na Windows”. Po teście odeślij mi:
1. ostatnie ~15 linijek z konsoli,
2. zawartość `czasy` z `analiza.json` (ile sekund trwał każdy etap),
3. wynik `nvidia-smi` w trakcie opisu kadrów (zużycie VRAM).

## Licencje
`docs/licencje.md`. Syntezator Piper (GPL-3.0) użyłem **tylko** do wygenerowania głosu w filmie testowym —
nie jest częścią programu.
