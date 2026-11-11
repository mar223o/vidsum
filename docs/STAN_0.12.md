# Stan prac 0.12.0 (punkt wznowienia) — noc 2026-11-12

Zlecenie użytkownika (00:23): jedno wydanie **0.12.0** ze wszystkim z planu trzech wydań; praca całą noc, krok ≤ 1 h,
po całości audyt i poprawki w kółko do ~10:00 albo do limitu; zebrać wiedzę z internetu (ze źródłami).
Komputer użytkownika jest WYŁĄCZONY — bez pomiarów na karcie; model tekstowy sprawdzam na runnerze GitHuba (CPU).

Zasady: gałąź robocza `wip-0.12.0` (push bez wydania). **Wydanie raz** (merge do main → workflow `windows.yml` buduje
i publikuje), po zakresie + testach. Po wydaniu poprawki zostają na gałęzi roboczej do decyzji użytkownika.
Domyślny tryb zostaje „Pełna” (nowe tryby bez pomiaru nie są domyślne).
Commit: autor `mar223o <193065166+mar223o@users.noreply.github.com>`, stopki Co-Authored-By: Claude Fable 5.2 + Claude-Session.

## Zakres i stan (aktualizować po każdym kroku)
- [ ] 1. Rdzeń jakości: typ raz (+sport z treści), szablon wg typu (`_FIELDS_BY_TYPE`), `story.py` (części, fakty z linii,
      reklamy, rozdziały), `thin_timeline`, `drop_frame_echo`, `clean_review`, OCR (`merge_frames`, `is_overlay_junk`,
      `caption_coverage`), `split_long_segments`, straże tłumaczenia (`line_problem`, `clean_script`), UI: reklamy, wykład.
      Stan: kod napisany; do zrobienia — naprawa testów (zmieniony przepływ typu), nowe testy, pełny pytest.
- [ ] 2. Pomiar na prawdziwym modelu w CI (`tests/bench/story_bench.py`, workflow `summary-bench.yml` z ref gałęzi).
- [ ] 3. Narzędzia: `--streszcz-ponownie`, `--zestaw`, kontrola jakości (`vidsum/quality.py`).
- [ ] 4. Tryby: Pełna / Tylko mowa / Mowa + szybki obraz + kadry wskazane mową.
- [ ] 5. Szybkość długich filmów (OCR jeden przebieg, Whisper nie czeka na OCR) + czas do końca (ETA).
- [ ] 6. Pierwsze uruchomienie (Ollama, modele) + profil sprzętu.
- [ ] 7. Badania z internetu → `docs/badania_0.12.md`.
- [ ] 8. Szlif, instrukcja, prywatność, licencje (ffmpeg: BtbN LGPL — widać w `windows.yml`).
- [ ] 9. Audyt → wydanie → RAPORT_0.12.0.md (+ sha256, kroki PowerShell) → kolejne rundy audytu.

## Dane testowe
`tests/data/filmy_0119/*.json` — 4 filmy z 0.11.9 (tortilla PL, pancake_touch, wisdm_moda, dokument_ambasada):
segmenty, tłumaczenie pl, napisy z ekranu, sceny kadrów.

## Notatki
- Stare wyniki dokumentu: `streszczenie_kroki.json` w załącznikach rozmowy (nie w repo).
