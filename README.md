# VidSum — prototyp (faza 1)

Film (plik MP4 albo link) → **mowa** (Whisper) + **obraz** (kadry + lokalny model wizyjny) → oś czasu → **streszczenie**,
w którym przy każdej informacji jest źródło: `[mowa]`, `[obraz]`, `[szacunek]` albo „brak danych”.

Na tym etapie to program z wiersza poleceń, wymaga Pythona. W fazie 2 zostanie z niego `.exe` z interfejsem.

## Co powstaje w folderze wyników
| plik | zawartość |
|---|---|
| `raport.md` | streszczenie + oś czasu z kadrami + pełna transkrypcja |
| `analiza.json` | wszystko w stałym formacie — opis: `docs/format_json.md` |
| `prompt_dla_claude.md` | gotowy prompt — wklej do claude.ai (Pro), jeśli nie używasz `--streszczenie claude` |
| `transkrypcja.srt` | napisy |
| `kadry/` | wybrane kadry JPG |

## Uruchomienie na Windows (PowerShell) — test prototypu

Uwaga: te kroki instalują Pythona, ffmpeg i Ollamę. Gotowy `.exe` z fazy 2 nie będzie wymagał Pythona.

```powershell
# 1. Narzędzia (jednorazowo)
winget install Python.Python.3.12
winget install Gyan.FFmpeg
winget install Ollama.Ollama
# zamknij i otwórz PowerShell ponownie, potem:
ollama pull qwen3-vl:4b-instruct

# 2. Program (w rozpakowanym folderze vidsum)
cd "$env:USERPROFILE\Downloads\vidsum"
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Test na filmie z paczki (polskie znaki w ścieżce)
python -m vidsum "tests\data\Filmy testowe ąęś\przepis żółć test.mp4" --jezyk pl

# 4. Twój film / link
python -m vidsum "C:\Users\Jan\Videos\przepis.mp4"
python -m vidsum "https://www.youtube.com/watch?v=..."
python -m vidsum "https://www.instagram.com/reel/..." --ciasteczka-z edge
```

Jeśli `Activate.ps1` jest zablokowany: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Najważniejsze opcje
| opcja | domyślnie | opis |
|---|---|---|
| `--jezyk auto/pl/en` | auto | język mowy |
| `--whisper small/medium/large-v3` | small | `medium` = lepszy polski, wolniej |
| `--model-obrazu` | `qwen3-vl:4b-instruct` | `qwen3-vl:8b-instruct` dokładniejszy, ledwo mieści się w 8 GB VRAM |
| `--streszczenie auto/ollama/claude/brak` | auto | `auto` = Claude Code (Pro), jeśli jest zainstalowany; inaczej lokalny model (słabszy) |
| `--obraz brak` | — | bez modelu wizyjnego (same kadry + mowa) |
| `--max-kadrow N` | 40 / 80 / 150 | zależnie od długości filmu |
| `--ciasteczka-z edge/chrome/firefox` | — | dla Instagrama/TikToka, gdy wymagają logowania |

Kilka plików naraz: `python -m vidsum film1.mp4 film2.mp4 ...` — błąd w jednym nie zatrzymuje reszty.

## Streszczenie przez Claude Pro
- **Bez instalacji:** otwórz `prompt_dla_claude.md`, skopiuj całość do claude.ai.
- **Z programu:** zainstaluj Claude Code, zaloguj się kontem Pro (`claude`, potem `/login`), uruchamiaj z `--streszczenie claude`.
  Program odmówi, jeśli ustawiona jest zmienna `ANTHROPIC_API_KEY` (wtedy Claude Code liczyłby płatne API).

## Testy (programisty)
```
pip install pytest
python -m pytest -q
```

## Claude: skill i serwer MCP (od 0.6)

**Skill** (`skill/SKILL.md`) — ta sama procedura, gdy wrzucasz film prosto do czatu z Claude: kadry w arkuszach 3×3
z czasem (Claude sam je ogląda), Whisper, wynik w układzie VidSum. Skrypty są wbudowane w SKILL.md.

**Serwer MCP** — Claude Desktop / Claude Code uruchamia VidSum na Twoim komputerze
(„przeanalizuj C:\Users\Jan\Videos\przepis.mp4”). Narzędzia: `analizuj_film`, `lista_analiz`, `pobierz_analize`.

Claude Desktop — dopisz do `%APPDATA%\Claude\claude_desktop_config.json`:
```json
{ "mcpServers": { "vidsum": { "command": "C:\\Users\\Jan\\Programy\\VidSum\\VidSum.cmd", "args": ["--mcp"] } } }
```
(ścieżkę dopasuj do miejsca, gdzie rozpakowałeś program; dla wariantu .exe: `VidSum.exe`). Uruchom Claude Desktop ponownie.

Claude Code (PowerShell):
```powershell
claude mcp add vidsum -- "C:\Users\Jan\Programy\VidSum\VidSum.cmd" --mcp
```
