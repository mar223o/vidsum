# Vidsumly 0.13.0: nazwa wszędzie, plik dla LLM, fiszki, poprawki po analizie dokumentu

Ostatnie wydanie tego etapu. Wszystkie zmiany pochodzą z Twoich próśb i z Twojej analizy dokumentu na 0.12.0 (13.11).

## Co nowego
- **Nazwa „Vidsumly” wszędzie:**
  - instalator `Vidsumly-Setup-0.13.0.exe`, a w środku `Vidsumly.exe` i `Vidsumly Start`;
  - folder programu `AppData\Local\Programs\Vidsumly`;
  - dane: `%LOCALAPPDATA%\Vidsumly`, wyniki: `Dokumenty\Vidsumly`, dziennik: `vidsumly.log`.
  - **Stare foldery „VidSum” są przenoszone automatycznie** przy pierwszym uruchomieniu (zmiana nazwy, nic nie jest kasowane). Ścieżki w ustawieniach i kolejce są poprawiane. Gdy stary folder jest zajęty, program dalej używa starego.
  - Instalator zamyka starą wersję uruchomioną ze starego folderu i usuwa ten folder.
  - W wydaniu jest też `VidSum-Setup-0.13.0.exe`, żeby wersja 0.12.0 znalazła aktualizację.
  - Bez zmian zostały wewnętrzna nazwa kodu (`vidsum`) i repozytorium, bo nie są widoczne.
- **„Kopiuj dla LLM” i plik `dla_llm.md`** w każdym wyniku, gotowy do wrzucenia do NotebookLM, Claude albo ChatGPT. Zawiera:
  - metadane;
  - legendę źródeł;
  - fakty, kroki i cytaty z odwołaniem do linii (`[L41 02:33]`);
  - pełną transkrypcję w ponumerowanych liniach (oryginał | tłumaczenie);
  - napisy z ekranu i kadry oznaczone jako automatyczne.

  Działa też dla starszych analiz.
- **Fiszki** (nowa zakładka), bez zgadywania:
  - luka w zdaniu-fakcie (liczba, data, nazwa → „____”);
  - ilości składników;
  - serie ćwiczeń;
  - kroki po kolei.

  Przycisk „Kopiuj do Anki”.
- **Mapa myśli** pokazuje fakty w rozdziałach dokumentu. Wcześniej rozdziały dokumentu nie miały gałęzi.
- **Imiona bez spolszczania:** „Michał chce postawić…” → „Michael chce postawić…”, z polską odmianą („Michaela”). Działa w tłumaczeniu i w streszczeniu.
- **Fakty:** bez zdań odsyłających do poprzedniego, które bez liczby i nazwy nic nie mówią (np. „Praktycznie zdarza się to tylko wtedy…”).
- **Cytaty:** w filmach dłuższych niż 5 min co najmniej 5 słów, najwyżej jedno pytanie (bez „Something like data?”).
- Odpowiedzi czatu mają klikalne czasy `mm:ss`. To działało już wcześniej; teraz jest w teście.

Wycofane na Twoją prośbę: opis autora jako źródło, quiz. Opis autora nadal jest widoczny w zakładce „Opis”, tak jak wcześniej.

## Testy
222 testy przechodzą, 3 pominięte (tylko Windows). W tym test na odpowiedziach modelu z Twojej analizy dokumentu z 13.11 (`tests/data/model_0120/dokument_ambasada_0120.json`):
- brak „Michał”;
- fakty 343 mln i 54 centra policji są;
- brak „In practice, that…”;
- brak „Something like data?”.

Na GitHubie budowa Windows i test przeniesienia instalacji z folderu „VidSum” do „Vidsumly”.

## Czego nie przetestowałem
- **Prawdziwej aktualizacji 0.12.0 → 0.13.0 na Twoim komputerze**, z przeniesieniem folderów `Dokumenty\VidSum` i `%LOCALAPPDATA%\VidSum`. Test na serwerze symuluje tylko starą instalację.
- Fiszek i przycisku „Kopiuj dla LLM” w oknie programu na Windows. Sprawdzona jest logika i składnia, nie wygląd.
- Granic modelu 4B. Streszczenie potrafi dopisać związki przyczynowe, których w filmie nie ma. Fakty i cytaty są dosłowne, streszczenie nie.
