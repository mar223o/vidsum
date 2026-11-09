# VidSum 0.7.10: krótszy etap streszczenia, poprawki składników

Pomiar na karcie (0.7.9, frytki): całość 3 min 40 s, a samo streszczenie 1 min 29 s.

- **Opis całości się zapętlał.** Model wypisywał dziesiątki wariantów tytułu w polu `tytul_akcent`, aż doszedł do
  limitu 3000 tokenów. Zdarzyło się to dwa razy z rzędu, bo druga próba była identyczna (temperatura 0, to samo
  ziarno). Strata wyniosła ok. 60 s. Poprawki:
  - pole usunięte;
  - limit długości odpowiedzi 1600 tokenów;
  - przy pustym wyniku od razu krótsze polecenie z innym ziarnem, bez powtarzania tego samego.
- **Składniki.** Skrobia ziemniaczana nie wypada już jako „duplikat” ziemniaków (duplikat liczy się tylko przy tych
  samych słowach). Poprawione nazwy: „sol” → „sól”, „malon” → „Maldon”.

Czego nie sprawdziłem: czasu na karcie. Pętla modelu zależy od treści i u mnie na procesorze nie wystąpiła tak samo.
Test sprawdza tylko, że druga próba idzie innym poleceniem.
