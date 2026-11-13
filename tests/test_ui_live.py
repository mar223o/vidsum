"""Strona wyniku w przeglądarce (Playwright, Chromium): otwiera się od razu, transkrypcja jest od pierwszych sekund,
kolejne części dochodzą bez przesuwania czytanego fragmentu, a po końcu analizy pojawia się pełny wynik.

Uruchamia się tylko, gdy jest Playwright z przeglądarką (lokalnie / w kontenerze); w CI bez przeglądarki — pominięty.
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")
DATA = Path(__file__).parent / "data"
BENCH = Path(__file__).parent / "bench" / "data" / "frytki_076.json"
TOKEN = "uitoken"


def _segments(n_rep: int = 4) -> list[dict]:
    """Długa transkrypcja (frytki ×4), żeby było co przewijać."""
    seg = json.loads(BENCH.read_text(encoding="utf-8"))["segmenty"]
    out = []
    for r in range(n_rep):
        out += [{**s, "start": s["start"] + 60 * r, "end": s["end"] + 60 * r} for s in seg]
    return out


@pytest.fixture()
def live(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")
    from vidsum.gui import App, Job, make_handler
    from vidsum.pipeline import Options
    app = App(tmp_path / "wyniki", TOKEN)
    out = tmp_path / "wyniki" / "film_1"
    (out / "kadry").mkdir(parents=True)
    job = Job("abcd1234", "https://example.com/v", "https://example.com/v", Options(out_root=tmp_path), None)
    job.status, job.started, job.out, job.stage = "trwa", time.time() - 12, out, "1"
    job.log = ["▶ https://example.com/v", "  [1/4] mowa: napisy serwisu"]
    segs = _segments()
    job.partial.update({"meta": {"tytul": "The Perfect French Fry", "autor": "Fallow", "dlugosc_s": 238.0,
                                 "szerokosc": 360, "wysokosc": 640},
                        "transkrypcja": {"jezyk": "en", "segmenty": segs}})
    app.worker.jobs[job.id] = job
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", app, job, out, segs
    srv.shutdown()


def _final(out: Path, segs: list[dict]) -> None:
    d = json.loads(BENCH.read_text(encoding="utf-8"))
    steps = [{"t": 13.0, "tekst": "Obierz ziemniaki, przytnij końce i boki.", "zrodlo": "mowa"},
             {"t": 41.4, "tekst": "Rozgrzej olej do 140 stopni.", "zrodlo": "mowa"}]
    dane = {"schema": "vidsum.summary/1", "typ": "przepis", "tytul": "Idealne frytki", "tytul_akcent": "dwa smażenia",
            "teza": "Chrupkie frytki to ziemniaki agria, soda i dwa smażenia.",
            "streszczenie": ["Akapit pierwszy. " * 12, "Akapit drugi. " * 12, "Akapit trzeci. " * 12],
            "do_zapamietania": "Smaż dwa razy: 140 i 190 stopni.", "czas_czytania_s": 70, "metoda": "kroki z linii mowy",
            "co_masz_zrobic": {"skladniki": [{"nazwa": "ziemniaki agria", "ilosc": "brak danych", "zrodlo": "mowa"}],
                               "kroki": steps, "sprzet": [], "czas": "", "cwiczenia": [], "wskazowki": [], "bledy": [],
                               "wnioski": []},
            "najwazniejsze": [], "momenty": [], "cytaty": [], "rozdzialy": [], "szczera_ocena": "Konkretny przepis.",
            "czego_nie_wiadomo": [], "pytania": ["Dlaczego soda?"]}
    r = {"schema": "vidsum.analysis/1", "utworzono": "2026-11-08T20:00:00+01:00",
         "zrodlo": {"tytul": "The Perfect French Fry", "autor": "Fallow", "dlugosc_s": 238.0, "film": "brak.mp4",
                    "szerokosc": 360, "wysokosc": 640},
         "ustawienia": {"whisper": "faster-whisper", "obraz": "brak", "streszczenie": "ollama:gemma3:4b"},
         "transkrypcja": {"jezyk": "en", "segmenty": segs, "tlumaczenia": {}},
         "napisy_ekranowe": d["napisy"], "kadry": [], "os_czasu": [], "luki": [], "czasy": {"razem_s": 99.0},
         "streszczenie": {"silnik": "ollama:gemma3:4b", "markdown": "x", "dane": dane}}
    (out / "analiza.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("width", [1280, 390])      # trzy kolumny i telefon (streszczenie NAD transkrypcją)
def test_live_result_page_keeps_reading_position(live, width):
    base, app, job, out, segs = live
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:                      # brak przeglądarki
            pytest.skip(f"brak Chromium: {e}")
        page = b.new_page(viewport={"width": width, "height": 860})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(f"{base}/?t={TOKEN}#/wynik/{job.id}")
        # od razu: tytuł, pasek etapów, transkrypcja (zakładka domyślna podczas analizy), szkielet streszczenia
        page.wait_for_selector("#tabc .tr-line")
        assert "The Perfect French Fry" in page.inner_text("#rhead")
        assert page.locator(".lstep.now").count() == 1
        assert page.locator("#csum .skel").count() == 1
        assert page.locator("#tabc .tr-line").count() == len(segs)
        shots = Path(os.environ.get("VIDSUM_SHOTS") or out)
        page.screenshot(path=str(shots / f"na_zywo_{width}.png"))
        # czytam transkrypcję: przewijam do linii z ok. 2:30
        line = page.locator('#tabc .tr-line').nth(120)
        line.scroll_into_view_if_needed()
        page.evaluate("window.scrollBy(0, -200)")
        before = line.bounding_box()["y"]
        # dochodzą kadry i kroki (etap 4/4)
        job.stage = "4"
        job.partial["kroki"] = {"typ": "przepis", "kroki": [{"t": 13.0, "tekst": "Obierz ziemniaki.", "zrodlo": "mowa"}],
                                "skladniki": []}
        page.wait_for_selector('#tabs button[data-tab="todo"]', timeout=8000)
        assert abs(line.bounding_box()["y"] - before) <= 2, "czytany fragment przesunął się po dojściu kroków"
        # koniec analizy: pełny wynik, ta sama zakładka (czytający nie traci miejsca), streszczenie i czas czytania
        _final(out, segs)
        job.status, job.finished = "gotowe", time.time()
        page.wait_for_selector("#csum .summary p", timeout=8000)
        page.wait_for_timeout(400)
        assert page.locator("#tabs button.on").get_attribute("data-tab") == "tr"
        line = page.locator('#tabc .tr-line').nth(120)
        assert abs(line.bounding_box()["y"] - before) <= 2, "czytany fragment przesunął się po końcu analizy"
        assert "czytania" in page.inner_text("#csum")
        assert "Smaż dwa razy" in page.inner_text("#csum")
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(shots / f"wynik_{width}.png"))
        # telefon: jedna kolumna, bez poziomego przewijania
        page.set_viewport_size({"width": 390, "height": 800})
        page.wait_for_timeout(200)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        b.close()
    assert not [e for e in errors if "favicon" not in e and "film" not in e and "404" not in e], errors


def test_quick_preview_then_full_and_mind_map(live):
    """0.8.2: wstępne streszczenie (oznaczone) w trakcie analizy → pełne z opisem „wstępne po … → pełne po …”;
    mapa myśli: kliknięcie gałęzi pokazuje szczegóły z czasem, kółko myszy powiększa, „Dopasuj” wraca."""
    base, app, job, out, segs = live
    job.partial["wstepne"] = {"typ": "inne", "tytul": "Frytki", "teza": "Frytki smażone dwa razy.", "wstepne": True,
                              "streszczenie": ["Wstępny akapit o frytkach z mowy."], "do_zapamietania": "",
                              "najwazniejsze": [{"t": 41.0, "tytul": "Olej 140", "opis": "Pierwsze smażenie.", "zrodlo": "mowa"}],
                              "momenty": [], "cytaty": [], "rozdzialy": [], "szczera_ocena": "", "czego_nie_wiadomo": [],
                              "pytania": [], "co_masz_zrobic": {"skladniki": [], "kroki": [], "sprzet": [], "czas": "",
                                                                 "cwiczenia": [], "wskazowki": [], "bledy": [], "wnioski": []}}
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"brak Chromium: {e}")
        page = b.new_page(viewport={"width": 1280, "height": 860})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{base}/?t={TOKEN}#/wynik/{job.id}")
        page.wait_for_selector("#csum .summary.prelim p")
        assert "Wstępny akapit" in page.inner_text("#csum")
        assert page.inner_text("#csum .pvtag").strip() == "wstępne"
        assert not page.locator('#tabs button[data-tab="map"]').count()     # mapa dopiero z pełnego wyniku
        # koniec analizy: pełne streszczenie z rozdziałami
        _final(out, segs)
        r = json.loads((out / "analiza.json").read_text(encoding="utf-8"))
        r["podglad"] = {"po_s": 25.0, "s": 6.2}
        r["streszczenie"]["dane"]["rozdzialy"] = [
            {"start": 0, "end": 30, "tytul": "Przygotowanie", "opis": "Obieranie i krojenie.", "momenty": []},
            {"start": 30, "end": 60, "tytul": "Smażenie", "opis": "Dwa smażenia.", "momenty": []}]
        r["streszczenie"]["dane"]["najwazniejsze"] = [{"t": 41.4, "tytul": "Olej 140", "opis": "Pierwsze smażenie.",
                                                      "zrodlo": "mowa"}]
        (out / "analiza.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        job.status, job.finished = "gotowe", time.time()
        page.wait_for_selector("#csum .pvtag.done", timeout=8000)
        assert "→" in page.inner_text("#csum .pvtag.done") and not page.locator(".summary.prelim").count()
        page.click('#tabs button[data-tab="map"]')
        page.wait_for_selector("#mapsvg .mnode")
        assert page.locator("#mapsvg .mnode").count() == 1 + 3 + 3       # środek, 3 gałęzie, liście: 2 kroki + 1 punkt
        node = page.locator('#mapsvg .mnode[aria-label="Smażenie"]')
        node.click()
        info = page.inner_text("#mapinfo")
        assert "Smażenie" in info and "00:30" in info and "Dwa smażenia" in info and "W filmie mówi" in info
        vb0 = page.get_attribute("#mapsvg", "viewBox")
        page.hover("#mapsvg")
        page.keyboard.down("Control")
        page.mouse.wheel(0, -300)
        page.keyboard.up("Control")
        page.wait_for_timeout(100)
        vb1 = page.get_attribute("#mapsvg", "viewBox")
        assert float(vb1.split()[2]) < float(vb0.split()[2])               # przybliżone
        page.click('#mapwrap [data-z="0"]')
        assert page.get_attribute("#mapsvg", "viewBox") == vb0
        shots = Path(os.environ.get("VIDSUM_SHOTS") or out)
        page.screenshot(path=str(shots / "mapa.png"))
        b.close()
    assert not errors, errors


@pytest.mark.parametrize("width", [1280, 1000, 820, 390])
def test_breakdown_tabs_fit_and_new_tabs(live, width):
    """0.10.0: pasek zakładek „Breakdown” w trybie Wideo mieści się bez przewijania w bok (zawija się), każda zakładka
    ma ikonę; rozdziały mają paski proporcji (od autora osobno), najważniejsze są zwijane, jest opis od autora,
    komentarze (z zapisanego pliku) i tryb kinowy, który nie przeładowuje filmu."""
    base, app, job, out, segs = live
    _final(out, segs)
    r = json.loads((out / "analiza.json").read_text(encoding="utf-8"))
    d = r["streszczenie"]["dane"]
    d["rozdzialy"] = [{"start": 0, "end": 60, "tytul": "Przygotowanie", "opis": "Obieranie.", "momenty": []},
                      {"start": 60, "end": 238, "tytul": "Smażenie", "opis": "Dwa smażenia.", "momenty": []}]
    d["najwazniejsze"] = [{"t": 41.4, "tytul": "Olej 140", "opis": "Pierwsze smażenie w 140 stopniach.", "zrodlo": "mowa"},
                          {"t": 90.0, "tytul": "Olej 190", "opis": "Drugie smażenie w 190 stopniach.", "zrodlo": "mowa"}]
    d["momenty"] = [{"t": 41.4, "tekst": "Olej 140"}]
    d["cytaty"] = [{"t": 34.0, "tekst": "This is going to add a beautiful crispy layer.", "tlumaczenie": "Chrupka warstwa."}]
    r["zrodlo"].update({"rodzaj": "link", "url": "https://www.youtube.com/watch?v=x", "opis": "Przepis na frytki.\n0:00 Start\n1:00 Smażenie",
                        "rozdzialy_autora": [{"start": 0, "end": 60, "tytul": "Start"}, {"start": 60, "end": 238, "tytul": "Smażenie"}],
                        "obraz_bez_pasow": {"x": 0, "y": 40, "w": 360, "h": 560}})
    (out / "analiza.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    (out / "komentarze.json").write_text(json.dumps({"stan": "gotowe", "dostepne": True, "pobrano": "2026-11-10 12:00",
                                                     "komentarze": [{"autor": "@ola", "tekst": "Najlepsze frytki!", "polubienia": 12,
                                                                     "odpowiedz": False}]}), encoding="utf-8")
    job.status, job.finished = "gotowe", time.time()
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"brak Chromium: {e}")
        page = b.new_page(viewport={"width": width, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script("try{localStorage.setItem('vs_mode','video');localStorage.removeItem('vs_cinema')}catch(e){}")
        page.goto(f"{base}/?t={TOKEN}#/wynik/{job.id}")
        page.wait_for_selector("#csum .summary p", timeout=8000)
        tabs = page.locator("#tabs button")
        assert tabs.count() == 10                     # todo key mom quo cha map tr fr desc com
        assert page.locator("#tabs button svg").count() == 10
        assert page.evaluate("(() => { const t = document.querySelector('#tabs'); return t.scrollWidth <= t.clientWidth + 1; })()")
        assert page.evaluate("""(() => { const t = document.querySelector('#tabs').getBoundingClientRect();
            return [...document.querySelectorAll('#tabs button')].every(b => { const r = b.getBoundingClientRect();
              return r.left >= t.left - 1 && r.right <= t.right + 1; }); })()""")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        shots = Path(os.environ.get("VIDSUM_SHOTS") or out)
        page.screenshot(path=str(shots / f"zakladki_{width}.png"))
        # 0.11.3: na szerokim ekranie wynik mieści się na jednym ekranie we wszystkich trybach — przewija się kolumna
        if width >= 1000:
            assert "Otwórz film na YouTube" in page.inner_text("#rhead")
            assert page.get_attribute("#rhead a.srclink", "href") == "https://www.youtube.com/watch?v=x"
            # 0.13.1: dwa przyciski — „Raport z filmu” i „Prompt do streszczenia”; „Kopiuj / Pobierz” dopiero po kliknięciu
            acts = page.inner_text("#rhead .actions")
            assert "Raport z filmu" in acts and "Prompt do streszczenia" in acts and "JSON" not in acts
            menu = page.locator("#rhead details.dd").first
            assert not menu.locator(".ddm").is_visible(), "menu zamknięte, dopóki nie klikniesz"
            menu.locator("summary").click()
            assert menu.locator(".ddm").is_visible() and "Kopiuj" in menu.inner_text() and "Pobierz" in menu.inner_text()
            assert "/notatka?pobierz=1" in menu.locator("a.btn").get_attribute("href")
            page.screenshot(path=str(shots / f"menu_raportu_{width}.png"))
            page.mouse.click(5, 5)
            page.wait_for_timeout(100)
            assert not menu.locator(".ddm").is_visible(), "kliknięcie obok zamyka menu"
            for m in ("bal", "read", "video"):
                page.click(f'#modes button[data-m="{m}"]')
                page.wait_for_timeout(150)
                assert page.evaluate("document.documentElement.scrollHeight <= window.innerHeight + 1"), (m, width, page.evaluate(
                    "[document.documentElement.scrollHeight, innerHeight, ...[...document.querySelectorAll('#res, .layout, .layout>section, main')].map(e => e.className + ':' + Math.round(e.getBoundingClientRect().bottom))]"))
                assert page.evaluate("[...document.querySelectorAll('.layout>section')].every(s => s.getBoundingClientRect().bottom <= innerHeight + 1)"), m
                page.screenshot(path=str(shots / f"tryb_{m}_{width}.png"))
        # transkrypcja: przycisk „Kopiuj transkrypcję”
        page.click('#tabs button[data-tab="tr"]')
        assert page.locator('#tabc [data-a="copytr"]').count() == 1
        # rozdziały: pasek całego filmu i udział każdego rozdziału (od autora + z analizy)
        page.click('#tabs button[data-tab="cha"]')
        assert page.locator(".chstrip").count() == 2 and page.locator(".chstrip.au button").count() == 2
        assert "25% filmu" in page.inner_text("#tabc") and "75% filmu" in page.inner_text("#tabc")
        w = page.evaluate("document.querySelector('.chstrip:not(.au) button:nth-child(2)').style.width")
        assert w.startswith("74.7")
        # najważniejsze: pierwszy rozwinięty, drugi zwinięty, „Rozwiń wszystkie”
        page.click('#tabs button[data-tab="key"]')
        assert page.evaluate("[...document.querySelectorAll('details.kp')].map(x => x.open)") == [True, False]
        page.click('[data-a="keyall"]')
        assert page.evaluate("[...document.querySelectorAll('details.kp')].map(x => x.open)") == [True, True]
        # opis od autora: czasy klikalne
        page.click('#tabs button[data-tab="desc"]')
        assert "Przepis na frytki" in page.inner_text("#tabc") and page.locator("#tabc .desc .tsb").count() == 2
        # komentarze z zapisanego pliku
        page.click('#tabs button[data-tab="com"]')
        page.wait_for_selector("#tabc .com")
        assert "Najlepsze frytki!" in page.inner_text("#tabc") and "nie fakty" in page.inner_text("#tabc")
        # tryb kinowy: film na całą szerokość, ten sam element <video>
        page.evaluate("window._v = document.querySelector('#cplayer .player')")
        page.click('[data-a="cinema"]')
        assert page.evaluate("document.querySelector('#res').classList.contains('cinema')")
        assert page.evaluate("window._v === document.querySelector('#cplayer .player')")
        lay = page.evaluate("document.querySelector('.layout').getBoundingClientRect().width")
        mid = page.evaluate("document.querySelector('.col-mid').getBoundingClientRect().width")
        assert mid >= lay - 2
        if width == 1280:
            page.screenshot(path=str(shots / "kinowy.png"))
        page.keyboard.press("Escape")
        # czarne pasy: przycisk przełącza między kadrem bez pasów a całym kadrem
        assert page.inner_text('[data-a="bars"]').strip() == "Pokaż cały kadr"
        page.click('[data-a="bars"]')
        page.wait_for_function("document.querySelector('[data-a=bars]').innerText.includes('Ukryj')")
        assert not page.evaluate("document.querySelector('#res').classList.contains('cinema')")
        b.close()
    assert not errors, errors


@pytest.mark.parametrize("typ", ["dokument", "sport"])
def test_type_panels_document_and_sport(live, typ):
    """0.11.5: panel zależny od typu — dokument: „Fakty, liczby, osoby, daty”; sport: „Ćwiczenia i elementy techniki”."""
    base, app, job, out, segs = live
    _final(out, segs)
    r = json.loads((out / "analiza.json").read_text(encoding="utf-8"))
    c = r["streszczenie"]["dane"]["co_masz_zrobic"]
    r["streszczenie"]["dane"]["typ"] = typ
    c.update({"skladniki": [], "kroki": []})
    if typ == "dokument":
        c["fakty"] = [{"t": 12.0, "tekst": "Most otwarto w 1937 roku.", "rodzaj": "data", "zrodlo": "mowa"},
                      {"t": 30.0, "tekst": "Długość: 2737 m.", "rodzaj": "liczba", "zrodlo": "mowa+obraz"}]
    else:
        c["cwiczenia"] = [{"nazwa": "Elastico", "serie": "", "powtorzenia": "10", "t": 20.0,
                           "technika": "Zewnętrzną częścią stopy, potem wewnętrzną.", "zrodlo": "mowa"}]
    (out / "analiza.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    job.status, job.finished = "gotowe", time.time()
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"brak Chromium: {e}")
        page = b.new_page(viewport={"width": 1280, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{base}/?t={TOKEN}#/wynik/{job.id}")
        page.wait_for_selector('#tabs button[data-tab="todo"]')
        page.click('#tabs button[data-tab="todo"]')
        txt = page.inner_text("#tabc")
        if typ == "dokument":
            assert "Fakty" in page.inner_text("#tabs") and "Fakty, liczby, osoby, daty" in txt
            assert "data" in txt and "1937" in txt and "liczba" in txt
        else:
            assert "Ćwiczenia i technika" in page.inner_text("#tabs") and "Ćwiczenia i elementy techniki" in txt
            assert "Elastico" in txt
        assert not errors, errors
        b.close()


def test_chat_suggestions_by_type(live):
    """0.11.5: propozycje pytań w czacie — 2–3 typowe dla przepisu (składniki, porcje, skład) + pytania od modelu."""
    base, app, job, out, segs = live
    _final(out, segs)
    job.status, job.finished = "gotowe", time.time()
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"brak Chromium: {e}")
        page = b.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{base}/?t={TOKEN}#/wynik/{job.id}")
        page.wait_for_selector("#sugg button")
        qs = page.eval_on_selector_all("#sugg button", "bs => bs.map(b => b.dataset.q)")
        assert qs[:3] == ["Jakie składniki są potrzebne?", "Przelicz składniki na 4 porcje", "Jaki jest skład i ile to ma kalorii?"]
        assert "Dlaczego soda?" in qs and len(qs) <= 6
        b.close()
