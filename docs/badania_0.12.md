# Badania do wersji 0.12.0 — źródła z internetu (stan: 2026-11-12)

Zasada: każdy fakt ma źródło. Czego nie udało się potwierdzić, jest oznaczone jako niepotwierdzone.

## 1. Konkurencja

**Narzędzia w chmurze (streszczanie filmów z YouTube).** Przegląd Scrimby z 2026 r. opisuje m.in. NoteGPT (Pro 9 USD/mies.
przy płatności rocznej, filmy bez napisów do 120 min), Eightify (9,99 USD/mies. albo 59,99 USD/rok), Nottę (darmowo
120 min transkrypcji miesięcznie, 3 min na rozmowę) i Fireflies (Pro 10 USD za osobę). Według tego przeglądu wszystkie
pracują na transkrypcji albo dźwięku; artykuł nie wymienia żadnego, który analizuje obraz filmu.
Źródło: https://scrimba.com/articles/best-ai-video-summarizers-2026/

**Narzędzie lokalne: OpenBrief** (open source, AGPL-3.0, Show HN 26 maja 2026). Recenzja opisuje je jako „polished GUI for
yt-dlp + Whisper with an LLM layer”: transkrypcja lokalnie (whisper.cpp), ale streszczenia i czat domyślnie przez model
w chmurze (OpenAI, Anthropic, Gemini, OpenRouter); lokalny model dopiero w planach. Instalacja tylko ze źródeł, bez
podpisanych instalatorów; opisany przebieg pracuje na samej transkrypcji (bez OCR i analizy kadrów).
Źródło: https://dev.to/andrew-ooo/openbrief-review-local-first-video-ai-summarizer-2026-1k3n

**vidsum.ai** — strony nie udało się pobrać (odmowa dostępu dla automatu), więc nie porównuję funkcji ani cen. Niepotwierdzone.

**Czym Vidsumly różni się na tle powyższych** (to cechy naszego programu, sprawdzalne w kodzie):
- streszczenie i czat liczy model lokalny (Ollama) — film, transkrypcja i pytania nie opuszczają komputera;
- oprócz mowy analizuje obraz: opisy kadrów i napisy z ekranu (OCR), także kadry wskazane mową („spójrz tutaj”);
- fakty i cytaty są dosłownymi zdaniami z nagrania, a każda informacja ma oznaczenie źródła [mowa] / [obraz];
- bez abonamentu i limitów minut.
Czego NIE wiem: jak wypada jakość naszych streszczeń względem narzędzi z dużymi modelami w chmurze — nie porównywałem.

## 2. Whisper (faster-whisper)

README faster-whisper podaje pomiar na **RTX 3070 Ti 8 GB** (ta sama karta co w komputerze testowym), 13 minut dźwięku,
model large-v2:

| Ustawienie | Czas | Pamięć karty |
|---|---|---|
| fp16, beam 5 | 1 min 03 s | 4525 MB |
| int8, beam 5 | 59 s | 2926 MB |
| fp16, batch_size=8 | 17 s | 6090 MB |
| int8, batch_size=8 | 16 s | 4500 MB |

Wnioski dla nas: (1) int8 bierze ok. 35% mniej pamięci karty przy podobnym czasie — to wspiera pomysł wczytania Whispera
int8 już w trakcie opisu kadrów; (2) przetwarzanie wsadowe (`BatchedInferencePipeline`) jest ok. 3,7× szybsze, ale
potrzebuje więcej pamięci. W 0.12.0 tego NIE włączam: pomiar dotyczy large-v2, a u nas działa large-v3-turbo i na karcie
siedzi wtedy model obrazu — decyzja po `--zmierz-czasy` na komputerze użytkownika.
Źródło: https://pypi.org/project/faster-whisper/ (wersja 1.2.1, 31.10.2025)

## 3. Ollama

- Domyślnie `OLLAMA_NUM_PARALLEL` = 1 (jedno zapytanie naraz), `OLLAMA_MAX_LOADED_MODELS` = 3 × liczba kart.
  Pamięć rośnie z liczbą równoległych zapytań (kontekst × liczba zapytań). Źródło: https://docs.ollama.com/faq
- Windows: instalacja w katalogu użytkownika, bez uprawnień administratora; jedyna opisana flaga instalatora to `/DIR`;
  Ollama dziedziczy zmienne środowiskowe użytkownika; API pod `http://localhost:11434`. Źródło: https://docs.ollama.com/windows
- Wykorzystane w 0.12.0: program sam uruchamia `ollama serve` z `OLLAMA_NUM_PARALLEL=2` i `OLLAMA_MAX_LOADED_MODELS=1`;
  instalatora nie uruchamiamy „po cichu”, bo dokumentacja takiej flagi nie opisuje.

## 4. Reklamy w filmach (SponsorBlock)

SponsorBlock ma publiczne API z kategoriami `sponsor`, `selfpromo`, `interaction`, `intro`, `outro` i wariant chroniący
prywatność (pierwsze znaki skrótu SHA-256 identyfikatora filmu zamiast samego identyfikatora).
Źródło: https://wiki.sponsor.ajay.app/w/API_Docs
W 0.12.0 NIE używam: to usługa sieciowa (program ma liczyć lokalnie), a licencji danych nie potwierdziłem.
Reklamy wykrywamy lokalnie: słowa reklamy, nazwa sponsora, wskazanie modelu.

## 5. Ostrzeżenie SmartScreen i podpis instalatora

Według Microsoft Learn (aktualizacja 2026-11-10):
- Azure Artifact Signing: ok. 9,99 USD/mies.; dla firm z USA, Kanady, UE i Wielkiej Brytanii, a dla osób prywatnych
  tylko z USA i Kanady;
- certyfikat OV: ok. 150–300 USD rocznie;
- certyfikat EV od 2024 r. nie daje już natychmiastowego zaufania SmartScreen — reputacja buduje się z czasem przy każdej metodzie;
- SignPath Foundation podpisuje za darmo kwalifikujące się projekty open source;
- Microsoft Store: Microsoft podpisuje paczkę bez dodatkowych kosztów.
Źródło: https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options
Wniosek: w 0.12.0 instalator pozostaje niepodpisany (decyzja o kosztach należy do właściciela produktu).

## 6. Co z badań weszło do 0.12.0, a co nie

| Temat | Decyzja |
|---|---|
| Uruchamianie Ollamy z 2 zapytaniami naraz | weszło (pierwsze uruchomienie bez PowerShella) |
| Schemat odpowiedzi modelu („structured outputs”) | weszło — po pomiarze na prawdziwym modelu (patrz RAPORT_0.12.0.md) |
| Whisper int8 / wsadowo | nie — czeka na pomiar `--zmierz-czasy` na komputerze użytkownika |
| SponsorBlock | nie — usługa sieciowa, licencja niepotwierdzona |
| Podpis instalatora | nie — koszt i wymagania formalne, decyzja właściciela |
