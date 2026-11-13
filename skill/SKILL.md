---
name: analiza-filmu
description: Analizuje film (MP4/MOV lub link) wrzucony do czatu — mowa, napisy na ekranie i obraz — i zwraca konkretne streszczenie w stylu Vidsumly: przepis, trening albo kroki z czasem, rozdziały, cytaty, szczera ocena, ze źródłem przy każdej informacji.
---

# Analiza filmu (procedura Vidsumly)

Użyj, gdy użytkownik wrzuca film albo prosi o streszczenie / przepis / ćwiczenia z filmu.
Odpowiadaj po polsku. **Niczego nie zmyślaj**: czego nie widać ani nie słychać → „brak danych”.
Przy każdej informacji źródło: [mowa], [obraz], [mowa+obraz] albo [szacunek].

## 0. Najpierw sprawdź, czy jest program Vidsumly
Jeśli pracujesz na komputerze użytkownika (Claude Code / Claude Desktop z dostępem do plików) i istnieje
`Vidsumly.exe` albo `Vidsumly.cmd` — uruchom go: `Vidsumly.cmd "ŚCIEŻKA" --streszczenie brak`, potem przeczytaj
`analiza.json` (oś czasu, transkrypcja, napisy OCR, kadry) z folderu wyników i przejdź do kroku 4.
To najdokładniejsza droga (Whisper large-v3-turbo + OCR + podpowiedzi słów, zmierzony WER: EN ≈1–3%, PL ≈0–1,4%).

## 1. Kadry (zawsze)
Zapisz skrypt `klatki.py` (niżej) i uruchom: `python klatki.py FILM kadry --max 36`.
Wymaga tylko ffmpeg. Tworzy arkusze 3×3 z czasem `mm:ss` na każdym kadrze oraz `audio.wav`.
Dla filmów > 10 min użyj `--max 60`.

## 2. Mowa
`pip install faster-whisper` (jeśli nie ma), zapisz `mowa.py` i uruchom:
`python mowa.py kadry/audio.wav mowa.json [--jezyk pl|en]`.
- Gdy na kadrach są wypalone napisy, podaj je jako `--podpowiedz "tytuł + napisy"` — tylko dla modelu turbo
  (skrypt sam pomija podpowiedź dla small; pomiary: małym modelom podpowiedź szkodzi).
- Jeśli instalacja/pobranie modelu nie działa (brak sieci): nie zgaduj mowy. Napisz, że mowa = „brak danych”,
  i zaproponuj, by użytkownik wkleił transkrypcję albo napisy. Napisy wypalone w obrazie nadal odczytasz z kadrów.

## 3. Obejrzyj kadry
Otwórz KAŻDY arkusz (`kadry/arkusz_*.jpg`) i dla każdego kadru zanotuj: czas, co widać, czynności rąk,
składniki/sprzęt, ustawienie ciała (ćwiczenia), **dokładny tekst z ekranu** (napisy, ilości, temperatury).
Napisy z ekranu są zwykle pewniejsze w nazwach i liczbach niż transkrypcja — gdy się różnią, zaufaj napisom.

## 4. Wynik
Rozpoznaj typ: przepis | trening | poradnik | wykład | inne. Odpowiedz w tym układzie:

**Tytuł** — *puenta*
> jednozdaniowa teza

**W skrócie** — 2–3 akapity.

**Co masz zrobić** (dopasuj do typu):
- przepis: Składniki (ilość albo „brak danych”), Kroki z `mm:ss`, Sprzęt, Czas;
- trening: Ćwiczenia (nazwa — serie × powtórzenia — `mm:ss`), Technika, Błędy, których unikać;
- poradnik: kroki z `mm:ss`; inne: 3–7 wniosków.

**Najważniejsze** (3–5, z `mm:ss`) · **Rozdziały** (`mm:ss–mm:ss` tytuł — opis) · **Cytaty** (dosłownie z mowy,
z tłumaczeniem, gdy obcojęzyczne) · **Szczera ocena** [szacunek] · **Czego nie wiadomo**.

Jeśli użytkownik chce dane do dashboardu — dodaj blok JSON w schemacie `vidsum.summary/1`
(pola: typ, tytul, tytul_akcent, teza, streszczenie[], co_masz_zrobic{skladniki[{nazwa,ilosc,zrodlo}],
kroki[{t,tekst,zrodlo}], sprzet[], czas, cwiczenia[{nazwa,serie,powtorzenia,t,technika,zrodlo}], wskazowki[],
bledy[], wnioski[]}, najwazniejsze[{t,tytul,opis,zrodlo}], momenty[{t,tekst}], cytaty[{t,tekst,tlumaczenie}],
rozdzialy[{start,end,tytul,opis,momenty[]}], szczera_ocena, czego_nie_wiadomo[], pytania[]}; czasy w sekundach).

