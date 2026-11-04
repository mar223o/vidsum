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
| Qwen3 8B / 4B (Alibaba) | alternatywny model tekstowy | Apache 2.0 (HuggingFace) | tak, także komercyjnie |
| Bielik 4.5B / Minitron 7B v3 (SpeakLeash) | kandydaci w pomiarze (polski model) | Apache 2.0 (HuggingFace) | tak |
| **Gemma 3 4B (Google)** | **domyślny model tekstowy od 0.7**: streszczenie, czat, tłumaczenia | Gemma Terms of Use | tak, także komercyjnie, z zasadami zakazanego użycia Google |
| Granite 3.3 8B (IBM) | kandydat w pomiarze | Apache 2.0 | tak |
| Llama 3.1 8B (Meta) | kandydat w pomiarze (odrzucony) | Llama 3.1 Community License | tak, z warunkami Meta |
| NVIDIA cuBLAS 12.8 + cuDNN 9.10 (pakiety PyPI `nvidia-cublas-cu12`, `nvidia-cudnn-cu12`) | Whisper na GPU (od 0.7) | NVIDIA Software License / cuDNN SLA | tak; program ich NIE rozprowadza — pobiera je na komputer użytkownika z oficjalnych pakietów NVIDIA |
| Claude Code | streszczenie przez subskrypcję Pro | warunki Anthropic | tak, w ramach planu |

\* Licencja yt-dlp pozwala na wszystko, ale regulaminy YouTube / Instagrama / TikToka generalnie zabraniają
pobierania. To decyzja użytkownika do prywatnego użytku — narzędzie nie omija zabezpieczeń (DRM) i nie
publikuje pobranych plików.

Sprawdzone: tagi licencji modeli przez API HuggingFace (`license:mit`, `license:apache-2.0`).
Niesprawdzone: dokładny wariant licencji ffmpeg w paczce na Windows (ustalimy przy fazie 2).
