"""Buduje filmy testowe ze ZNANYM tekstem mowy (synteza Piper) i wypalonymi napisami, jak na Shorts.

Użycie: python make_bench.py <folder_wyjściowy> <głos_en.onnx> <głos_pl.onnx>
Tworzy: bench_en.mp4, bench_pl.mp4 + *.truth.json (zdania z czasami = prawda do pomiaru WER).
Piper (GPL) służy tylko do wygenerowania danych testowych — nie jest częścią programu.
"""
import json
import subprocess
import sys
import wave
from pathlib import Path

SCRIPTS = {
    "en": [
        "This is the perfect French fry, the secret to super crispy fries.",
        "Start with Maris Piper potatoes, which have a high starch content.",
        "Peel them and cut them lengthways into uniform fries, roughly one centimetre square.",
        "Soak them in cold water and wash them until the water runs perfectly clear.",
        "Bring a pot of water to the boil and add baking soda and salt.",
        "Boil the fries until just tender, then dust them lightly with potato starch.",
        "Heat the oil and duck fat to one hundred and forty degrees and blanch the fries.",
        "For the final fry, heat the oil to one hundred and ninety degrees.",
        "Finish with a sprinkle of Maldon sea salt for extra crunch.",
    ],
    "pl": [
        "Dziś przygotujemy szakszukę z wędzoną papryką i świeżą kolendrą.",
        "Na patelni rozgrzej dwie łyżki oliwy i zeszklij pokrojoną cebulę.",
        "Dodaj dwa ząbki czosnku, łyżeczkę kminu rzymskiego i szczyptę chili.",
        "Wlej czterysta gramów pomidorów z puszki i duś przez dziesięć minut.",
        "Zrób w sosie cztery dołki i wbij do każdego po jednym jajku.",
        "Przykryj pokrywką i gotuj na małym ogniu, aż białka się zetną.",
        "Na koniec posyp fetą, kolendrą i podawaj z chrupiącym pieczywem.",
    ],
}
COLORS = ["0x2d4a22", "0x1f3a5f", "0x5f1f2d", "0x3d3d3d", "0x4a3b22", "0x22404a", "0x402a4a", "0x2a4a40", "0x4a2222"]
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def sh(*a):
    subprocess.run(a, check=True, capture_output=True)


def main(out: Path, voice_en: str, voice_pl: str):
    out.mkdir(parents=True, exist_ok=True)
    for lang, voice in (("en", voice_en), ("pl", voice_pl)):
        tmp = out / f"_{lang}"
        tmp.mkdir(exist_ok=True)
        t, truth, parts = 0.6, [], []
        for i, text in enumerate(SCRIPTS[lang]):
            wav = tmp / f"s{i}.wav"
            subprocess.run([sys.executable, "-m", "piper", "-m", voice, "-f", str(wav)], input=text.encode(),
                           check=True, capture_output=True)
            with wave.open(str(wav)) as w:
                dur = w.getnframes() / w.getframerate()
            truth.append({"start": round(t, 2), "end": round(t + dur, 2), "text": text})
            # klip: kolorowe tło + napis (wypalony, dół ekranu, jak na Shorts) na czas zdania + 0,6 s przerwy
            clip = tmp / f"v{i}.mp4"
            seg = dur + 0.6 if i else dur + 1.2
            off = 0.6 if i == 0 else 0.0
            # napisy po 3 słowa, równo rozłożone na czas zdania (jak automatyczne napisy na Shorts)
            words = text.split()
            chunks = [" ".join(words[k:k + 3]) for k in range(0, len(words), 3)]
            draws = []
            for j, ch in enumerate(chunks):
                f = tmp / f"c{i}_{j}.txt"
                f.write_text(ch, encoding="utf-8")
                a0, a1 = off + dur * j / len(chunks), off + dur * (j + 1) / len(chunks)
                draws.append(f"drawtext=fontfile={FONT}:textfile={f}:fontsize=46:fontcolor=white:box=1:"
                             f"boxcolor=black@0.55:boxborderw=14:x=(w-tw)/2:y=h*0.70:enable='between(t,{a0:.2f},{a1:.2f})'")
            sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={COLORS[i % len(COLORS)]}:s=720x1280:r=25:d={seg}",
               "-i", str(wav), "-filter_complex",
               f"[0]{','.join(draws)}[v];"
               f"[1]adelay={600 if i == 0 else 0}|{600 if i == 0 else 0},apad[a]",
               "-map", "[v]", "-map", "[a]", "-t", f"{seg}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-ar", "44100", str(clip))
            parts.append(clip)
            t += seg if i else seg - 0.6
            if i == 0:
                t = seg
        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        mixed = out / f"bench_{lang}.mp4"
        # lekki szum tła (jak muzyka/kuchnia), żeby nie było „studyjnie”
        sh("ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
           "-filter_complex", "anoisesrc=color=pink:amplitude=0.02:r=44100[n];[0:a][n]amix=inputs=2:duration=first:normalize=0[a]",
           "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", str(mixed))
        (out / f"bench_{lang}.truth.json").write_text(json.dumps({"language": lang, "segments": truth}, ensure_ascii=False, indent=1),
                                                     encoding="utf-8")
        print(mixed, round(t, 1), "s")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
