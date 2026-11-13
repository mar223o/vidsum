#!/usr/bin/env python3
"""Transkrypcja z czasami (faster-whisper). Próbuje large-v3-turbo, a gdy się nie da (pamięć/sieć) — small.

Użycie: python mowa.py audio.wav WYNIK.json [--jezyk pl|en] [--podpowiedz "tytuł i napisy z ekranu"]
Wymaga: pip install faster-whisper (pobiera model z HuggingFace przy pierwszym użyciu).
Uwaga z pomiarów Vidsumly: podpowiedź pomaga TYLKO dużym modelom (turbo); małym szkodzi — nie podawaj jej dla small.
"""
import json
import sys


def load_wav(path):
    """WAV 16 kHz mono (z klatki.py) → float32, bez PyAV (nowe PyAV jest niezgodne z faster-whisper 1.2.1)."""
    import wave
    import numpy as np
    with wave.open(path, "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def main(wav, out, lang=None, hint=None):
    from faster_whisper import WhisperModel
    audio = load_wav(wav)
    last = None
    for name in ("large-v3-turbo", "small"):
        try:
            m = WhisperModel(name, device="cpu", compute_type="int8")
            segs, info = m.transcribe(audio, language=lang, vad_filter=True, word_timestamps=True, beam_size=5,
                                      condition_on_previous_text=False,
                                      hotwords=hint if (hint and name != "small") else None)
            res = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segs if s.text.strip()]
            json.dump({"model": name, "jezyk": info.language, "segmenty": res}, open(out, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
            print(json.dumps({"model": name, "jezyk": info.language, "segmentow": len(res)}))
            return
        except Exception as e:     # brak pamięci / brak sieci do pobrania modelu → mniejszy model
            last = e
    raise SystemExit(f"Transkrypcja nie powiodła się: {last}")


if __name__ == "__main__":
    a = sys.argv[1:]
    lang = a[a.index("--jezyk") + 1] if "--jezyk" in a else None
    hint = a[a.index("--podpowiedz") + 1] if "--podpowiedz" in a else None
    main(a[0], a[1], lang, hint)
