# Vidento 0.10.0 (dawniej VidSum): nowa marka, zakładki bez przewijania, tryb kinowy, rozdziały z paskami, komentarze, lepszy czat

Nazwa techniczna zostaje: polecenie `VidSum`, folder `%LOCALAPPDATA%\VidSum`, `analiza.json` (`"narzedzie": "VidSum"`),
serwer MCP `vidsum`, identyfikator instalatora (AppId). Stare skróty i wyniki działają dalej.

## 1. Jaki model ma VidSumm
**Nie udało się tego ustalić z publicznych źródeł.** Pod podobnymi nazwami działa kilka produktów:
- rozszerzenie Chrome „VidSumm – YouTube Video Summarizer” ([Chrome Web Store](https://chromewebstore.google.com/detail/VidSumm%20-%20YouTube%20Video%20Summarizer/jccddiipfockmfemlidldgdbboieeaad), [creati.ai](https://creati.ai/ai-tools/vidsumm-youtube-video-summarizer/));
- „VidSum: YouTube Video Summarizer” ([Chrome Web Store](https://chromewebstore.google.com/detail/lnlncmgmjnbhbiijhigaekcfgenpmepg/reviews?hl=en)) i „VidSummize – AI YouTube Summary with Chat GPT” ([Chrome Web Store](https://chromewebstore.google.com/detail/vidsummize-ai-youtube-sum/gidcfccogfdmkfdfmhfdmfnibafoopic));
- aplikacja iOS „Video Summarize VidSum” ([App Store](https://apps.apple.com/app/id6746120652));
- pakiet Pythona `vidsum` ([PyPI](https://pypi.org/project/vidsum/)).

**Hipoteza (niepotwierdzona):** produkt ze zrzutów to usługa w chmurze na dużym modelu z rodziny GPT (część z tych
rozszerzeń ma „ChatGPT” w nazwie). Na to wskazuje płynny język i wiedza ogólna w czacie. Nie wiem, który to model ani
czy ogląda obraz.

## 2. Jaki model ma Vidento
Wszystko działa lokalnie, na Twojej karcie:
- mowa: faster-whisper `large-v3-turbo` (CUDA);
- opis kadrów: `qwen3-vl:4b-instruct` (Ollama);
- streszczenie, kroki, czat i tłumaczenie: `gemma3:4b` (Ollama).

Claude jest tylko opcją.

## 3. Co zmieniło się w AI
- **Czat od nowa:**
  - model dostaje transkrypcję z czasami `[mm:ss]`, kroki, tezę i napisy z ekranu, a nie całe streszczenie, więc nie
    wkleja streszczenia jako odpowiedzi;
  - zasady: fakty tylko z filmu, z czasem; gdy film nie podaje liczby, mówi to wprost i podaje, co film mówi zamiast
    niej; wiedza ogólna tylko oznaczona „Wiedza ogólna (nie z filmu):”; na pytania spoza filmu odpowiada, że zna tylko
    ten film;
  - odpowiada w języku pytania. Program liczy polskie i angielskie słowa; wcześniej na „strzelanina w krakowie”
    odpowiadał po angielsku;
  - **kontrola liczb:** jeśli odpowiedź podaje liczbę z jednostką (minuty, stopnie, gramy…), której nie ma w filmie,
    i nie jest oznaczona jako wiedza ogólna, program dopisuje „⚠ Tej liczby nie ma w filmie — to szacunek modelu”;
  - **nowe:** czat dostaje też opisy kadrów, oznaczone jako mniej pewne niż transkrypcja. Film bez mowy nie był
    wcześniej w ogóle „widziany” przez czat.
- **Szybki podgląd bez przełącznika.** Program sam go robi, gdy nic nie kosztuje: ten sam model do obrazu i tekstu albo
  opis kadrów wyłączony. Gdy modele są różne, nie robi go, bo w 0.9.0 przerzucanie modeli dodawało ok. 16 s
  (1:20 → 1:36). Wstępny wynik zawsze ma etykietę „wstępne”, a wynik pusty albo zmyślony się nie pokazuje (kontrole
  z 0.8.x).
- Z 0.9.1: dokładne cytaty z czasem, usuwanie fałszywego „brakuje…”, terminy (soda, Maldon, wstępne smażenie).

## 4. Jakość i 5. Porównanie z VidSumm
Porównałem Twoje zrzuty VidSumm z naszymi wynikami na tym samym filmie (frytki, 58 s):

| | VidSumm (zrzuty) | Vidento 0.9.x (Twoje pomiary) |
|---|---|---|
| odmiana ziemniaków | „transkrypcja nie podaje odmiany” (błąd: pada „agria”) | „ziemniaki agria” |
| sól | „molden” | „sól Maldon” |
| temperatury 140 / 190 °C | są | są, w dobrych krokach |
| styl streszczenia | płynny, naturalny | poprawny, sztywniejszy |
| czat | dobrze odmawia zgadywania | był gorszy (np. zmyślone „20–25 minut”); poprawiony w 0.10.0, patrz pkt 3 |

**Wniosek:** w faktach z tego filmu jesteśmy dokładniejsi. VidSumm pisze ładniej i jego czat był lepszy. Nowego czatu
nie sprawdziłem na Twojej karcie; sprawdziłem go tylko tutaj na gemma3:4b na kilku pytaniach.

## 6. Czasy przed i po
Twoje pomiary (frytki, 58 s, RTX 3070 Ti):

| | 0.8.2 | 0.9.0 |
|---|---|---|
| bez podglądu | 1:39 | 1:20 |
| z podglądem | 2:20 | 1:36 (podgląd po 29 s) |

**0.10.0 nie zmienia szybkości analizy,** więc nie podaję nowego czasu. Celu ~50 s nie osiągnąłem i nie twierdzę, że
jest. Najbardziej obiecuje jeden model do wszystkiego (gemma3:4b także do kadrów): bez przerzucania modeli, Whisper
równolegle, podgląd za darmo. Żeby to sprawdzić, potrzebuję folderu `kadry` z Twojej analizy. Porównam opisy gemma
i qwen na tych samych klatkach.

## 7. Domyślny podgląd
Przełącznik zniknął z ustawień, a podgląd robi się sam (pkt 3). **Ograniczenie:** przy domyślnych modelach (qwen
do obrazu, gemma do tekstu) podglądu teraz **nie ma**, bo kosztowałby ok. 16 s. Pojawi się, gdy przejdziemy na jeden
model.

## 8. Zmiany w wyglądzie
- **Paleta:** jeden akcent, chłodny błękit:
  - tło `#090c12`, panele `#121722`, karty `#171d2a`, tekst `#e9edf5`, drugorzędny `#8b94a9`;
  - akcent `#5b9bff`, gradient `#3d7bff → #38c4ff`;
  - stany: sukces `#3dd9a0`, błąd `#ff7a85`, ostrzeżenie `#f2b84b`;
  - fiolet, róż i żółta iskra zniknęły; jasny motyw ma te same role.
- **Pasek tytułu okna** (Windows 11) w kolorach programu: ciemne tło, jasny tekst i niebieska ramka.
- **Ikona:** niebieski gradient, grubsza ramka, dwie linie, trójkąt „play” i biała iskra. Sprawdzona w rozmiarach
  16–128 px.

## 9. Funkcje ze zrzutów
- **Tryb kinowy:** przycisk pod filmem. Film zajmuje całą szerokość (do 84% wysokości okna), a reszta jest przygaszona
  i rozjaśnia się po najechaniu. Esc zamyka. Przełączanie nie przeładowuje filmu (test to sprawdza), a wybór jest
  zapamiętany.
- **Rozdziały z paskami:**
  - pasek całego filmu z rozdziałami (kliknięcie przewija);
  - przy każdym rozdziale pasek jego udziału i „25% filmu”;
  - rozdziały **od autora** (YouTube) są osobno, na zielono, bo są dokładne; pod nimi rozdziały z analizy.
- **Najważniejsze zwijane:** pierwszy punkt rozwinięty, reszta zwinięta (tytuł i czas widać), plus „Rozwiń wszystkie”.
- **Opis** (nowa zakładka, dla linków): opis od autora z serwisu, z klikalnymi czasami. Ma etykietę „tekst autora, nie
  wynik analizy”.
- **Komentarze** (nowa zakładka, dla linków, na żądanie):
  - przycisk „Pobierz komentarze”: yt-dlp pobiera do 40 najpopularniejszych, bez filmu;
  - zapis w `komentarze.json`, więc drugi raz pojawiają się od razu;
  - etykieta „opinie widzów, nie fakty z filmu”;
  - komentarze **nie** trafiają do streszczenia ani do czatu.
- **Transkrypcja:** bez zmian (już była, z tłumaczeniem).
- **Karuzele:** nie zrobiłem. Cytaty i momenty w kolumnie czyta się łatwiej niż w przesuwanej karuzeli, a w wąskiej
  kolumnie „Breakdown” karuzela schowałaby treść.

## 10. Paleta i logo
Patrz pkt 8. Nazwę widać w oknie, w tytule, w ikonie, w instalatorze, w menu Start i na pulpicie: instalator usuwa stare
skróty „VidSum” i zakłada „Vidento”.

## 11. Pasek „Breakdown”
Zakładki się **zawijają** zamiast przewijać w bok. Każda ma własną ikonę SVG i podpis. Test w przeglądarce sprawdza
szerokości 1280, 1000, 820 i 390 px (10 zakładek):
- pasek nie ma przewijania;
- żaden przycisk nie wystaje;
- strona nie ma poziomego paska.

## 12. Testy
- **120 testów przechodzi** (2 pominięte, bo działają tylko na Windows). Nowe testy:
  - zakładki bez przewijania na 4 szerokościach;
  - rozdziały: paski 25/75%, osobno od autora;
  - najważniejsze: zwijanie i „Rozwiń wszystkie”;
  - opis: czasy klikalne;
  - komentarze: z pliku w przeglądarce; endpoint tylko dla linków, pobiera raz i zapisuje;
  - parsowanie komentarzy (odpowiedzi na końcu, puste pominięte) i rozdziałów od autora;
  - tryb kinowy: ten sam element filmu, cała szerokość, Esc;
  - czat dostaje kadry;
  - podgląd automatyczny tylko, gdy nic nie kosztuje;
  - kolory paska tytułu.
- Naprawione 2 testy, które padły po zmianie nazwy (tytuł okna) i formatu polecenia czatu.

## 13. Ograniczenia: czego nie przetestowałem
- **Pobierania komentarzy i opisu z prawdziwego YouTube.** Tutaj nie mam dostępu do YouTube, więc testy używają
  atrapy yt-dlp. Format pól (`comments`, `chapters`, `description`) wziąłem z yt-dlp, ale w prawdziwym przebiegu go nie
  widziałem. YouTube może też ograniczać pobieranie komentarzy.
- **Koloru paska tytułu na Windows.** Atrybuty DWM 34/35/36 działają od Windows 11 (build 22000). Na Windows 10
  program je pomija, bez błędu.
- **Nowego czatu na Twojej karcie** i czasu analizy 0.10.0 (pkt 6).
- **Wyglądu w oknie WebView2.** Zrzuty robiłem w Chromium.

---

## Nazwa marki: sprawdzone kandydatki
Szukałem w wyszukiwarce: produktów i firm, App Store, GitHuba. **Nie sprawdzałem bezpośrednio** rejestrów domen
ani baz znaków towarowych (EUIPO, UPRP, WIPO), bo nie mam do nich dostępu z tego środowiska. Brak konfliktu poniżej
znaczy tylko „nic nie znalazłem”, **a nie, że nazwa jest prawnie wolna.**

| nazwa | co znalazłem |
|---|---|
| **Vidento** | brak produktu, firmy ani repozytorium o tej nazwie. Podobna nazwa: aplikacja iOS „Videntium” ([App Store](https://apps.apple.com/us/app/videntium/id6754339343)) |
| Kadrio | brak dokładnej nazwy; bardzo podobne „Cadrio” ([Capterra](https://www.capterra.com/p/10048711/Cadrio/)) i „KADRIS 4 Mobile” ([App Store](https://apps.apple.com/us/app/kadris-4-mobile/id1456104426)) |
| Sumvio | brak dokładnej nazwy; podobne „Sumio” ([App Store](https://apps.apple.com/app/id1560198579)) |
| Kadrix | brak produktu; podobny znak „Quadrix” ([Markinton](https://markinton.com/trademark/quadrix-75299260)) |
| Tellvo | brak produktu; podobna firma „Telvero” ([village.ai](https://village.ai/company/telvero)) |
| Vistel | aplikacja „Vistel” ([App Store](https://apps.apple.com/br/app/vistel/id6470592947?l=en-GB)) |
| Scenly | znaki towarowe SCENELY w USA ([Justia](https://trademarks.justia.com/900/24/scenely-90024978.html)) |
| Seenly | istniejący produkt ([GetApp](https://getapp.com.au/software/2072909/seenly)) |
| Gisto | „Gist AI” streszcza wideo YouTube ([topai.tools](https://topai.tools/t/gist-ai)) — za blisko |
| Recapo | „Recapo AI: Audio to Text Notes” ([App Store](https://apps.apple.com/app/id6752839074)) |
| Klarvo | oprogramowanie do EU AI Act ([klarvo](https://klarvo-marketing-pages.pages.dev/)) |
| Glimo | „Glimo — GLP-1 Peptide Tracker” ([App Store](https://apps.apple.com/us/app/id6762262370)) |
| Klipso | podobne „Klipo” ([Shopify](https://apps.shopify.com/klipo)) i „Klypse.app” ([AlternativeTo](https://alternativeto.net/software/klypse-app/about/)) |
| Lumo | asystent AI firmy Proton ([Proton](https://proton.me/blog/lumo-ai)) |
| Frameo | aplikacja do ramek na zdjęcia ([App Store](https://apps.apple.com/pl/app/frameo/id1179744119?l=pl)) |

**Top 5:**
1. **Vidento**: brak konfliktu; „vid” + „-ento” (jak „momento”); łatwe po polsku i angielsku.
2. Sumvio: podobne do Sumio (aplikacja finansowa, inna branża).
3. Kadrix: „kadr” to polski rdzeń; podobne do znaku Quadrix.
4. Kadrio: bardzo blisko Cadrio.
5. Tellvo: blisko Telvero.

**Wybór: Vidento.** Przed publicznym użyciem warto sprawdzić bazy EUIPO, UPRP i WIPO (klasy 9 i 42) i domeny
`vidento.com` / `vidento.ai`.
