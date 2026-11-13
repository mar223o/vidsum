# Stan prac 0.12.0 (punkt wznowienia) — noc 2026-11-12

Zlecenie użytkownika (00:23): jedno wydanie **0.12.0** ze wszystkim z planu trzech wydań; praca całą noc, krok ≤ 1 h,
po całości audyt i poprawki w kółko do ~10:00 albo do limitu; zebrać wiedzę z internetu (ze źródłami).
Komputer użytkownika jest WYŁĄCZONY — bez pomiarów na karcie; model tekstowy sprawdzam na runnerze GitHuba (CPU).

Zasady: gałąź robocza `wip-0.12.0` (push bez wydania). **Wydanie raz** (merge do main → workflow `windows.yml` buduje
i publikuje), po zakresie + testach. Po wydaniu poprawki zostają na gałęzi roboczej do decyzji użytkownika.
Domyślny tryb zostaje „Pełna” (nowe tryby bez pomiaru nie są domyślne).
Commit: autor `mar223o <193065166+mar223o@users.noreply.github.com>`, stopki Co-Authored-By: Claude Fable 5.2 + Claude-Session.

## Zakres i stan — 2026-11-12 (po południu)

1. [x] Rdzeń jakości: typ raz, szablon wg typu, streszczanie część po części, fakty z linii, reklamy, OCR, tłumaczenie.
2. [x] Narzędzia kontroli: `--kontrola`, `--streszcz-ponownie`, `--zestaw`; kontrola jakości w wyniku i w interfejsie.
3. [x] Trzy tryby (pełna / mowa + szybki obraz / tylko mowa), kadry wskazane mową, przełącznik przy linku, `--tryb`.
4. [x] Szybkość długich filmów: OCR jednym przebiegiem (≤ 240 klatek), Whisper nie czeka na OCR; prognoza czasu (ETA).
5. [x] Poprawki po pomiarach na prawdziwym modelu (gemma3:4b na runnerze GitHuba): wybór faktów, cytaty, czasy
       „najważniejszych”, reklamy przed zapytaniem, schemat odpowiedzi, naprawa urwanego JSON-a.
6. [x] Pierwsze uruchomienie bez PowerShella (`ollama_setup.py`, karta w interfejsie); profil sprzętu (propozycja trybu).
7. [x] Pliki dźwiękowe (mp3, m4a, wav, ogg, flac) — prośba z 12.11, 14:21.
8. [x] Badania ze źródłami: `docs/badania_0.12.md`.
9. [x] Dokumenty: `docs/INSTRUKCJA.md`, `docs/PRYWATNOSC.md`, `docs/licencje.md` (ffmpeg = kompilacja LGPL).
10. [x] Wydanie 0.12.0 → `RAPORT_0.12.0.md` (sha256 w wiadomości do użytkownika i na stronie wydania).
11. [x] Po pomiarze CI 43228784364: angielski opis „Najważniejszych” → fakt po polsku; kontrola jakości to wykrywa; napisy z ekranu w zapytaniu opisane jako „nie druga osoba”.

### Świadomie NIE zrobione w 0.12.0 (wymaga komputera użytkownika albo decyzji)
- Whisper int8 / wczytanie w trakcie opisu kadrów — dopiero po `--zmierz-czasy` na karcie użytkownika.
- Większy model do czatu — narzędzie jest (`--zapytaj "folder" "pytanie" [model]`), pomiaru nie było.
- Podpis instalatora (SmartScreen) — koszt i formalności, patrz `docs/badania_0.12.md`.
- Test na drugim komputerze i prawdziwa instalacja Ollamy z przycisku — tylko użytkownik może to sprawdzić.

### Przerwy w pracy
Sesja robocza zatrzymywała się między wiadomościami użytkownika (ok. 00:45–09:21 i 09:40–14:21 dnia 12.11), więc praca
„przez całą noc” nie była możliwa; wszystko powyżej powstało w trzech odcinkach.

## Dane testowe
`tests/data/filmy_0119/*.json` — 4 filmy z 0.11.9 (tortilla PL, pancake_touch, wisdm_moda, dokument_ambasada):
segmenty, tłumaczenie pl, napisy z ekranu, sceny kadrów.

## Notatki
- Stare wyniki dokumentu: `streszczenie_kroki.json` w załącznikach rozmowy (nie w repo).

## Następna wersja (zgłoszenia po 0.12.0)
- [ ] Opis autora (YouTube, Instagram, TikTok, Facebook) jako źródło [opis]: do streszczenia, czatu i raportu; filtr linków afiliacyjnych, hashtagów i „subskrybuj”. Opis jest już pobierany (`fetch.py`, pole `opis` w analiza.json), ale nieużywany. TikTok/Facebook — do sprawdzenia na linkach użytkownika.
- [ ] Imiona bez spolszczania („Michał” → „Michael”), mniej faktów bez kontekstu, bez krótkich cytatów-pytań, kontrola nazw/liczb spoza transkrypcji (analiza dokumentu z 13.11).
