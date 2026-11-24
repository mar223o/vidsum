"""Sprawdzenie na prawdziwym Windows (CI), ffmpeg z instalatora (LGPL): tryb „Konwersja” — plik → MP3 i MP4,
VP9 → MP4 (koder H.264 dostępny w tej kompilacji albo zapis bez przekodowania). Uruchomienie Pythonem z instalacji:
<instalacja>\\python\\python.exe tests\\win_convert_check.py <instalacja> <film testowy>"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, sys.argv[1])
from vidsum import convert as cv  # noqa: E402

film = Path(sys.argv[2])
encs = cv.encoders()
print("ffmpeg:", cv.find_tool("ffmpeg"))
print("kodery H.264:", [e for e in cv.H264_ENCODERS if e in encs], "| MP3:", "libmp3lame" in encs,
      "| VP9:", "libvpx-vp9" in encs)
out = Path(tempfile.mkdtemp()) / "Konwersje ąę"
mp3 = cv.convert(str(film), "mp3", out, log=print)
st = cv.streams(mp3)
assert st["audio"] == "mp3" and st["video"] is None, st
mp4 = cv.convert(str(film), "mp4", out, log=print)
st = cv.streams(mp4)
assert st["video"] == "h264" and st["audio"] == "aac", st
if "libvpx-vp9" in encs:
    src = out / "klip.webm"
    subprocess.run([cv.find_tool("ffmpeg"), "-v", "error", "-y", "-i", str(film), "-t", "5", "-c:v", "libvpx-vp9",
                    "-b:v", "400k", "-deadline", "realtime", "-c:a", "libopus", str(src)], check=True)
    v = cv.convert(str(src), "mp4", out, log=print)
    st = cv.streams(v)
    print("VP9 → MP4:", st["video"], st["audio"])
    assert st["video"] in ("h264", "vp9") and st["audio"] == "aac", st
print("konwersja: ok")
