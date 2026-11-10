# Vidsumly 0.10.1: ostateczna nazwa

Nazwa wybrana przez Ciebie: **Vidsumly**. Zastępuje „Vidento” z 0.10.0 wszędzie, gdzie ją widać:
- tytuł okna i pasek tytułu;
- logo i tytuł strony;
- komunikaty („Wyłączyć Vidsumly?”, brak połączenia);
- instalator: nazwa, wydawca, „Dodaj lub usuń programy”;
- skróty w menu Start i na pulpicie.

Instalator usuwa stare skróty „VidSum” i „Vidento”. Program sam odświeża ikonę skrótów o każdej z trzech nazw.

Bez zmian (zgodność):
- polecenie `VidSum`, folder `%LOCALAPPDATA%\VidSum` i folder instalacji;
- `analiza.json`, serwer MCP `vidsum`;
- identyfikator instalatora (AppId), więc 0.10.1 aktualizuje 0.10.0, a nie instaluje się obok.

Druga instancja rozpoznaje działający program po każdej z nazw: VidSum, Vidento, Vidsumly.

## Sprawdzenie nazwy
- Wyszukiwanie „Vidsumly” (10.11.2026) nie znalazło produktu, firmy ani aplikacji o tej nazwie. Wyniki pokazały tylko
  inne nazwy, np. Vidly ([CB Insights](https://www.cbinsights.com/company/vidly)).
- **Uwaga:** nazwa jest bardzo blisko produktów „VidSumm – YouTube Video Summarizer”
  ([Chrome Web Store](https://chromewebstore.google.com/detail/VidSumm%20-%20YouTube%20Video%20Summarizer/jccddiipfockmfemlidldgdbboieeaad))
  i „VidSum: YouTube Video Summarizer”
  ([Chrome Web Store](https://chromewebstore.google.com/detail/lnlncmgmjnbhbiijhigaekcfgenpmepg/reviews?hl=en)).
  To ta sama branża (streszczenia wideo), więc ryzyko pomylenia i sporu o znak jest większe niż przy Vidento.
- Nie sprawdzałem baz EUIPO, UPRP i WIPO ani domen `vidsumly.com` / `vidsumly.ai`. **To nie jest potwierdzenie, że nazwa
  jest prawnie wolna.**

## Testy
- Testy okna i strony przechodzą (29), w tym tytuł okna „Vidsumly…” i zakładki na 4 szerokościach.
- Zrzut na 390 px: logo „Vidsumly” mieści się w górnym pasku.

## Czego nie przetestowałem
- Instalacji na Windows z wcześniej zainstalowanym 0.10.0: czy skróty „Vidento” znikną, a „Vidsumly” się pojawią.
  Sprawdza to budowa w GitHub Actions (skrót w menu Start), ale nie na Twoim komputerze.
