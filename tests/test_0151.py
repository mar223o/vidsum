"""0.15.1: mini dźwięki (Web Audio, z wyłącznikiem), oszczędne animacje, żywe logo i żywa podpowiedź w polu."""
from __future__ import annotations

import json
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "vidsum" / "web" / "index.html"


def test_sound_setting_default_on_and_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    from vidsum.gui import App
    app = App(tmp_path / "wyniki", "tok")
    assert app.settings["dzwieki"] is True
    app.save_settings({"dzwieki": False})
    assert App(tmp_path / "wyniki", "tok").settings["dzwieki"] is False


def test_sounds_are_generated_not_files_and_motion_respects_reduced():
    html = HTML.read_text(encoding="utf-8")
    assert "AudioContext" in html and ".mp3\"" not in html.split("const SFX")[1][:3000]   # bez plików dźwiękowych
    css = html[:html.index("</style>")]
    tail = css[css.index("0.15.1: animacje"):]
    assert "prefers-reduced-motion:reduce" in tail and "#app.enter" in tail
    assert "prefers-reduced-motion:reduce){.alive .play" in css


@pytest.fixture()
def ui(tmp_path, monkeypatch):
    pytest.importorskip("playwright.sync_api")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")
    from vidsum.gui import App, Job, make_handler
    from vidsum.pipeline import Options
    app = App(tmp_path / "wyniki", "tok")
    run = Job("runn0001", "https://youtu.be/x", "https://youtu.be/x", Options(out_root=tmp_path), None)
    run.status, run.started = "trwa", time.time() - 30
    run.start_tracking()
    app.worker.jobs[run.id] = run
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield f"http://127.0.0.1:{srv.server_address[1]}", app, b, run
        b.close()
    srv.shutdown()


def test_ui_sounds_on_events_and_switch_off(ui):
    base, app, b, run = ui
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(base + "/?t=tok#/")
    pg.wait_for_selector("#queue .qi.now")
    pg.click("#kind [data-kind=mp4]")                                   # kliknięcie przełącznika → „tap”
    pg.click("#kind [data-kind=analiza]")
    assert pg.evaluate("window.__sfx").count("tap") == 2
    run.status = "blad"                                                  # zmiana stanu zadania → dźwięk błędu
    pg.evaluate("poll()")
    pg.wait_for_function("(window.__sfx || []).includes('error')")
    run.status = "gotowe"
    pg.evaluate("poll()")
    pg.wait_for_function("(window.__sfx || []).includes('done')")
    # wyłącznik w Ustawieniach → Interfejs
    pg.click('nav a[data-nav="set"]')
    pg.select_option("#s_dzwieki", "false")
    pg.wait_for_timeout(300)
    assert app.settings["dzwieki"] is False
    pg.evaluate("window.__sfx = []")
    pg.click('.setnav [data-sec="an"]')
    assert pg.evaluate("window.__sfx") == []
    assert not errors, errors


def test_ui_alive_logo_and_typing_hint(ui):
    base, app, b, run = ui
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    pg.goto(base + "/?t=tok#/")
    pg.wait_for_selector("#alive")
    assert "busy" in pg.get_attribute("#alive", "class")                # coś się analizuje → szybciej
    assert pg.evaluate("getComputedStyle(document.querySelector('#alive .play')).animationName") == "aPlay"
    seen = set()
    for _ in range(12):                                                  # podpowiedź wypisuje się na żywo
        seen.add(pg.get_attribute("#links", "placeholder"))
        pg.wait_for_timeout(120)
    assert len(seen) >= 5 and any(x.endswith("▍") for x in seen)
    assert pg.get_attribute("#links", "aria-label") == "Wklej link albo przeciągnij plik"
    pg.fill("#links", "https://youtu.be/abc")                            # coś wpisane → podpowiedź stoi
    pg.wait_for_timeout(900)
    a = pg.get_attribute("#links", "placeholder"); pg.wait_for_timeout(400)
    assert pg.get_attribute("#links", "placeholder") == a
    # ograniczony ruch: bez animacji logo i bez wypisywania
    rm = b.new_page(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    rm.goto(base + "/?t=tok#/")
    rm.wait_for_selector("#alive")
    assert rm.evaluate("getComputedStyle(document.querySelector('#alive .play')).animationName") == "none"
    assert rm.get_attribute("#links", "placeholder") == "Wklej link z YouTube…"


def test_ui_options_popover_animates_and_done_moves_to_recent(ui):
    base, app, b, run = ui
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    pg.goto(base + "/?t=tok#/")
    pg.wait_for_selector("#queue .qi.now")
    pg.click("#optbtn")
    assert pg.evaluate("getComputedStyle(document.querySelector('#optpop')).animationName") == "vsPop"
    pg.wait_for_timeout(1600)                                            # po starcie nowe wiersze dostają animację
    run.status = "gotowe"
    pg.evaluate("poll()")
    pg.wait_for_timeout(300)
    assert pg.locator("#ostatnie").count() == 1
