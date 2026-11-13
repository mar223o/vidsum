"""Sprawdzenie na prawdziwym Windows (CI): właściwości okna do przypinania i naprawa skrótów .lnk.
Uruchomienie: python tests/win_icon_check.py <folder instalacji>"""
import ctypes
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # konsola CI: cp1252
app = Path(sys.argv[1])
sys.path.insert(0, str(app))
from vidsum import winicon  # noqa: E402

ico = winicon.stable_icon([app])
assert ico == app / "Vidsumly.ico" and ico.read_bytes() == winicon.package_icon().read_bytes(), ico
print("stała ikona:", ico)

# 1) okno: ID + relaunch (bez nich przypięcie bierze ikonę pythonw.exe)
u = ctypes.windll.user32
u.CreateWindowExW.restype = ctypes.c_void_p
hwnd = u.CreateWindowExW(0, "STATIC", "Vidsumly test", 0, 0, 0, 100, 100, None, None, None, None)
assert hwnd, "CreateWindowExW"
cmd = winicon.relaunch_command(app / "python" / "pythonw.exe")
winicon.set_window_props(hwnd, ico, cmd)
got = winicon.get_window_props(hwnd)
print("okno:", got)
assert got[winicon.PID_ID] == winicon.APP_ID
assert got[winicon.PID_RELAUNCH_ICON] == f"{ico},0"
assert got[winicon.PID_RELAUNCH_COMMAND] == cmd
assert got[winicon.PID_RELAUNCH_NAME] == "Vidsumly"

# 2) skróty: stary skrót (ikona z pakietu, bez ID) i przypięcie samego pythonw.exe (jak przed 0.13.1)
tmp = Path(tempfile.mkdtemp())
pyw = app / "python" / "pythonw.exe"


def make(name, args, icon, target=pyw):
    """Skrót tworzony przez COM z Pythona (PowerShell -Command psuje ścieżki z „ąę” na konsoli cp1252)."""
    c = winicon._com()
    ct, method = c.ctypes, c.method
    c.init()
    lnk = tmp / name
    sl = ct.c_void_p()
    c.ole32.CoCreateInstance(ct.byref(c.guid(winicon.CLSID_ShellLink)), None, 1,
                             ct.byref(c.guid(winicon.IID_IShellLinkW)), ct.byref(sl))
    method(sl, 20, ct.c_wchar_p)(str(target))                                   # SetPath
    method(sl, 11, ct.c_wchar_p)(args)                                          # SetArguments
    path, _, idx = icon.rpartition(",")
    method(sl, 17, ct.c_wchar_p, ct.c_int)(path, int(idx))                      # SetIconLocation
    pf = winicon._qi(sl, winicon.IID_IPersistFile)
    method(pf, 6, ct.c_wchar_p, ct.c_int)(str(lnk), 1)                          # Save
    c.release(pf)
    c.release(sl)
    return lnk


old = make("stary.lnk", "-m vidsum --ui", f"{app}\\vidsum\\web\\vidsum.ico,0")
bare = make("przypiety.lnk", "", f"{pyw},0")
print("przed:", winicon.read_link(old))
assert winicon.fix_link(old, ico)
assert winicon.fix_link(bare, ico)
for f in (old, bare):
    r = winicon.read_link(f)
    print("po:", f.name, r)
    assert r["id"] == winicon.APP_ID, r
    assert r["ikona"].lower() == str(ico).lower() and r["indeks"] == 0, r
    assert "-m vidsum --ui" in r["argumenty"], r
    assert r["cel"].lower() == str(pyw).lower(), r
# skrót do Pythona spoza instalacji Vidsumly (inny program) — nie ruszamy (skrypt uruchamiany Pythonem z runnera)
other_py = Path(sys.executable)
o = make("obcy.lnk", "-c pass", f"{other_py},0", target=other_py)
assert not winicon.fix_link(o, ico)
print("ikony i skróty: ok")
