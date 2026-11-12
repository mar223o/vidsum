Odpowiedzi PRAWDZIWEGO modelu (gemma3:4b, Ollama na runnerze GitHuba, workflow `pomiar-streszczenia`,
przebieg 43121885545 z 2026-11-12, gałąź `wip-0.12.0`) na zapytania streszczania czterech filmów z
`tests/data/filmy_0119`. Każdy plik: lista `{etap, odpowiedz}` w kolejności zapytań (odpowiedź obcięta w dzienniku
do 2500 znaków; w `dokument_ambasada.json` domknięty ręcznie nawias obciętego „opis_calosci”).

Służą do testów „na odtworzeniu”: nowy kod dostaje te same odpowiedzi, które model naprawdę dał, m.in.
`"fakty"` z 20–40 kolejnymi numerami linii, `"cytat"` jako tekst zamiast numeru, `"t"` w minutach albo jako numer linii,
„(linia 8)” w streszczeniu, klucz `"ilość"` zamiast `"ilosc"`.

`pancake_touch.json`: odpowiedzi „fakty” i „opis” były w dzienniku obcięte — uzupełnione z pełnego raportu tego samego
przebiegu (12 ćwiczeń, sprzęt, wskazówki), bez zmiany treści.
