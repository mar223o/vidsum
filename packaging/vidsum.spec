# PyInstaller: jeden folder z Vidsumly.exe (onedir — szybki start, łatwe podmienienie ffmpeg).
# Budowanie:  pyinstaller packaging/vidsum.spec --noconfirm
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hidden = [("../vidsum/web", "vidsum/web"), ("../vidsum/wzorce", "vidsum/wzorce")], [], []
for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "tokenizers", "rapidocr_onnxruntime"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hidden += h
hidden += collect_submodules("yt_dlp")   # ekstraktory ładowane dynamicznie

a = Analysis(["vidsum_entry.py"], pathex=[".."], binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=["tkinter", "matplotlib", "IPython", "pytest", "torch", "scipy", "pandas", "sympy"], noarchive=False)
pyz = PYZ(a.pure)
import sys
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Vidsumly", console=True,
          icon=None, upx=False,   # bez UPX — kompresja .exe to częsty powód fałszywych alarmów
          version="version_info.txt" if sys.platform == "win32" else None)
# drugi plik startowy BEZ okna konsoli (to klika użytkownik); Vidsumly.exe zostaje dla wiersza poleceń i MCP
exe_start = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Vidsumly Start", console=False,
                icon=None, upx=False, version="version_info.txt" if sys.platform == "win32" else None)
coll = COLLECT(exe, exe_start, a.binaries, a.datas, name="Vidsumly", upx=False)
