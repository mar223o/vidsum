# Vidsumly 0.13.2 (gałąź `wip-0.13.2`, jeszcze nie wydane)

Zmiany po Twoich prośbach z 14.11.2026.

## Postęp na żywo
- Zamiast „Etap 2/4 · kadry” i „zostało ok. 3 min” program pokazuje:
  - co robi teraz, np. „Opisuję kadry · 7 z 20 kadrów”;
  - procent ukończenia i pasek;
  - licznik „zostało 2:14”, który odlicza co sekundę;
  - numer etapu, np. „etap 4 z 5”, i listę etapów.
- Etapy zależą od trybu:

  | Tryb | Etapy |
  |---|---|
  | Pełna | Przygotowanie → Mowa → Kadry → Opis obrazu → Streszczenie |
  | Mowa + szybki obraz | Przygotowanie → Mowa → Streszczenie → Szybki obraz |
  | Tylko mowa | Przygotowanie → Mowa → Streszczenie |
  | Sama transkrypcja | Przygotowanie → Mowa → Tłumaczenie (jeśli włączone) |

- W trybach „Tylko mowa” i „Sama transkrypcja” nie ma już etapu kadrów. Robienie kilku miniatur liczy się do przygotowania.
- W „Samej transkrypcji” kolumna streszczenia mówi wprost, że w tym trybie streszczenia nie ma, zamiast czekać na nie.
- Skąd biorą się liczby:
  - **Procent:** dla opisu kadrów to liczba opisanych kadrów. Dla pozostałych etapów to czas od startu etapu w porównaniu z przewidywanym czasem tego etapu.
  - **Udziały etapów w całym czasie:** program uczy się ich z poprzednich analiz na tym komputerze (`czasy_trybow.json`, nowe pole `etapy`). Na start bierze:
    - dla trybu „Pełna” udziały z pomiaru `frytki_0114`;
    - dla pozostałych trybów szacunek, który zastąpią pierwsze własne pomiary.
  - **„Zostało”:** na początku liczone z prognozy z historii. W miarę postępu coraz bardziej z tempa tej analizy, a od połowy analizy już tylko z tempa.

## Biblioteka: „Wyczyść bibliotekę”
- Po kliknięciu przycisku klikasz filmy, które mają zostać. Licznik pokazuje „Zostaje: 2 · Do Kosza: 3”.
- Pierwsze kliknięcie „Przenieś do Kosza” zamienia przycisk na „Na pewno?”. Dopiero drugie kliknięcie usuwa.
- Foldery trafiają do Kosza Windows, więc da się je przywrócić.
  - Na dysku bez Kosza (pendrive, dysk sieciowy) trafiają do folderu `kosz` w danych Vidsumly.
  - Nic nie znika bez śladu.
- Program usuwa tylko gotowe analizy z folderu wyników. Analizy w toku i foldery spoza folderu wyników są pomijane.
- Gdy działa wyszukiwanie albo filtr typu, czyszczenie dotyczy tylko widocznych filmów i program to pisze.

## Kolory i układ
- **Tryb ciemny:** czarne tło, kremowy tekst #F5EFE6, akcent błękit #38BDF8, drugi kolor lawenda #C4B5FD.
- **Tryb jasny:** kremowe tło, czarny tekst, czarny główny przycisk.
- Pasek postępu i przyciski na gradiencie mają gradient od błękitu do lawendy.
- Pasek tytułu okna w Windows też jest w tych kolorach.
- Drobne poprawki układu:
  - mniejszy nagłówek strony głównej;
  - przełącznik trybów zawija się na wąskim oknie (wcześniej wychodził poza ekran);
  - filtr typów w Bibliotece przewija się w poziomie;
  - wiersz kolejki w toku bez powtarzanego „trwa”.

## Logo
- Kadr taśmy filmowej z perforacją, a w nim błękitny „play” i kremowe linie streszczenia. W rogu lawendowa iskra.
- Inspiracja: Twoje dwa obrazki. To własny rysunek, nie kopia.
- Przy 16–24 px jest uproszczona wersja bez perforacji i linii.

## Testy
- Linux: 252 testy przeszły, 3 pominięte. W tym nowe:
  - `tests/test_0132.py`: postęp w każdym trybie, nauka udziałów etapów;
  - prawdziwy przebieg analizy, w którym postęp idzie tylko do przodu i kończy się na 100%;
  - czyszczenie biblioteki wraz z odmowami;
  - przeglądarka (Playwright): pasek, licznik i czyszczenie z zaznaczaniem.
- Windows (GitHub Actions, budowa testowa bez wydania): `tests/win_trash_check.py` sprawdza, że folder ląduje w Koszu systemu.

## Czego nie przetestowałem
- Dokładności licznika „zostało” na Twoim komputerze z prawdziwymi modelami. Pierwsze analizy w trybach innych niż „Pełna” startują z szacunku, a każda kolejna poprawia udziały.
- Przywracania z Kosza w Eksploratorze. Test na Windows sprawdza tylko, że folder jest w Koszu.
- Wyglądu ikony na Twoim pasku zadań i pulpicie.
