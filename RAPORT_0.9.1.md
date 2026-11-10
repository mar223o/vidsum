# VidSum 0.9.1: poprawki po Twoich pomiarach 0.9.0

## Pomiar 0.9.0 (frytki 58 s, Twój komputer)
| | 0.8.2 | 0.9.0 | cel |
|---|---|---|---|
| bez szybkiego podglądu | 1:39 | **1:20** | 50–90 s ✓ |
| z szybkim podglądem | 2:20 | **1:36**, podgląd po 29 s | < 2:00 ✓ |
| opis kadrów | 38 s (20 kadrów) | 21–26 s (15 kadrów, 1,4–1,8 s/kadr) | |

Oba przebiegi: 22 kroki, 1 cm, 140 °C i 190 °C w dobrych krokach. Działają też poprawki z 0.8.3: „ziemniaki agria”,
„sól Maldon”, „Wrzuć frytki”, „Wyjmij je”, bez „miodu”.

## Poprawki
**1. Modele z poprzedniej analizy zwalniane na starcie.**
W przebiegu bez podglądu na karcie było zajęte 5,5 GB, w tym gemma3:4b (3,1 GB) z analizy sprzed chwili. Ollama trzyma
model 5 minut. Skutki:
- model obrazu wczytywał się 17,4 s zamiast ~10 s, a kadry czekały na niego 10 s;
- kadry szły 1,8 s zamiast 1,4 s;
- ostrzeżenie mówiło o „innych programach”.

Teraz program na starcie zwalnia z karty modele, których ta analiza zaraz nie użyje, i zapisuje to w przebiegu.
Raport pokazuje osobno: „modele z poprzedniej analizy (zwolnione na starcie)” i „inne programy” (już bez nich).

**2. Cytaty z dokładnym tekstem i czasem.**
Model podawał cytat przerobiony i z innym czasem:
- „This will add a beautiful crispy layer.” przy 0:13;
- „To add a beautiful crisping layer.” przy 0:13.

W filmie pada „This is going to add a beautiful crispy layer.”, i to przy 0:34. Teraz cytat, który przejdzie kontrolę,
dostaje dokładny tekst i czas z transkrypcji. Dwa „cytaty” tego samego zdania są łączone w jeden.

**3. „Szczera ocena” bez fałszywego „brakuje”.**
W obu przebiegach: „brakuje informacji o … dokładnej temperaturze oleju”, a kroki podają 140 i 190 stopni.
- Z wyliczenia znika tylko pozycja, której kroki przeczą (temperatura, czas). Prawdziwe braki zostają: „brakuje
  informacji o czasie smażenia, proporcjach składników.”
- Zdanie, które samo podaje liczbę („w temperaturze 190 °C”), zostaje.
- Ta sama kontrola dotyczy „Czego nie wiadomo”.

**4. Terminy:**
- „parz/blanszuj w oleju” → „wstępnie smaż/blanszuj w oleju”;
- „blanshować” → „blanszować”;
- poprawiony przypadek: „o odpowiednim wstępnym smażeniu” (w 0.8.3 było „wstępnemu”).

## Testy
- 111 testów przechodzi (2 pominięte, bo działają tylko na Windows). Nowe testy:
  - cytaty z Twoich przebiegów: dokładny tekst i czas, bez duplikatu, bez doklejania następnego zdania, zmyślony usuwany;
  - fałszywe „brakuje”: usuwane, a prawdziwe braki i zdania z liczbą zostają;
  - terminy z tego pomiaru;
  - zwalnianie modelu z poprzedniej analizy przed opisem kadrów i opis w raporcie.

## Czego nie przetestowałem
- **Czasu na Twojej karcie po zwolnieniu starego modelu.** Spodziewam się, że kadry zaczną się wcześniej (model obrazu
  ~10 s zamiast 17 s), ale to szacunek.
- **Tłumaczenia całości na EN na prawdziwym modelu.** Nie przysłałeś jeszcze wyniku z przełącznika EN.

## Znane, jeszcze nie poprawione
- Rozdział „Gotowanie ziemniaków 0:24–0:45” obejmuje też mąkę, chłodzenie i rozgrzewanie oleju. Model podaje złe początki
  rozdziałów (20 s, 22 s, 42 s), a program pomija tytuły, które nie pasują do kroków w pobliżu.
- Streszczenie czasem łączy dwa etapy w jednym zdaniu („gotowanie z sodą … aby usunąć skrobię”, a skrobię usuwa
  moczenie).
- Opisy kadrów z modelu obrazu bywają złe („czekolada”, „zioła”, „papier toaletowy”). Nie trafiają do kroków ani
  streszczenia, tylko do osi czasu.
