# Vidsumly 0.11.1: wzorzec kadrów, porównanie modeli obrazu, poprawki z pomiaru 0.11.0

## Twój pomiar 0.11.0 (frytki 58 s)
- **Czas:** 1:35. Wstępne streszczenie pojawiło się po 25 s, czyli tak samo jak w 0.9.0 z podglądem.
- **Gdzie ucieka czas:**
  - poprawka mowy (16,3 s) poszła po opisie kadrów, a nie równolegle: inne programy zajmowały 1,5 GB karty i zostało
    1330 MB wolnego;
  - model obrazu wczytywał się 11 s po podglądzie;
  - model tekstowy wczytywał się drugi raz (14 s).

## Kadry: jak naprawdę wypadł qwen3-vl
Twoje 15 kadrów opisałem ręcznie jako wzorzec (`vidsum/wzorce/frytki_kadry.json`). Program ocenia opisy według tego
wzorca: czy padły słowa, które pasują do kadru, i czy padło słowo, którego na kadrze nie ma.

**qwen3-vl z Twojego przebiegu:**
- 4 kadry z błędnym słowem:
  - 0:22 „wycierka zlew”: zlewu nie ma, kucharz trzyma miskę;
  - 0:28 „trzyma nóż”: to łyżka z sodą;
  - 0:43 „czekolada”: to frytki w oleju 140 °C;
  - 0:48 „zioła”: to frytki na łyżce cedzakowej.
- Trafność: między 0,6 a 0,85 (to próg w teście; dokładnej liczby nie wypisywałem). Dużo ogólników („coś”, „składnik”)
  zamiast „frytki” i „łyżka”.
- Te liczby pochodzą z Twojego przebiegu; test je sprawdza.

**Nowe polecenie do porównania modeli obrazu na Twojej karcie:**
```powershell
& "$env:LOCALAPPDATA\Programs\VidSum\python\python.exe" -m vidsum --porownaj-modele-obrazu "C:\Users\marek\Documents\VidSum\The Perfect French Fry_20261110-212853"
```
- Opisuje te same kadry modelami qwen3-vl:4b-instruct i gemma3:4b, tak jak program.
- Gemma dostaje ten sam kontekst co model tekstowy.
- Mierzy czas wczytania i opisu, liczy trafność i błędne słowa według wzorca.
- Wynik zapisuje do `porownanie_modeli_obrazu.md` w folderze analizy.
- Ścieżka do `python.exe` zakłada instalację instalatorem. W wersji z `VidSum.exe` zamiast tego:
  `VidSum.exe --porownaj-modele-obrazu "folder"`.

## Poprawki treści (z Twojego wyniku)
- **„powinny pękać bez łamania” → „powinny łamać się, ale nie pękać”.** W filmie pada „break without snapping”, a model
  odwracał sens. Poprawka działa też w tłumaczeniu transkrypcji („Powinny się łamać bez pękających”).
- **„na ostateczny smaż” → „przed ostatecznym smażeniem”.**
- **„Smaż, aż złoty i chrupiący” → „Smaż, aż będą złote i chrupiące”.**
- **„dodatkowy chrupkość” → „dodatkowa chrupkość”.**
- **„w wyższym tempie (190°C)” → „w wyższej temperaturze”.**
- **Zgubiony krok „Obierz” (0:13):** gdy model dwa razy nie odpowie na jednowyrazowe polecenie („Peel.”, „Drain.”,
  „Stir.”…), a polskie tłumaczenie linii jeszcze się liczy, program wstawia stałe tłumaczenie.
  - Twojego przebiegu nie odtworzyłem w 100%. Brakuje mi napisów z ekranu z tego przebiegu (analiza.json).
  - Odtworzenie bez nich dało krok „Obierz.”, więc nie mam pewności, czy właśnie to było przyczyną.
- Wszystkie poprawki działają tylko wtedy, gdy dany zwrot pada w filmie (warunek w oryginale).

## Testy
- 131 testów przechodzi, 3 pominięte (tylko Windows; uruchomią się w budowie).
- Nowe testy:
  - wzorzec i ocena opisów qwen z Twojego przebiegu;
  - porównanie dwóch modeli (atrapa Ollamy): tabela, ocena, kontekst gemmy;
  - poprawki terminów;
  - stałe tłumaczenie „Peel.” przy milczącym modelu.

## Czego nie przetestowałem
- **Gemmy jako modelu obrazu na tych kadrach.** Tu nie ma karty ani Ollamy; od tego jest polecenie wyżej.
- **Jakości całego streszczenia po poprawkach na prawdziwym modelu.**

## Znane, niepoprawione
- **„Najważniejsze”:** „wstępne smażenie pomaga rozbić strukturę ziemniaków”. W filmie rozbija je soda w wodzie (0:26).
  Związek przyczynowy zmyślony; nie mam jeszcze ogólnej kontroli takich błędów.
- **Rozdział „Gotowanie w wodzie z sodą” trwa 0:24–0:50**, czyli obejmuje też smażenie.
- **„Drain just lightly with potato starch”:** Whisper źle rozpoznał słowo, na ekranie jest „dust”. Program poprawia
  pojedyncze słowa według napisów z ekranu, ale nie zamianę dwóch słów na jedno. Tłumaczenie transkrypcji daje przez to
  „Odcedź lekko…”; kroki są dobre („Oprósz lekko mąką”).
