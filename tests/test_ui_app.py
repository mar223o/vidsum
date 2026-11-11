"""0.11.0: strona główna z kolejką, Ustawienia, przełączanie języka w całym programie (Playwright, Chromium)."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
TOKEN = "apptoken"


@pytest.fixture()
def appsrv(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")
    from vidsum import gui
    from vidsum.pipeline import Options
    gate = threading.Event()

    def fake(src, opt, log):
        log("  [2/4] kadry")
        gate.wait(30)
        raise RuntimeError("test: brak filmu")
    monkeypatch.setattr(gui, "analyze", fake)
    app = gui.App(tmp_path / "wyniki", TOKEN)
    w = app.worker
    for n in ("pierwszy.mp4", "drugi.mp4", "trzeci.mp4"):
        j = gui.Job(n.split(".")[0], str(tmp_path / n), n, Options(), None)
        w.submit(j)
    for _ in range(100):
        if w.current:
            break
        time.sleep(0.02)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), gui.make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", app
    gate.set()
    srv.shutdown()


def _browser(p):
    try:
        return p.chromium.launch()
    except Exception as e:
        pytest.skip(f"brak Chromium: {e}")


# teksty, które nie mogą zostać po polsku w wersji angielskiej (i odwrotnie) — z widocznych elementów
PL_ONLY = re.compile(r"\b(Kolejka|Ustawienia|Analizuj|Biblioteka|czeka|Wstrzymaj|Wznów|Zapisz|Diagnostyka|Silnik wideo|Zamknij)\b")
EN_ONLY = re.compile(r"\b(Queue|Settings|Analyze|Library|waiting|Pause|Resume|Save settings|Diagnostics|Video engine|Quit app)\b")


@pytest.mark.parametrize("width", [1280, 390])
def test_home_queue_settings_and_language(appsrv, width):
    base, app = appsrv
    shots = Path(os.environ.get("VIDSUM_SHOTS") or app.results)
    shots.mkdir(parents=True, exist_ok=True)
    with pw.sync_playwright() as p:
        b = _browser(p)
        page = b.new_page(viewport={"width": width, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{base}/?t={TOKEN}#/")
        page.wait_for_selector("#queue .qi.now")
        # strona główna: bez „Ostatnio”, kolejka z trwającym i dwoma oczekującymi, przycisk „Ustawienia” zamiast „Zakończ”
        assert not page.locator("#recent").count() and not page.locator("#quit").count()
        assert page.locator('nav a[data-nav="set"]').is_visible()
        assert page.locator("#queue .qi").count() == 3
        assert "1 w toku" in page.inner_text("#queue") and "2 czeka" in page.inner_text("#queue")
        assert "Etap 2/4" in page.inner_text("#queue .qi.now")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        page.screenshot(path=str(shots / f"start_{width}.png"), full_page=True)
        # 0.11.5: tryb wstępnego streszczenia wybiera się przy linku (nie w Ustawieniach) i zapamiętuje
        page.click('#pvmode [data-pv="zawsze"]')
        page.wait_for_function("document.querySelector('#pvmode [data-pv=\"zawsze\"]').classList.contains('on')")
        page.wait_for_function("document.querySelector('#pvhint').innerText.includes('1:42')")
        for _ in range(50):
            if app.settings.get("tryb_podgladu") == "zawsze":
                break
            time.sleep(0.05)
        assert app.settings["tryb_podgladu"] == "zawsze"
        page.click('#pvmode [data-pv="najszybciej"]')
        page.wait_for_function("document.querySelector('#pvmode [data-pv=\"najszybciej\"]').classList.contains('on')")
        # kolejka: trzeci na górę oczekujących, usuń drugi, wstrzymaj
        page.click('#queue [data-q="przesun"][data-id="trzeci"]')
        page.wait_for_function("document.querySelectorAll('#queue .qi.w_kolejce')[0]?.innerText.includes('trzeci')")
        page.click('#queue [data-q="usun"][data-id="drugi"]')
        page.wait_for_function("document.querySelectorAll('#queue .qi.w_kolejce').length === 1")
        page.click('#queue [data-q="pauza"]')
        page.wait_for_selector("#queue .qnotice")
        assert app.worker.paused and [j.id for j in app.worker.pending] == ["trzeci"]
        # Ustawienia: prawdziwe sekcje, diagnostyka z silnikiem wideo
        page.click('nav a[data-nav="set"]')
        page.wait_for_selector(".setnav")
        txt = page.inner_text("#app")
        # zapis od razu po zmianie (bez przycisku „Zapisz”)
        page.click('.setnav [data-sec="an"]')
        page.select_option("#s_ocr", "false")
        page.wait_for_function("document.querySelector('#toast').innerText.includes('Zapisano')")
        assert app.settings["ocr"] is False
        assert app.settings["tryb_podgladu"] == "najszybciej" and not page.locator("#s_tryb_podgladu").count()
        page.click('.setnav [data-sec="diag"]')
        page.wait_for_selector("#diag .drow")
        for h in ("Interfejs", "Analiza", "Modele AI", "Pliki i pobieranie", "Diagnostyka", "Aktualizacje", "O programie", "Zamykanie"):
            assert h in txt, h
        assert "Silnik wideo" in page.inner_text("#diag")
        page.screenshot(path=str(shots / f"ustawienia_{width}.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        # zmiana języka w Ustawieniach: cały program po angielsku, bez restartu
        page.click('.setnav [data-sec="ui"]')
        page.select_option("#set_lang", "en")
        page.wait_for_function("document.documentElement.lang === 'en'")
        page.click('.setnav [data-sec="diag"]')
        page.wait_for_selector("#diag .drow")
        whole = page.inner_text("body")
        assert "Settings" in whole and "Diagnostics" in whole and "Video engine" in page.inner_text("#diag")
        assert not PL_ONLY.search(whole), PL_ONLY.findall(whole)
        page.click('nav a[data-nav="home"]')
        page.wait_for_selector("#queue .qi")
        whole = page.inner_text("body")
        assert "Queue" in whole and not PL_ONLY.search(whole), PL_ONLY.findall(whole)
        page.screenshot(path=str(shots / f"start_en_{width}.png"), full_page=True)
        # i z powrotem po polsku przyciskiem w pasku
        page.click('.lang button[data-l="pl"]')
        page.wait_for_function("document.documentElement.lang === 'pl'")
        assert not EN_ONLY.search(page.inner_text("body")), EN_ONLY.findall(page.inner_text("body"))
        b.close()
    assert not errors, errors
    assert json.loads((Path(os.environ["LOCALAPPDATA"]) / "VidSum" / "ustawienia.json").read_text())["jezyk_ui"] == "pl"
