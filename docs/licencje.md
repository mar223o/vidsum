# Licencje użytych komponentów (stan: 2026-11-01)

| komponent | do czego | licencja | prywatne użycie |
|---|---|---|---|
| faster-whisper 1.2.1 | transkrypcja | MIT | tak |
| CTranslate2 4.8.4 | silnik Whispera | MIT | tak |
| Whisper small/medium (Systran/faster-whisper-*) | model mowy | MIT (tag na HuggingFace) | tak |
| yt-dlp 2026.10.26 | pobieranie z linków | Unlicense (domena publiczna) | tak* |
| ffmpeg / ffprobe | audio, kadry | LGPL/GPL (zależnie od kompilacji) | tak |
| RapidOCR 1.2.3 (detekcja tekstu) | napisy na ekranie | Apache-2.0 | tak |
| PP-OCRv5 latin (monkt/paddleocr-onnx) | rozpoznawanie napisów, polskie znaki | Apache-2.0 | tak |
| OpenCV (zależność RapidOCR) | obróbka obrazu | Apache-2.0 | tak |
| Whisper large-v3-turbo | mowa (domyślny od 0.4) | MIT | tak |
| Ollama | uruchamianie modelu wizyjnego | MIT | tak |
| Qwen3-VL 4B / 8B Instruct | opis kadrów | Apache 2.0 (tag na HuggingFace) | tak |
| Claude Code | streszczenie przez subskrypcję Pro | warunki Anthropic | tak, w ramach planu |

\* Licencja yt-dlp pozwala na wszystko, ale regulaminy YouTube / Instagrama / TikToka generalnie zabraniają
pobierania. To decyzja użytkownika do prywatnego użytku — narzędzie nie omija zabezpieczeń (DRM) i nie
publikuje pobranych plików.

Sprawdzone: tagi licencji modeli przez API HuggingFace (`license:mit`, `license:apache-2.0`).
Niesprawdzone: dokładny wariant licencji ffmpeg w paczce na Windows (ustalimy przy fazie 2).
