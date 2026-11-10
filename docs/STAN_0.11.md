# Stan prac 0.11.0 (punkt wznowienia)

Zadanie: MASTER EXECUTION PROMPT (19 etapów) — autonomicznie. Gałąź robocza: `wip-0.11` (main = wydanie).

## Audyt (skrót)
- Backend: `gui.py` (serwer HTTP + Worker = 1 wątek, kolejka FIFO w pamięci, bez zapisu), `pipeline.py` (analiza),
  `summary.py` (streszczenie, PL), `translate*.py`, `llm.py` (Ollama/Claude), `tools.py` (ffmpeg przez subprocess.run).
- Zamykanie: X → potwierdzenie → `srv.shutdown(); os._exit(0)`. Procesy ffmpeg/ffprobe uruchomione przez
  `subprocess.run` mogły zostać osierocone (Windows nie zabija dzieci). Ollama: program jej nie uruchamia (usługa
  użytkownika) — nie wolno jej zabijać; można tylko zwolnić wczytane modele (`keep_alive: 0`).
- Kolejka: brak usuwania, kolejności, pauzy, ponawiania, deduplikacji i odzyskania po restarcie.
- Dashboard: „Ostatnio” (karty) + „W toku” — ostatnie wyniki mają być tylko w Bibliotece.
- Ustawienia: schowane w `<details>` na stronie głównej; „Zakończ” jako przycisk w pasku.
- Wskaźnik „ffmpeg” = dostępność ffmpeg+ffprobe (`/api/status`), nie stan pracy.
- Aktualizacja: `update.py` — „kod” podmienia folder `vidsum` (stary → `vidsum.stare`, sprzątany przy starcie),
  „pełna” = instalator Inno Setup ([InstallDelete] usuwa `{app}\vidsum`). Dane użytkownika (`%LOCALAPPDATA%\VidSum`,
  `Dokumenty\VidSum`) poza folderem programu.

## Zadania
Wszystkie zrobione w 0.11.0, oprócz punktów z RAPORT_0.11.0.md, sekcja H (m.in. streszczenie najpierw w języku
oryginału i wznawianie od przerwanego etapu). Następny krok: pomiary na komputerze użytkownika.
