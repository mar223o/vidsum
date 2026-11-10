"""Tłumaczenie całej analizy na żądanie (0.9.0): streszczenie, kroki, kadry, transkrypcja — PL ↔ EN."""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import pytest


class EchoEN:
    """Atrapa modelu: „tłumaczy” każdą numerowaną linię jako „EN: …” (z zachowaną numeracją)."""
    model = "atrapa"

    def __init__(self):
        self.calls = 0

    def complete(self, prompt, as_json=False, **kw):
        self.calls += 1
        lines = re.findall(r"^(\d+)\. (.*)$", prompt.split("LINES:")[1], re.M)
        return json.dumps({n: "EN: " + t for n, t in lines}, ensure_ascii=False)


def _analysis(lang="en"):
    dane = {"tytul": "Idealne frytki", "teza": "Dwa smażenia.", "streszczenie": ["Akapit 1.", "Akapit 2."],
            "do_zapamietania": "Smaż dwa razy.", "szczera_ocena": "Konkretny.", "czego_nie_wiadomo": ["Ilości."],
            "pytania": ["Dlaczego soda?"],
            "najwazniejsze": [{"t": 52.0, "tytul": "Olej 190", "opis": "Drugie smażenie."}],
            "momenty": [{"t": 13.0, "tekst": "Obierz."}],
            "rozdzialy": [{"start": 0, "end": 30, "tytul": "Przygotowanie", "opis": "Obieranie."}],
            "cytaty": [{"t": 34.0, "tekst": "Extra crunch.", "tlumaczenie": "Dodatkowa chrupkość."}],
            "co_masz_zrobic": {"skladniki": [{"nazwa": "ziemniaki agria", "ilosc": "brak danych", "zrodlo": "mowa"}],
                               "kroki": [{"t": 41.4, "tekst": "Rozgrzej olej do 140 stopni.", "zrodlo": "mowa"}],
                               "sprzet": ["garnek"], "czas": "", "cwiczenia": [], "wskazowki": ["Agria ma dużo skrobi."],
                               "bledy": [], "wnioski": []}}
    return {"streszczenie": {"dane": dane},
            "kadry": [{"t": 4.5, "file": "kadry/k1.jpg", "vision": {"scena": "Ręce kroją ziemniak.",
                                                                    "czynnosci": ["krojenie"], "obiekty": ["nóż"]}}],
            "transkrypcja": {"jezyk": lang, "segmenty": [{"start": 1.0, "end": 2.0, "text": "Peel."}],
                             "tlumaczenia": {}}}


def test_whole_analysis_to_english_keeps_times_and_original():
    from vidsum.translate_all import translate_analysis
    r = _analysis("en")
    before = json.dumps(r, sort_keys=True)
    out = translate_analysis(EchoEN(), r, "en")
    d = out["dane"]
    assert json.dumps(r, sort_keys=True) == before                       # oryginał nietknięty
    assert d["tytul"] == "EN: Idealne frytki" and d["streszczenie"] == ["EN: Akapit 1.", "EN: Akapit 2."]
    assert d["najwazniejsze"][0] == {"t": 52.0, "tytul": "EN: Olej 190", "opis": "EN: Drugie smażenie."}
    assert d["rozdzialy"][0]["start"] == 0 and d["rozdzialy"][0]["tytul"] == "EN: Przygotowanie"
    assert d["cytaty"][0]["tekst"] == "Extra crunch."                      # cytat w oryginale zostaje
    todo = d["co_masz_zrobic"]
    assert todo["kroki"][0] == {"t": 41.4, "tekst": "EN: Rozgrzej olej do 140 stopni.", "zrodlo": "mowa"}
    assert todo["skladniki"][0]["nazwa"] == "EN: ziemniaki agria" and todo["skladniki"][0]["ilosc"] == "no data"
    assert todo["sprzet"] == ["EN: garnek"] and todo["wskazowki"] == ["EN: Agria ma dużo skrobi."]
    v = out["kadry"][0]["vision"]
    assert v["scena"] == "EN: Ręce kroją ziemniak." and v["czynnosci"] == ["EN: krojenie"]
    assert out["transkrypcja"] == {"segmenty": r["transkrypcja"]["segmenty"], "zrodlo": "oryginał"}
    assert out["nieprzetlumaczone"] == 0 and out["jezyk"] == "en"


