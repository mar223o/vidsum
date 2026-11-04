# Raport — fazy 6 i 7 (VidSum 0.7.0)

## Co doszło
- **Języki:** transkrypcja zawsze w języku oryginału, 100 języków Whispera (`--jezyk auto|kod`). Napisy z YouTube
  tylko w języku oryginału (nigdy przekład autora ani tłumaczenie automatyczne).
- **Tłumaczenia** (`--tlumacz`, domyślnie `pl,en`): EN → +PL, PL → +EN, inny → +PL +EN. Te same segmenty i czasy co
  oryginał; `analiza.json` → `transkrypcja.tlumaczenia`, pliki `transkrypcja.<kod>.srt`, sekcje w `raport.md`.
  Linia, której model nie przetłumaczył, ma `null` (nigdy zgadywany tekst).
- **Faza 6 — samodzielne streszczenie:** lokalny model tekstowy `gemma3:4b` (wybrany pomiarem, `docs/modele.md`),
  pobierany automatycznie przy pierwszym użyciu. Streszczenie lokalne idzie etapami (fakty → opis). Czat z filmem
  też lokalny. Claude to tylko dodatek (`--streszczenie claude` / ustawienie).
- **Faza 7 — Whisper na GPU:** karta NVIDIA bez bibliotek CUDA → jednorazowe pobranie cuBLAS 12.8 + cuDNN 9.10
  z oficjalnych pakietów NVIDIA (PyPI, sumy SHA-256 przypięte) do `%LOCALAPPDATA%\VidSum\cuda`; `--pobierz-cuda`.
  Brak miejsca/sieci → CPU z jasną uwagą. Kolejność na 8 GB: Whisper (GPU) → zwolnienie → model obrazu → model tekstowy.
- Odporność: przerwane odpowiedzi Ollamy („token repeat limit reached”) → ponowna próba zamiast awarii.

## Dowody
- Lokalnie (Linux): 48 testów OK. CI Windows (run 41769336935): 41 OK, 7 pominiętych (atrapy POSIX).
- CI Windows, `VidSum.exe --pobierz-cuda`: pobrano 1,3 GB, sumy zgodne, 11 bibliotek, „✔ biblioteki CUDA załadowane”
  w obu wariantach (runner nie ma karty: „karty NVIDIA widoczne: 0”).
- Pomiar modeli tekstowych: 3 rundy, 8 modeli (`docs/modele.md`), wyniki na gałęzi `wyniki-pomiarow`.
- ZIP: `VidSum-0.7.0-windows-x64.zip` sha256 `18fc902c8ba8718fa5498494ff3c4cf6e060ea83cd808aa1292ab784e54d719b`;
  `VidSum-0.7.0-windows-x64-python.zip` sha256 `b2e6b3870daa489ef43125eeaa1e7d6d010f3da8d1f8bb1bb748f8a4ea72e182`.
  Windows Defender: brak zagrożeń w obu.

## Czego nie przetestowałem
- Whispera **liczącego** na prawdziwej karcie NVIDIA (CI nie ma GPU) ani czasu analizy na RTX 3070 Ti.
- gemma3:4b na GPU (pomiar był na CPU) i jakości na filmach treningowych / wykładach.
- Pobierania napisów z YouTube w innym języku niż PL/EN na prawdziwym filmie (logika wyboru — tylko testy jednostkowe).
- Interfejsu — bez zmian (faza 8); nowe dane (tłumaczenia) nie są jeszcze pokazane w widoku.
