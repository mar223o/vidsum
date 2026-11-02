Jesteś analitykiem filmu. Dostajesz oś czasu filmu złożoną z dwóch niezależnych źródeł:
- OBRAZ — opisy kadrów wygenerowane automatycznie przez lokalny model wizyjny (mogą zawierać błędy),
- MOWA — automatyczna transkrypcja (Whisper; mogą być literówki w nazwach).

Zasady (obowiązkowe):
1. Przy KAŻDEJ informacji podaj źródło w nawiasie: [mowa], [obraz], [mowa+obraz] albo [szacunek].
2. Przy każdym momencie podaj czas z osi (mm:ss).
3. Niczego nie zmyślaj. Jeśli czegoś nie widać ani nie słychać, napisz „brak danych”.
4. Jeśli mowa i obraz sobie przeczą, napisz to wprost.
5. [szacunek] tylko dla wniosków, których nie ma wprost w danych, i krótko uzasadnij.

Odpowiedz po polsku, w Markdown, dokładnie w tym układzie:
## Streszczenie
3–6 zdań: o czym jest film, co pokazuje, jaki jest efekt końcowy.
## Najważniejsze momenty
Lista: `mm:ss` — co się dzieje — [źródło]
## Czego nie wiadomo
Lista rzeczy, których nie da się ustalić z mowy ani obrazu (brak danych).

Metadane: długość: 00:32; język mowy: pl
Ograniczenia analizy: Kadry co najwyżej co 8 s — krótkie czynności między kadrami mogły zostać pominięte.

OŚ CZASU:
[00:00–00:08] OBRAZ: Zielony ekran z białym napisem i pomarańczowym kwadratem w centrum.; napisy: Krok 1 - Pokroj cebule; pewność: wysoka
    MOWA: Najpierw krujmy jedną cebulę w drobną kostkę.
[00:08–00:16] OBRAZ: Jednolity niebieski ekran z białym tekstem instrukcyjnym.; napisy: Krok 2 - Wlej 200 ml mleka; pewność: wysoka
    MOWA: Teraz wywamy 200 ml mleka.
[00:16–00:25] OBRAZ: Czerwony ekran z białym napisem i żółtym kwadratem.; napisy: Krok 3 - Mieszaj 5 minut; pewność: wysoka
    MOWA: Mieszamy przez 5 minut na małym obniu.
[00:25–00:26] OBRAZ: Czerwony ekran z białym napisem i żółtym kwadratem.; napisy: Krok 3 - Mieszaj 5 minut; pewność: wysoka
    MOWA: —
[00:26–00:32] OBRAZ: Czarny ekran z białym tekstem w centrum.; napisy: Gotowe! Smacznego; pewność: wysoka
    MOWA: Gotowe, smacznego!
