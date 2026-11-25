"""0.13.1: wyrazista ikona + przypięta ikona nie zmienia się w logo Pythona (część niezależna od Windows)."""
import re
from pathlib import Path

from PIL import IcoImagePlugin, Image

from vidsum import winicon

ROOT = Path(__file__).resolve().parent.parent


def test_ico_has_all_sizes_and_small_variant():
    ico = IcoImagePlugin.IcoFile(open(ROOT / "vidsum/web/vidsum.ico", "rb"))
    sizes = {s[0] for s in ico.sizes()}
    assert {16, 20, 24, 32, 40, 48, 64, 96, 128, 256} <= sizes
    big = ico.getimage((256, 256)).convert("RGBA")
    # 0.15.0 „Kontur”: czarne tło, cienki kremowy kontur kadru, perforacja w środku, kremowy „play”, lawendowa gwiazdka
    assert big.getpixel((80, 130)) == (0xF5, 0xEF, 0xE6, 255)      # play
    assert big.getpixel((33, 130)) == (0xF5, 0xEF, 0xE6, 255)      # kontur kadru: 9 px (29,5–38,5)…
    assert big.getpixel((46, 130)) == (0, 0, 0, 255)                # …w środku czarno (kontur, nie pełna ramka)
    assert big.getpixel((56, 72)) == (0xF5, 0xEF, 0xE6, 255)       # perforacja wewnątrz kadru
    assert big.getpixel((20, 230)) == (0, 0, 0, 255)                # tło
    assert big.getpixel((204, 56)) == (0xC4, 0xB5, 0xFD, 255)       # gwiazdka #C4B5FD
    assert big.getpixel((100, 56)) == (0xF5, 0xEF, 0xE6, 255)       # górny kontur
    assert big.getpixel((226, 106)) == (0, 0, 0, 255)               # 0.15.0: jedna gwiazdka (druga, mała, zniknęła)
    # 16 px: wersja uproszczona (bez perforacji i linii) — inna niż zmniejszona duża
    small = ico.getimage((16, 16)).convert("RGBA")
    scaled = big.resize((16, 16), Image.LANCZOS)
    assert small.tobytes() != scaled.tobytes()


def test_svg_matches_ico_palette():
    svg = (ROOT / "vidsum/web/icon.svg").read_text(encoding="utf-8")
    for c in ("#C4B5FD", "#F5EFE6"):
        assert c in svg
    assert "#38BDF8" not in svg                                     # 0.13.3: play już nie błękitny
    assert 'fill="none" stroke="#F5EFE6"' in svg                   # 0.15.0: kadr jako kontur
    znak = (ROOT / "vidsum/web/znak.svg").read_text(encoding="utf-8")   # znak wodny tła = ten sam kształt
    assert 'fill="none" stroke="#F5EFE6"' in znak and "#C4B5FD" not in znak


def test_stable_icon_copies_and_refreshes(tmp_path):
    d = tmp_path / "app"
    p = winicon.stable_icon([d])
    assert p == d / "Vidsumly.ico" and p.read_bytes() == winicon.package_icon().read_bytes()
    p.write_bytes(b"stara ikona")                       # nowa wersja ikony w pakiecie → kopia odświeżona
    assert winicon.stable_icon([d]).read_bytes() == winicon.package_icon().read_bytes()


def test_stable_icon_falls_back_when_not_writable(tmp_path):
    blocker = tmp_path / "plik"
    blocker.write_text("x")                              # „folder”, który jest plikiem → nie da się zapisać
    second = tmp_path / "dane"
    assert winicon.stable_icon([blocker / "pod", second]) == second / "Vidsumly.ico"
    assert winicon.stable_icon([blocker / "pod"]) == winicon.package_icon()


def test_is_vidsum_link(tmp_path):
    app = tmp_path / "Vidsumly"
    (app / "vidsum").mkdir(parents=True)
    (app / "vidsum" / "__init__.py").write_text("")
    (app / "python").mkdir()
    pyw = app / "python" / "pythonw.exe"
    assert winicon.is_vidsum_link(str(pyw), "-m vidsum --ui")
    assert winicon.is_vidsum_link(str(pyw), "")          # przypięte okno sprzed 0.13.1: sam pythonw.exe
    assert not winicon.is_vidsum_link(str(tmp_path / "Python312" / "pythonw.exe"), "")
    assert not winicon.is_vidsum_link(str(tmp_path / "notatnik.exe"), "")


def test_relaunch_command_quotes_path(tmp_path):
    exe = tmp_path / "Programy z spacją" / "python" / "pythonw.exe"
    assert winicon.relaunch_command(exe) == f'"{exe}" -m vidsum --ui'


def test_installer_uses_stable_icon_and_app_id():
    iss = (ROOT / "packaging/vidsum.iss").read_text(encoding="utf-8-sig")
    icons = [ln for ln in iss.splitlines() if ln.startswith('Name: "{') and "pythonw.exe" in ln]
    assert len(icons) == 2
    for ln in icons:
        assert 'IconFilename: "{app}\\Vidsumly.ico"' in ln
        assert f'AppUserModelID: "{winicon.APP_ID}"' in ln
    assert 'DestName: "Vidsumly.ico"' in iss and "UninstallDisplayIcon={app}\\Vidsumly.ico" in iss


def test_gui_uses_same_app_id():
    gui = (ROOT / "vidsum/gui.py").read_text(encoding="utf-8")
    assert "SetCurrentProcessExplicitAppUserModelID(APP_ID)" in gui
    assert "winicon.set_window_props(hwnd, ico_path)" in gui
    assert re.search(r'Vidsumly\.Aplikacja', (ROOT / "vidsum/winicon.py").read_text(encoding="utf-8"))


def test_ci_runs_windows_check():
    wf = (ROOT / ".github/workflows/windows.yml").read_text(encoding="utf-8")
    assert "tests\\win_icon_check.py" in wf and "*Vidsumly.ico*" in wf


def test_fix_shortcut_icons_noop_off_windows(monkeypatch):
    from vidsum import gui
    monkeypatch.setattr(gui.os, "name", "posix")
    assert gui.fix_shortcut_icons() is None