## Ograniczenia — powiedz o nich
- Kadry są próbkami: krótkie czynności między nimi mogą umknąć — podaj największy odstęp między kadrami.
- Linki (YouTube/Instagram/TikTok): w czacie zwykle nie da się ich pobrać — poproś o plik.

## Skrypt `klatki.py`
```python
#!/usr/bin/env python3
"""Kadry do obejrzenia przez Claude: zmiany scen + równomierne pokrycie, złożone w arkusze 3×3 z czasem na każdym kadrze.

Użycie: python klatki.py FILM.mp4 FOLDER_WYJŚCIOWY [--max 36]
Wynik: FOLDER/arkusz_01.jpg … (po 9 kadrów, czas mm:ss w rogu), FOLDER/kadry.json, FOLDER/audio.wav
Wymaga tylko ffmpeg/ffprobe.
"""
import json
import re
import subprocess
import sys
from pathlib import Path


def sh(*a, text=True):
    return subprocess.run(a, check=True, capture_output=True, text=text)


def duration(video):
    out = sh("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video).stdout
    return float(out.strip() or 0)


def scene_times(video, thr=0.22):
    err = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-i", video, "-an", "-vf",
                          f"fps=2,scale=320:-2,select='gt(scene,{thr})',showinfo", "-f", "null", "-"],
                         capture_output=True, text=True, errors="replace").stderr
    return [float(x) for x in re.findall(r"pts_time:([0-9.]+)", err)]


def main(video, out, max_frames=36):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    dur = duration(video)
    base = max(1.5, dur / max(1, max_frames * 0.6))
    cand = {round(min(dur - 0.1, t + 0.5), 1) for t in scene_times(video)}         # chwilę po cięciu
    t = 0.3
    while t < dur - 0.3:
        cand.add(round(t, 1))
        t += base
    times = []
    for x in sorted(cand):                                                       # min. 1 s odstępu
        if not times or x - times[-1] >= 1.0:
            times.append(x)
    if len(times) > max_frames:                                                  # równomierne przerzedzenie
        step = len(times) / max_frames
        times = [times[int(i * step)] for i in range(max_frames)]
    frames = []
    for i, x in enumerate(times):
        f = out / f"k_{i:03d}.jpg"
        mm = f"{int(x // 60):02d}\\:{int(x % 60):02d}"
        sh("ffmpeg", "-y", "-v", "error", "-ss", f"{x:.2f}", "-i", video, "-frames:v", "1", "-vf",
           f"scale=480:-2,drawtext=text='{mm}':x=8:y=8:fontsize=26:fontcolor=white:box=1:boxcolor=black@0.7:boxborderw=6",
           str(f))
        frames.append({"t": x, "plik": f.name})
    sheets = []
    for s in range(0, len(frames), 9):
        chunk = frames[s:s + 9]
        sheet = out / f"arkusz_{s // 9 + 1:02d}.jpg"
        inputs = [a for c in chunk for a in ("-i", str(out / c["plik"]))]
        n = len(chunk)
        h = int(sh("ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=height",
                   "-of", "csv=p=0", str(out / chunk[0]["plik"])).stdout.strip() or 270)
        if n == 1:
            sh("ffmpeg", "-y", "-v", "error", "-i", str(out / chunk[0]["plik"]), str(sheet))
        else:
            # kadry w siatce 3 kolumny (xstack); wszystkie przeskalowane do 480×h
            scale = "".join(f"[{i}]scale=480:{h}[s{i}];" for i in range(n))
            layout = "|".join(f"{(i % 3) * 480}_{(i // 3) * h}" for i in range(n))
            sh("ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex",
               scale + "".join(f"[s{i}]" for i in range(n)) + f"xstack=inputs={n}:layout={layout}:fill=black",
               "-q:v", "3", str(sheet))
        sheets.append({"arkusz": sheet.name, "od": chunk[0]["t"], "do": chunk[-1]["t"]})
    has_audio = "audio" in sh("ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", video).stdout
    if has_audio:
        sh("ffmpeg", "-y", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", "16000", str(out / "audio.wav"))
    (out / "kadry.json").write_text(json.dumps({"dlugosc_s": round(dur, 2), "audio": has_audio, "kadry": frames,
                                                "arkusze": sheets}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"dlugosc_s": round(dur, 2), "audio": has_audio, "kadrow": len(frames), "arkusze": [s["arkusz"] for s in sheets]}))


if __name__ == "__main__":
    a = sys.argv[1:]
    mx = int(a[a.index("--max") + 1]) if "--max" in a else 36
    main(a[0], a[1], mx)
```

## Skrypt `mowa.py`
```python
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
```
