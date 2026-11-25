"""0.15.0 „Komenda”: nowy wygląd strony głównej, paleta krem + błękit (ciemne tło „łupek”), logo „Kontur”."""
from __future__ import annotations

import json
import re
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "vidsum" / "web" / "index.html"


def _lum(h: str) -> float:
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _vars(block: str) -> dict:
    return dict(re.findall(r"--([\w-]+):(#[0-9A-Fa-f]{6})", block))


def test_text_contrast_at_least_4_5_in_both_themes():
    html = HTML.read_text(encoding="utf-8")
    dark = _vars(html[html.index(":root{"):html.index(":root,:root[data-theme]{")])
    light = _vars(html[html.index(':root[data-theme="light"]{'):html.index("@media (prefers-color-scheme: light)")])
    for v in (dark, light):
        for fg in ("ink", "ink2", "muted", "faint", "accent"):
            for bg in ("bg", "panel", "card", "raised"):
                assert _contrast(v[fg], v[bg]) >= 4.5, (fg, bg, v[fg], v[bg], round(_contrast(v[fg], v[bg]), 2))
    assert dark["bg"].lower() == "#0f1316" and dark["accent"] == "#38BDF8" and dark["ink"] == "#F5EFE6"


def test_one_accent_no_decorative_gradients():
    html = HTML.read_text(encoding="utf-8")
    css = html[:html.index("</style>")]
    assert "#C4B5FD" not in css                                      # lawenda tylko w logo
    assert "linear-gradient(110deg" not in css and "var(--amb1)" not in css
    assert "/znak.svg" in css and "radial-gradient(rgba(56,189,248" in css   # kropki + znak wodny (ciemny motyw)


def test_job_dict_has_video_title_while_running(tmp_path, monkeypatch):
    from vidsum.gui import Job
    from vidsum.pipeline import Options
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    j = Job("abcd0002", "https://youtu.be/x", "https://youtu.be/x", Options(out_root=tmp_path), None)
    assert j.to_dict()["tytul_filmu"] is None
    j.partial["meta"] = {"tytul": "Martwy ciąg — technika"}
    assert j.to_dict()["tytul_filmu"] == "Martwy ciąg — technika"


@pytest.fixture()
def ui(tmp_path, monkeypatch):
    pytest.importorskip("playwright.sync_api")
    from vidsum import trash
    monkeypatch.setattr(trash, "_has_recycle_bin", lambda p: False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")
    from vidsum.gui import App, Job, make_handler
    from vidsum.pipeline import Options
    res = tmp_path / "wyniki"
    for i, (tytul, typ, kiedy) in enumerate([("Idealne frytki", "przepis", "2026-11-20T10:00:00+01:00"),
                                              ("Push day", "trening", "2026-11-22T10:00:00+01:00")]):
        d = res / f"film_{i}"
        d.mkdir(parents=True)
        (d / "analiza.json").write_text(json.dumps({
            "zrodlo": {"tytul": tytul, "dlugosc_s": 238}, "utworzono": kiedy, "czasy": {"razem_s": 10},
            "streszczenie": {"dane": {"tytul": tytul, "typ": typ, "teza": "Teza " + tytul}}}), encoding="utf-8")
    app = App(res, "tok")
    run = Job("runn0001", "https://youtu.be/x", "https://youtu.be/x", Options(out_root=tmp_path), None)
    run.status, run.started = "trwa", time.time() - 30
    run.start_tracking()
    run.feed("  [1/4] transkrypcja (Whisper)…")
    run.partial["meta"] = {"tytul": "Martwy ciąg — technika", "dlugosc_s": 420.0}
    app.worker.jobs[run.id] = run
    orig = app.status
    state = {"ollama": True}
    app.status = lambda: {**orig(), "ffmpeg": True, "ollama": state["ollama"], "ollama_info": "gemma3:4b"}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 900})
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        yield f"http://127.0.0.1:{srv.server_address[1]}", app, pg, state, errors
        b.close()
    srv.shutdown()


def test_ui_home_command_layout(ui):
    base, app, pg, state, errors = ui
    pg.goto(base + "/?t=tok#/")
    pg.wait_for_selector("#queue .qi.now")
    # bez dawnego hasła na pół ekranu; pole linku to pierwszy element pod paskiem
    assert not pg.locator(".hero").count()
    top = pg.evaluate("document.querySelector('#setup').getBoundingClientRect().bottom")   # karta pierwszego
    assert pg.locator("#drop").bounding_box()["y"] - top < 120                             # uruchomienia (bez Ollamy)
    # tytuł filmu w kolejce zamiast linku; gotowe analizy nie dublują się w kolejce
    assert "Martwy ciąg — technika" in pg.inner_text("#queue .qi.now")
    assert pg.locator("#queue .qi").count() == 1
    # „Ostatnie”: zwinięte, po rozwinięciu najnowsza analiza na górze, link do wyniku
    assert "Ostatnie" in pg.inner_text("#ostatnie") and not pg.locator("#ostatnie .ri").count()
    pg.click("#recentt")
    titles = pg.locator("#ostatnie .rt").all_inner_texts()
    assert titles == ["Push day", "Idealne frytki"]
    assert pg.locator("#ostatnie .ri").first.get_attribute("href").startswith("#/wynik/")
    # opcje analizy schowane; otwierają się przyciskiem, zamykają Esc i kliknięciem obok
    assert not pg.is_visible("#optpop") and pg.inner_text("#optlbl") == "Pełna"
    pg.click("#optbtn")
    assert pg.is_visible("#amode") and pg.get_attribute("#optbtn", "aria-expanded") == "true"
    pg.click('#amode [data-mode="mowa"]')
    pg.wait_for_function("document.querySelector('#optlbl').innerText === 'Tylko mowa'")
    assert not pg.is_visible("#pvrow")                              # wstępne streszczenie tylko przy pełnej
    pg.keyboard.press("Escape")
    assert not pg.is_visible("#optpop")
    pg.click("#optbtn")
    pg.mouse.click(20, 860)                                         # kliknięcie obok okienka
    assert not pg.is_visible("#optpop")
    # jeden wskaźnik stanu zamiast trzech chipów
    assert pg.locator("#chips .chip").count() == 1 and pg.inner_text("#chips") == "Gotowy"
    assert not pg.locator(".lang").count()
    assert pg.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    assert not errors, errors


def test_ui_status_names_what_is_broken(ui):
    base, app, pg, state, errors = ui
    state["ollama"] = False
    pg.goto(base + "/?t=tok#/")
    pg.wait_for_selector("#chips .chip.bad")
    assert pg.inner_text("#chips") == "Coś nie działa: Ollama"
    assert "Claude Code" in pg.get_attribute("#chips .chip", "title")          # szczegóły w dymku


def test_ui_library_hides_empty_categories(ui):
    base, app, pg, state, errors = ui
    pg.goto(base + "/?t=tok#/biblioteka")
    pg.wait_for_selector(".vcard")
    shown = [t for t in pg.locator("#libt button").all_inner_texts() if t]
    vis = [b.inner_text() for b in pg.locator("#libt button").all() if b.is_visible()]
    assert vis == ["Wszystko", "przepis 1", "trening 1"], (vis, shown)
    assert "⏱" not in pg.inner_text("#libc")                         # data zamiast czasu analizy


def test_watermark_and_icon_served(ui):
    base, app, pg, state, errors = ui
    import urllib.request
    for path in ("/znak.svg", "/icon.svg"):
        with urllib.request.urlopen(base + path) as r:
            body = r.read().decode("utf-8")
        assert r.status == 200 and body.lstrip().startswith("<svg")
