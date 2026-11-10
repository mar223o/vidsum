# VidSum 0.9.0: nowy wygląd i tłumaczenie całego wideo PL ↔ EN

## Nowy wygląd: „sala projekcyjna”
Kierunek, który wybrałeś: premium ciemny (jak Linear/Arc).
- **Poświata z filmu:** za nagłówkiem wyniku i odtwarzaczem świeci rozmyty, nasycony kadr z tego filmu (jak tryb kinowy
  na YouTube). Każdy wynik ma kolory swojego filmu.
- **Tło i powierzchnie:**
  - tło to głęboka granatowa czerń z delikatnym fioletowym światłem u góry;
  - panele są jak szkło: półprzezroczyste, z cienką jasną krawędzią u góry i warstwowym cieniem;
  - zaokrąglenia są stopniowane: duże panele, mniejsze elementy, przyciski-pigułki.
- **Kolory marki z ikony** (niebieski → fiolet → róż):
  - główny przycisk „Analizuj”, numery kroków, aktywny etap analizy, wiadomości w czacie;
  - żółta „iskra” tylko dla rzeczy w toku: szybki podgląd, trwająca analiza.
- **Pismo:** Segoe UI Variable, natywne w Windows 11. Nagłówki są ciaśniejsze i grubsze. Zniknęła ozdobna kursywa,
  wielkie litery w etykietach i kropki między informacjami. Czasy mają cyfry równej szerokości.
- **Elementy:**
  - górny pasek ze szkła, z zakładkami-pigułkami;
  - pole „Przeciągnij tu pliki” z obramowaniem w kolorach marki;
  - zakładki wyniku jako przełącznik-pigułka;
  - składniki jako jedna lista w karcie;
  - „Do zapamiętania” z paskiem w kolorach marki;
  - powiadomienia jako pływająca pigułka.
- **Ruch:** jeden moment, czyli wynik „zapala się” jak ekran, gdy przychodzi. Poza tym tylko reakcje na kliknięcia.
  Ustawienie „ogranicz ruch” w systemie wyłącza animacje.
- Jasny motyw i motyw systemowy dalej działają (☾ w górnym pasku). Na telefonie kolumny układają się jedna pod drugą
  i nic nie wystaje poza ekran.

## Tłumaczenie całego wideo (na żądanie)
- W nagłówku wyniku jest przełącznik **„Język wyniku: PL | EN”**. Przycisk pod streszczeniem robi to samo
  („Wersja angielska” / „Wersja polska”).
- Kliknięcie EN tłumaczy **wszystko**:
  - streszczenie, tezę, „Do zapamiętania”;
  - kroki, składniki, sprzęt, wskazówki;
  - rozdziały, najważniejsze, momenty, tłumaczenie cytatów, pytania do czatu, „Czego nie wiadomo”;
  - **opisy kadrów**;
  - **transkrypcję**. Jeśli film jest po angielsku, to oryginał. Jeśli była już przetłumaczona, bierze to
    tłumaczenie, inaczej tłumaczy ją od nowa.
- Tłumaczy lokalny model tekstowy (gemma3:4b), w tle. Pasek pokazuje postęp, a analiza czeka na to tylko wtedy, gdy
  klikniesz. Wynik zapisuje się w `analiza.json` (`tlumaczenie_calosci.en`), więc drugi raz przełącza się od razu.
- Czasy, liczby i oryginał zostają nietknięte. Tekst, którego model nie przetłumaczył, zostaje w oryginale, a program
  mówi, ile takich fragmentów było. Nie wstawia zgadywanego tekstu.
- Na PL wraca od razu, bez tłumaczenia (streszczenie i kadry program i tak pisze po polsku).

## Testy
- 107 testów przechodzi (2 pominięte, bo działają tylko na Windows). Nowe testy:
  - tłumaczenie całości: przetłumaczone są wszystkie pola, czasy bez zmian, oryginał nietknięty, cytat zostaje
    w oryginale, „brak danych” → „no data”;
  - tłumaczenie w drugą stronę (PL): tłumaczy tylko transkrypcję;
  - nieudane linie zostają w oryginale i są policzone; nieobsługiwany język jest odrzucany;
  - tłumaczenie w tle przez program: stan, zapis do `analiza.json`, drugi raz bez liczenia od nowa;
  - w przeglądarce: kliknięcie EN pokazuje wersję angielską (nagłówek, streszczenie, kroki), a powrót na PL działa.
- Przeglądarka (Chromium), wynik na żywo na 1280 i 390 px: czytany fragment się nie przesuwa, nic nie wystaje poza
  ekran. Pierwsza wersja poświaty wystawała na telefonie i test to wyłapał, więc jest poprawiona.
- Zrzuty ekranu: strona główna, wynik w trybach Wideo i Zbalansowany, jasny motyw, telefon. Użyłem Twojego wyniku 0.8.2
  z kadrami podstawionymi, bo filmu nie mam.

## Czego nie przetestowałem
- **Jakości tłumaczenia na prawdziwym modelu.** Testy używają atrapy, więc nie wiem, jak gemma3:4b przetłumaczy
  polskie streszczenie na angielski, ani ile to potrwa na Twojej karcie. Szacuję kilkadziesiąt sekund.
- **Wyglądu w Twoim oknie programu (WebView2)** z prawdziwym filmem i kadrami. Poświata korzysta z rozmycia
  (`filter: blur`), które WebView2 obsługuje, ale okno programu ma wyłączone przyspieszanie grafiki, więc rozmycie
  może być wolniejsze przy przewijaniu.
- Czcionka Segoe UI Variable jest w Windows 11. Na Windows 10 będzie zwykłe Segoe UI.
