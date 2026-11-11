# Vidsumly 0.11.9: pomiar, gdzie da się odzyskać czas

## Dlaczego najpierw pomiar
W Twoim przebiegu „Najszybciej” (1:09) po opisie kadrów (34 s) dzieją się naraz dwie rzeczy:
- poprawka mowy Whisperem: 16 s;
- wczytanie modelu tekstowego (gemma): 13 s, w tle.

Streszczenie startuje dopiero po dłuższej z nich. Gdyby Whisper szedł równolegle z opisem kadrów, streszczenie i tak
czekałoby na gemmę. Pewny zysk to więc ok. **3 s, a nie 14**. Więcej da się odzyskać tylko wtedy, gdy:
- Whisper zmieści się obok qwena (dziś wolne jest 1,5–1,7 GB, próg 2,5 GB);
- albo gemma wczyta się szybciej niż 13 s.

Nie wiem, ile zajmuje sam Whisper (wczytanie vs rozpoznanie) ani ile pamięci potrzebuje wersja int8. To trzeba zmierzyć
na Twojej karcie.

## Zmiany
- **`VidSum.exe --zmierz-czasy "folder analizy"`** zapisuje w folderze `pomiar_czasow.md` i `.json`:
  1. Whisper sam na karcie, float16 (jak dziś) i int8_float16: wczytanie, rozpoznanie, najmniej wolnej pamięci,
     **zgodność tekstu z transkrypcją z analizy** (żeby nie przyspieszyć kosztem jakości);
  2. opis kadrów (2 naraz, jak w programie) sam i z Whisperem w tym samym czasie: czy się mieści, ile trwa;
  3. wczytanie gemmy: okno 8192 (jak w programie) na zimno i na ciepło oraz 4096.
- **Log analizy** rozbija poprawkę mowy na wczytanie Whispera, rozpoznanie i drugi przebieg.

## Testy
148 testów przechodzi, 3 pominięte (tylko Windows). Pomiar sprawdzony na atrapach, w tym brak pamięci przy pracy równoległej.

## Czego nie przetestowałem
- Pomiaru na prawdziwej karcie: tu nie ma GPU ani Ollamy.
- Ile wolnej pamięci zostawia qwen przy 2 kadrach naraz. To pokaże dopiero pomiar.
