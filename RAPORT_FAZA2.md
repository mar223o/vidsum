# Raport — Faza 2: program na Windows (VidSum 0.2.0)

## Co powstało
- **VidSum.exe** (folder z programem, ZIP ~200 MB). Dwuklik → czarne okno (serwer) + strona w przeglądarce.
  Z argumentami działa jak wiersz poleceń (`VidSum.exe "C:\film.mp4"`, `VidSum.exe --help`).
- **Interfejs PL/EN:** przeciągnij pliki (kilka naraz) albo wklej link(i) / ścieżki → kolejka analiz z postępem →
  podgląd wyniku (streszczenie, ograniczenia, oś czasu z kadrami i etykietami „obraz” / „mowa”) →
  przyciski **Kopiuj prompt dla Claude**, **Podsumuj przez Claude**, **Otwórz folder**. Ustawienia zapamiętywane.
  Status u góry: ffmpeg / Ollama + model / Claude Code.
- **ffmpeg w zestawie** (`bin\`, kompilacja LGPL BtbN, wersja w `bin\FFMPEG-VERSION.txt`). Pythona nie trzeba.
- **Bezpieczeństwo:** serwer słucha tylko na 127.0.0.1; każde wywołanie API wymaga losowego tokenu z adresu strony
  (inne strony w przeglądarce nie mogą sterować programem); pliki wyników serwowane tylko z folderu danej analizy.
- **GitHub Actions** (`.github/workflows/windows.yml`): przy każdym pushu testy na Windows, budowa, testy dymne,
  ZIP + sha256 jako artefakt; przy tagu `v*` — Release.

## Dowody — co uruchomiłem i z jakim wynikiem
**Na Windows (GitHub Actions, Windows Server 2025, przebieg 41523632998 — zielony):**
1. `pytest` → **19 passed, 3 skipped** (pominięte: atrapa `claude` jako skrypt Linux).
2. Gotowy `VidSum.exe` z PATH ograniczonym do `C:\Windows\System32` (bez Pythona, bez ffmpeg):
   `VidSum.exe "tests\data\Filmy testowe ąęś\przepis z mową.mp4" -o "...\wyniki ąę" --whisper tiny`
   → 4 segmenty mowy, 16 kadrów, 6,8 s. Rozpoznane (Whisper tiny, CPU): „Najpierw krojmy jedną cebulę w drobną
   kostkę.” · „Teraz wywamy 200 mlm leka.” · „Mieszamy przez 5 minut na małym obniu.” · „Gotowe, smacznego.”
3. `VidSum.exe --ui` → strona się wczytuje; `/api/status` widzi spakowany ffmpeg; bez tokenu → **403**.

**U mnie (Linux):**
4. `pytest` → **22 passed** (w tym 7 testów serwera: token, wysyłanie pliku z polską nazwą, sprzątanie przesłanej
   kopii, blokada `../` w ścieżkach, błędny plik nie zabija serwera, przycisk Claude na atrapie).
5. Interfejs w Chromium (Playwright): wysłanie „Mój film żółć.mp4”, kolejka, podgląd wyniku, przełączenie na EN,
   widok telefonu 390 px bez poziomego przewijania; zrzuty ekranu obejrzane.
6. Spakowana wersja Linux (ten sam plik .spec) z prawdziwym Whisper small: 4/4 zdania.

## Błędy znalezione i poprawione w tej fazie
| problem | poprawka |
|---|---|
| luka „brak dźwięku” wpisywana dwa razy | jedna |
| pusty odcinek na samym końcu („00:05–00:05”) | brak kadru w ostatniej sekundzie; test |

## Czego nie przetestowałem
- **Twojego komputera:** GPU RTX 3070 Ti, prędkości, VRAM przy 8 GB, Ollamy na Windows z prawdziwym modelem.
- **Claude Code na Windows** (przycisk „Podsumuj przez Claude”) — tylko atrapa na Linuksie.
- Przeciągania pliku myszką z Eksploratora (testowane przez wybór pliku w przeglądarce), plików 30–40 min,
  10 filmów naraz.
- Linków YouTube / Instagram / TikTok i opcji ciasteczek z przeglądarki.
- Ostrzeżenia SmartScreen (program nie jest podpisany certyfikatem).
- Whisper na GPU w .exe — paczka używa Whispera na **CPU** (biblioteki CUDA dodałyby ~1 GB);
  model obrazu w Ollamie i tak korzysta z GPU.

## Jak sprawdzić na Windows (PowerShell)
```powershell
cd $env:USERPROFILE\Downloads
Get-FileHash .\VidSum-0.2.0-windows-x64.zip -Algorithm SHA256   # porównaj z plikiem .sha256
Expand-Archive .\VidSum-0.2.0-windows-x64.zip -DestinationPath .\VidSum-0.2.0
.\VidSum-0.2.0\VidSum\VidSum.exe
```
Potem w przeglądarce: wrzuć krótki przepis (1–3 min). Odeślij mi: zrzut ekranu wyniku, ostatnie linie z czarnego
okna i linijkę `czasy` z `analiza.json` (folder: Dokumenty\VidSum\...).