def test_whole_analysis_to_polish_translates_only_transcript():
    from vidsum.translate_all import translate_analysis
    e = EchoEN()
    out = translate_analysis(e, _analysis("en"), "pl")
    assert out["dane"]["tytul"] == "Idealne frytki"                    # streszczenie jest już po polsku
    assert out["transkrypcja"]["zrodlo"] == "przetłumaczona" and out["transkrypcja"]["segmenty"][0]["text"] == "EN: Peel."
    assert e.calls == 1


def test_failed_lines_stay_in_original_and_are_counted():
    from vidsum.translate_all import translate_analysis

    class Broken(EchoEN):
        def complete(self, prompt, as_json=False, **kw):
            return "nie JSON"
    out = translate_analysis(Broken(), _analysis("en"), "en")
    assert out["dane"]["tytul"] == "Idealne frytki" and out["nieprzetlumaczone"] > 10
    with pytest.raises(ValueError):
        translate_analysis(EchoEN(), _analysis(), "de")


def test_translate_endpoint_runs_in_background_and_saves(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    import vidsum.gui as gui
    from vidsum.gui import App, Job, make_handler
    from vidsum.pipeline import Options

    class FakeOllama(EchoEN):
        def __init__(self, *a, **k):
            super().__init__()

        def ensure(self, log):
            pass
    monkeypatch.setattr(gui, "Ollama", FakeOllama)
    app = App(tmp_path / "wyniki", "tok")
    out = tmp_path / "wyniki" / "film"
    out.mkdir(parents=True)
    (out / "analiza.json").write_text(json.dumps(_analysis("en"), ensure_ascii=False), encoding="utf-8")
    job = Job("abc123", "x", "x", Options(out_root=tmp_path), None)
    job.status, job.out = "gotowe", out
    app.worker.jobs[job.id] = job
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(method, data=None, q=""):
        rq = urllib.request.Request(f"{base}/api/zadania/abc123/tlumacz{q}", method=method,
                                    data=json.dumps(data).encode() if data else None, headers={"X-Token": "tok"})
        with urllib.request.urlopen(rq, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    try:
        assert call("GET", q="?jezyk=en")[1]["stan"] == "brak"
        st, body = call("POST", {"jezyk": "en"})
        assert st in (200, 202) and body["stan"] in ("trwa", "gotowe")
        for _ in range(50):
            if call("GET", q="?jezyk=en")[1]["stan"] == "gotowe":
                break
            time.sleep(0.1)
        r = json.loads((out / "analiza.json").read_text(encoding="utf-8"))
        assert r["tlumaczenie_calosci"]["en"]["dane"]["tytul"] == "EN: Idealne frytki"
        assert r["streszczenie"]["dane"]["tytul"] == "Idealne frytki"      # oryginał zostaje
        assert call("POST", {"jezyk": "en"})[1]["stan"] == "gotowe"        # drugi raz nie liczy od nowa
        with pytest.raises(urllib.error.HTTPError):
            call("POST", {"jezyk": "de"})
    finally:
        srv.shutdown()


def test_result_language_switch_in_browser(tmp_path, monkeypatch):
    """Przełącznik „Język wyniku” PL ↔ EN: tłumaczy całość w tle, pokazuje wersję EN (nagłówek, streszczenie, kroki),
    powrót na PL bez ponownego tłumaczenia."""
    pw = pytest.importorskip("playwright.sync_api")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    import vidsum.gui as gui
    from vidsum.gui import App, Job, make_handler
    from vidsum.pipeline import Options

    class FakeOllama(EchoEN):
        def __init__(self, *a, **k):
            super().__init__()

        def ensure(self, log):
            pass
    monkeypatch.setattr(gui, "Ollama", FakeOllama)
    app = App(tmp_path / "wyniki", "tok")
    out = tmp_path / "wyniki" / "film"
    (out / "kadry").mkdir(parents=True)
    r = _analysis("en")
    r.update({"schema": "vidsum.analysis/1", "utworzono": "2026-11-10T17:00:00+01:00",
              "zrodlo": {"tytul": "The Perfect French Fry", "autor": "Fallow", "dlugosc_s": 58.0, "film": "brak.mp4"},
              "ustawienia": {"whisper": "w", "obraz": "o", "streszczenie": "s"}, "napisy_ekranowe": [], "os_czasu": [],
              "luki": [], "czasy": {"razem_s": 80.0}})
    d = r["streszczenie"]["dane"]
    d.update({"schema": "vidsum.summary/1", "typ": "przepis", "tytul_akcent": "", "metoda": "kroki z linii mowy"})
    r["streszczenie"]["markdown"] = "x"
    (out / "analiza.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    job = Job("abc123", "x", "x", Options(out_root=tmp_path), None)
    job.status, job.out, job.finished = "gotowe", out, time.time()
    app.worker.jobs[job.id] = job
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pw.sync_playwright() as p:
            try:
                b = p.chromium.launch()
            except Exception as e:
                pytest.skip(f"brak Chromium: {e}")
            page = b.new_page(viewport={"width": 1280, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{srv.server_address[1]}/?t=tok#/wynik/abc123")
            page.wait_for_selector("#csum .summary p")
            assert page.inner_text("#rhead h1") == "Idealne frytki"
            page.click('#rlang button[data-rl="en"]')
            page.wait_for_function("document.querySelector('#rhead h1').innerText.startsWith('EN:')", timeout=8000)
            assert "EN: Akapit 1." in page.inner_text("#csum")
            assert "EN: Rozgrzej olej do 140 stopni." in page.inner_text("#tabc")
            assert page.locator('#rlang button.on').get_attribute("data-rl") == "en"
            page.click('#rlang button[data-rl=""]')
            page.wait_for_function("document.querySelector('#rhead h1').innerText === 'Idealne frytki'")
            b.close()
        assert not [e for e in errors if "film" not in e], errors
    finally:
        srv.shutdown()


def test_retranslation_only_changed_texts_and_staleness():
    """0.11.0: oryginał jest źródłem prawdy — po zmianie oryginału tłumaczenie jest nieaktualne, a ponowne
    tłumaczy tylko zmienione teksty (reszta z pamięci)."""
    from vidsum.translate_all import is_current, source_hash, translate_analysis
    r = _analysis("en")
    eng = EchoEN()
    first = translate_analysis(eng, r, "en")
    r["tlumaczenie_calosci"] = {"en": first}
    assert is_current(r, "en") and first["zrodlo_hash"] == source_hash(r) and first["z_pamieci"] == 0
    r["streszczenie"]["dane"]["teza"] = "Dwa smażenia w 140 i 190 stopniach."        # oryginał się zmienił
    assert not is_current(r, "en")
    seen = []

    class Spy(EchoEN):
        def complete(self, prompt, as_json=False, **kw):
            seen.extend(re.findall(r"^\d+\. (.*)$", prompt.split("LINES:")[1], re.M))
            return super().complete(prompt, as_json, **kw)
    second = translate_analysis(Spy(), r, "en", cache=first["pamiec"])
    assert seen == ["Dwa smażenia w 140 i 190 stopniach."]                         # tylko zmieniony tekst
    assert second["dane"]["teza"] == "EN: Dwa smażenia w 140 i 190 stopniach."
    assert second["dane"]["tytul"] == "EN: Idealne frytki" and second["z_pamieci"] > 5
    r["tlumaczenie_calosci"]["en"] = second
    assert is_current(r, "en")
    legacy = {"tlumaczenie_calosci": {"en": {"dane": {}}}, **{k: v for k, v in r.items() if k != "tlumaczenie_calosci"}}
    assert is_current(legacy, "en")                                                  # sprzed 0.11 (bez odcisku)
