# PyInstaller: jeden folder z VidSum.exe (onedir — szybki start, łatwe podmienienie ffmpeg).
# Budowanie:  pyinstaller packaging/vidsum.spec --noconfirm
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hidden = [("../vidsum/web", "vidsum/web")], [], []
for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "tokenizers"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hidden += h
hidden += collect_submodules("yt_dlp")   # ekstraktory ładowane dynamicznie

a = Analysis(["vidsum_entry.py"], pathex=[".."], binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "matplotlib", "IPython", "pytest", "torch", "scipy", "pandas", "PIL", "sympy"], noarchive=False)
pyz = PYZ(a.pure)
import sys
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VidSum", console=True,
          icon=None, upx=False,   # bez UPX — kompresja .exe to częsty powód fałszywych alarmów
          version="version_info.txt" if sys.platform == "win32" else None)
coll = COLLECT(exe, a.binaries, a.datas, name="VidSum", upx=False)
