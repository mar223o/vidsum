"""0.13.2: postęp na żywo (etapy według trybu, %, ile zostało), czyszczenie biblioteki do Kosza, paleta i logo."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from vidsum import eta
from vidsum.progress import DEFAULT_SHARES, Tracker, step_times, steps_for

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "vidsum" / "web" / "index.html"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# ---------------------------------------------------------------- etapy według trybu

def test_steps_depend_on_mode():
    assert steps_for("pelna") == ["start", "mowa", "kadry", "obraz", "streszczenie"]
    assert steps_for("szybki") == ["start", "mowa", "streszczenie", "obraz"]
    assert steps_for("mowa") == ["start", "mowa", "streszczenie"]
    assert steps_for("transkrypcja") == ["start", "mowa", "tlumaczenie"]
    assert steps_for("transkrypcja", translate=False) == ["start", "mowa"]
    assert steps_for("pelna", summary=False, vision=False) == ["start", "mowa", "kadry"]
    for m, sh in DEFAULT_SHARES.items():
        assert abs(sum(sh.values()) - 1.0) < 1e-6, m


@pytest.mark.parametrize("mode", ["mowa", "transkrypcja"])
def test_speech_modes_never_show_frames(mode):
    """Prośba użytkownika: w „Tylko mowa” i „Sama transkrypcja” nie ma etapu kadrów — linia [2/4] (miniatury) nic
    nie zmienia w postępie."""
    c = Clock()
    tr = Tracker(mode, clock=c)
    for line in ["▶ film.mp4", "  tryb: Sama transkrypcja" if mode == "transkrypcja" else "  tryb: Tylko mowa",
                 "  tryb: Tylko mowa", "  [1/4] transkrypcja (Whisper large-v3-turbo, cuda)…",
                 "  [2/4] wykrywanie zmian scen i wybór kadrów…", "        6 miniatur (bez analizy scen)"]:
        tr.feed(line)
    d = tr.to_dict(100.0)
    assert d["tryb"] == mode and d["teraz"] == "mowa"
    assert "kadry" not in d["kroki"] and "obraz" not in d["kroki"]
    assert d["nr"] == 2 and d["z"] == len(d["kroki"])


def test_full_mode_progress_and_frames_count():
    c = Clock()
    tr = Tracker("pelna", clock=c)
    seen = []
    lines = ["▶ x", "  [1/4] mowa: napisy serwisu", "  [2/4] wykrywanie zmian scen i wybór kadrów…",
             "  [0/4] napisy na ekranie (OCR) — w tle", "  [3/4] opis kadrów (qwen3-vl:4b-instruct)…",
             "        1/4 kadr 00:01: kuchnia", "  [1/4] dokładna transkrypcja Whisperem (GPU)",   # równolegle — wstecz
             "        2/4 kadr 00:05: x", "        4/4 kadr 00:09: y", "  [4/4] streszczenie (ollama:gemma3:4b)…"]
    for line in lines:
        c.t += 3
        tr.feed(line)
        seen.append((tr.step, tr.percent(60.0)))
    assert [s for s, _ in seen][-1] == "streszczenie"
    assert ("obraz" in [s for s, _ in seen]) and tr.idx == 4
    pcts = [p for _, p in seen]
    assert pcts == sorted(pcts), "procent nie cofa się"
    # w opisie kadrów procent rośnie z liczbą kadrów: 2/4 → połowa udziału etapu
    tr2 = Tracker("pelna", clock=c)
    for line in lines[:6]:
        tr2.feed(line)
    tr2.feed("        2/4 kadr 00:05: x")
    sh = tr2.shares
    assert tr2.percent(60.0) == pytest.approx(sh["start"] + sh["mowa"] + sh["kadry"] + sh["obraz"] * 0.5)
    assert tr2.to_dict(60.0)["szczegol"] == [2, 4]
    tr2.feed("  ✔ gotowe w 1:02")
    assert tr2.to_dict(60.0)["proc"] == 100 and tr2.to_dict(60.0)["zostalo_s"] == 0.0


def test_fast_mode_order_summary_then_picture():
    tr = Tracker("szybki", clock=Clock())
    for line in ["  tryb: Mowa + szybki obraz", "  [1/4] transkrypcja…", "  [2/4] wykrywanie…", "  [4/4] streszczenie…"]:
        tr.feed(line)
    assert tr.step == "streszczenie"
    tr.feed("  [3/4] szybki obraz: 8 kadrów (3 wskazanych mową, 2 początków rozdziałów)")
    assert tr.step == "obraz"
    tr.feed("        3/8 kadr 01:10: wykres")
    assert tr.to_dict(100.0)["szczegol"] == [3, 8]


def test_audio_file_switches_full_to_speech():
    """Plik mp3 w trybie „Pełna” liczy się jako „Tylko mowa” (pipeline loguje „tryb: Tylko mowa”)."""
    tr = Tracker("pelna", clock=Clock())
    tr.feed("  tryb: Tylko mowa")
    assert tr.mode == "mowa" and tr.steps == steps_for("mowa")


def test_remaining_is_a_number_and_blends_forecast_with_pace():
    c = Clock()
    tr = Tracker("mowa", clock=c)
    assert tr.remaining(None) is None                      # nic jeszcze nie wiadomo
    assert tr.remaining(120.0) == pytest.approx(120.0)     # sama prognoza
    c.t += 10
    tr.feed("  [1/4] transkrypcja…")
    c.t += 30
    left = tr.remaining(120.0)
    assert 0 < left < 120 - 40 + 30                         # liczba sekund, nie „ok.”
    # analiza idzie 2× wolniej niż prognoza → po połowie zostało ~tyle, ile minęło, a nie prognoza
    c2 = Clock()
    slow = Tracker("transkrypcja", translate=False, clock=c2)
    slow.feed("  [1/4] transkrypcja…")
    slow.detail = None
    c2.t += 200
    slow.shares = {"start": 0.0, "mowa": 1.0}
    slow.step_start = c2.t - 200
    p = slow.percent(100.0)
    assert p == pytest.approx(0.95)
    assert slow.remaining(100.0) == pytest.approx(200 * 0.05 / 0.95, rel=1e-3)


# ---------------------------------------------------------------- nauka udziałów etapów

def test_step_times_from_trail_and_shares_roundtrip(tmp_path):
    trail = ["[   0.0 s] ▶ film.mp4\n  wyniki: x", "[   0.4 s]   tryb: Tylko mowa", "[   2.0 s]   [1/4] transkrypcja…",
             "[   3.0 s]   [2/4] wykrywanie zmian scen i wybór kadrów…", "[  32.0 s]   [4/4] streszczenie (gemma)…",
             "[  62.0 s] ✔ gotowe"]
    st = step_times(trail, "mowa")
    assert st == {"start": 2.0, "mowa": 30.0, "streszczenie": 30.0}
    eta.record(tmp_path, "mowa", 300, 62, "0.13.2", st)
    eta.record(tmp_path, "mowa", 300, 62, "0.13.2", {"start": 2.0, "mowa": 50.0, "streszczenie": 10.0})
    sh = eta.shares(tmp_path, "mowa")
    assert sh["mowa"] == pytest.approx((30 / 62 + 50 / 62) / 2)
    assert eta.shares(tmp_path, "pelna") is None
    row = json.loads((tmp_path / eta.FILE).read_text(encoding="utf-8"))[0]
    assert row["etapy"] == st and eta.predict(tmp_path, "mowa", 300)["z_pomiarow"] == 2


def test_pipeline_records_step_times_and_progress_reaches_100(tmp_path, monkeypatch):
    """Prawdziwy przebieg analizy (film testowy, modele udawane): postęp z logu idzie tylko do przodu, kończy na 100%,
    a historia czasów dostaje czasy etapów."""
    import http.server
    import threading as th
    from test_vidsum import FILM, FakeOllama
    from vidsum.pipeline import Options, analyze
    subs = tmp_path / "napisy.json"
    subs.write_text(json.dumps({"language": "pl", "segments": [
        {"start": 0.5, "end": 6.0, "text": "Najpierw kroimy jedną cebulę w drobną kostkę."},
        {"start": 8.5, "end": 14.0, "text": "Teraz wlewamy dwieście mililitrów mleka."}]}), encoding="utf-8")
    FakeOllama.calls, FakeOllama.fail_images = [], set()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    th.Thread(target=srv.serve_forever, daemon=True).start()
    tr = Tracker("mowa")
    pcts = []

    def log(msg):
        for line in str(msg).splitlines():
            tr.feed(line)
            pcts.append(tr.percent(30.0))
    try:
        opt = Options(out_root=tmp_path / "w", transcript_file=subs, ollama_host=f"http://127.0.0.1:{srv.server_address[1]}",
                      vision_model="fake-vl", text_model="fake-txt", mode="mowa", translate=[])
        analyze(str(FILM), opt, log=log)
    finally:
        srv.shutdown()
    assert pcts == sorted(pcts) and pcts[-1] == 1.0 and tr.done
    rows = json.loads((tmp_path / "w" / eta.FILE).read_text(encoding="utf-8"))
    assert rows[-1]["tryb"] == "mowa" and set(rows[-1]["etapy"]) <= {"start", "mowa", "streszczenie"}
    assert "streszczenie" in rows[-1]["etapy"]
    assert sum(rows[-1]["etapy"].values()) == pytest.approx(rows[-1]["razem_s"], abs=1.5)


# ---------------------------------------------------------------- serwer: postęp w zadaniu, czyszczenie biblioteki

def _app(tmp_path, monkeypatch, n=3):
    from vidsum import trash
    monkeypatch.setattr(trash, "_has_recycle_bin", lambda p: False)   # testy: zawsze kosz Vidsumly (Kosz systemu —
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))    # tests/win_trash_check.py w CI na Windows)
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")
    from vidsum.gui import App
    res = tmp_path / "wyniki"
    for i in range(n):
        d = res / f"film_{i}"
        d.mkdir(parents=True)
        (d / "analiza.json").write_text(json.dumps({"zrodlo": {"tytul": f"Film {i}"}, "czasy": {"razem_s": 10}}),
                                        encoding="utf-8")
    return App(res, "tok"), res


def test_job_dict_has_progress_while_running(tmp_path, monkeypatch):
    from vidsum.gui import Job
    from vidsum.pipeline import Options
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    job = Job("abcd0001", "x.mp4", "x.mp4", Options(out_root=tmp_path, mode="transkrypcja"), None)
    job.status, job.started = "trwa", time.time()
    job.start_tracking()
    for line in ["▶ x.mp4", "  tryb: Sama transkrypcja", "  tryb: Tylko mowa", "  [1/4] transkrypcja…",
                 "  [2/4] wykrywanie zmian scen i wybór kadrów…"]:
        job.feed(line)
    job.partial["meta"] = {"dlugosc_s": 120.0}
    d = job.to_dict()["postep"]
    assert d["tryb"] == "transkrypcja" and d["teraz"] == "mowa" and d["kroki"] == ["start", "mowa", "tlumaczenie"]
    assert isinstance(d["proc"], int) and 0 < d["proc"] < 100 and d["zostalo_s"] > 0
    job.status = "gotowe"
    assert job.to_dict()["postep"] is None


def test_clear_library_moves_to_trash_and_keeps_selected(tmp_path, monkeypatch):
    app, res = _app(tmp_path, monkeypatch)
    ids = {j.out.name: j.id for j in app.worker.jobs.values()}
    r = app.clear_library([ids["film_0"], ids["film_2"]])
    assert sorted(r["usuniete"]) == sorted([ids["film_0"], ids["film_2"]]) and not r["bledy"]
    assert r["gdzie"] == ["kosz_vidsumly"]                     # Linux: kosz Vidsumly (Windows: Kosz systemu)
    assert not (res / "film_0").exists() and not (res / "film_2").exists() and (res / "film_1").exists()
    kosz = tmp_path / "appdata" / "Vidsumly" / "kosz"
    assert sorted(re.sub(r"_\d{8}-\d{6}(_\d+)?$", "", p.name) for p in kosz.iterdir()) == ["film_0", "film_2"]
    assert all((p / "analiza.json").is_file() for p in kosz.iterdir())   # nic nie zginęło
    assert set(j.out.name for j in app.worker.jobs.values()) == {"film_1"}
    app.scan_library()                                            # po ponownym skanowaniu też ich nie ma
    assert set(j.out.name for j in app.worker.jobs.values()) == {"film_1"}


def test_clear_library_refuses_running_unknown_and_outside(tmp_path, monkeypatch):
    from vidsum.gui import Job
    from vidsum.pipeline import Options
    app, res = _app(tmp_path, monkeypatch, n=1)
    outside = tmp_path / "gdzies_indziej" / "film_x"
    outside.mkdir(parents=True)
    (outside / "analiza.json").write_text("{}", encoding="utf-8")
    j = Job("out00001", str(outside), "x", Options(), None)
    j.status, j.out = "gotowe", outside
    run = Job("run00001", "y", "y", Options(), None)
    run.status, run.out = "trwa", res / "film_0"
    app.worker.jobs.update({j.id: j, run.id: run})
    r = app.clear_library(["out00001", "run00001", "nieznane"])
    assert r["usuniete"] == [] and len(r["bledy"]) == 3
    assert outside.exists() and (res / "film_0").exists()


def test_clear_library_endpoint_needs_confirmation(tmp_path, monkeypatch):
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from vidsum.gui import make_handler
    app, res = _app(tmp_path, monkeypatch, n=2)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def post(body):
        req = urllib.request.Request(base + "/api/biblioteka/wyczysc?t=tok", data=json.dumps(body).encode(),
                                     method="POST", headers={"Content-Type": "application/json", "X-Token": "tok"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    try:
        jid = next(iter(app.worker.jobs))
        assert post({"usun": [jid]})[0] == 400                    # bez potwierdzenia nic się nie dzieje
        assert len(list(res.iterdir())) == 2
        code, r = post({"usun": [jid], "potwierdz": True})
        assert code == 200 and r["usuniete"] == [jid] and len(list(res.iterdir())) == 1
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- interfejs: paleta, teksty

def test_palette_from_user_in_both_themes():
    html = HTML.read_text(encoding="utf-8")
    root = html[html.index(":root{"):html.index('@media (prefers-color-scheme: light)')]
    for c in ("#38BDF8", "#C4B5FD", "#F5EFE6", "#000000"):
        assert c in root, c
    light = html[html.index(':root[data-theme="light"]{'):html.index("@media (prefers-color-scheme: light)")]
    assert "--bg:#F5EFE6" in light and "--ink:#0A0A0A" in light
    assert "rgba(61,123,255" not in html and "#3d7bff" not in html          # stary lazur zniknął
    for k in ("ps_start", "pn_obraz", "p_left", "lib_clear", "lib_sure", "live_no_sum"):
        assert html.count(f"{k}:") == 2, k                                    # PL i EN
    assert "zostało ok." not in re.sub(r"eta_left:[^,]+,", "", html)


def test_wrapper_trash_module_on_linux(tmp_path, monkeypatch):
    from vidsum import trash
    monkeypatch.setattr(trash, "_has_recycle_bin", lambda p: False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    d = tmp_path / "a b ąę"
    d.mkdir()
    (d / "plik.txt").write_text("x", encoding="utf-8")
    assert trash.to_trash(d) == "kosz_vidsumly" and not d.exists()
    with pytest.raises(FileNotFoundError):
        trash.to_trash(d)


# ---------------------------------------------------------------- przeglądarka (Playwright)

@pytest.fixture()
def ui(tmp_path, monkeypatch):
    pytest.importorskip("playwright.sync_api")
    import threading
    from http.server import ThreadingHTTPServer
    from vidsum.gui import Job, make_handler
    from vidsum.pipeline import Options
    app, res = _app(tmp_path, monkeypatch, n=3)
    jobs = {}
    for mode in ("pelna", "transkrypcja"):
        j = Job(f"live{mode[:4]}", "https://example.com/" + mode, "https://example.com/" + mode,
                Options(out_root=tmp_path, mode=mode), None)
        j.status, j.started = "trwa", time.time() - 40
        j.start_tracking()
        j.tracker.started = j.started
        for line in ["▶ x", "  [1/4] transkrypcja (Whisper)…", "  [2/4] wykrywanie zmian scen i wybór kadrów…",
                     "  [3/4] opis kadrów (qwen3-vl)…", "        5/20 kadr 00:41: kuchnia"]:
            j.feed(line)
        j.partial["meta"] = {"tytul": "Film " + mode, "dlugosc_s": 200.0}
        app.worker.jobs[j.id] = j
        jobs[mode] = j
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 900})
        yield f"http://127.0.0.1:{srv.server_address[1]}", app, res, jobs, pg
        b.close()
    srv.shutdown()


def test_ui_live_progress_per_mode(ui):
    base, app, res, jobs, pg = ui
    pg.goto(base + "/?t=tok#/wynik/livepeln")
    pg.wait_for_selector(".prog.full")
    steps = pg.locator(".psteps li").all_inner_texts()
    assert steps == ["Przygotowanie", "Mowa", "Kadry", "Opis obrazu", "Streszczenie"]
    assert pg.locator(".psteps li.now").inner_text() == "Opis obrazu"
    assert "5 z 20 kadrów" in pg.locator(".pnow").inner_text()
    pct = int(pg.locator(".ppct").inner_text().rstrip("%"))
    assert 0 < pct < 100 and pg.locator(".pgbar").get_attribute("aria-valuenow") == str(pct)
    left = pg.locator(".pleft").inner_text()
    assert re.fullmatch(r"zostało \d+:\d\d", left), left
    pg.wait_for_timeout(2200)                                     # licznik odlicza co sekundę
    assert pg.locator(".pleft").inner_text() != left or "jeszcze" in left
    # „Sama transkrypcja”: bez kadrów i obrazu, nawet gdy w logu była linia [2/4] i [3/4]
    pg.goto(base + "/?t=tok#/wynik/livetran")
    pg.reload()
    pg.wait_for_selector(".prog.full")
    steps = pg.locator(".psteps li").all_inner_texts()
    assert steps == ["Przygotowanie", "Mowa", "Tłumaczenie"]
    assert pg.locator(".psteps li.now").inner_text() == "Mowa"
    assert "W trybie „Sama transkrypcja” nie ma streszczenia" in pg.locator("body").inner_text()
    # kolejka na stronie głównej: pasek i procent, bez starego „Etap 2/4 · kadry”
    pg.goto(base + "/?t=tok#/")
    pg.reload()
    pg.wait_for_selector("#queue .prog")
    assert pg.locator("#queue .prog").count() == 2
    row = pg.locator("#queue .qi", has_text="example.com/transkrypcja").inner_text().lower()
    assert "rozpoznaję mowę" in row and "kadr" not in row and "etap 2/4" not in row


def test_ui_clear_library_keeps_marked(ui):
    base, app, res, jobs, pg = ui
    pg.goto(base + "/?t=tok#/biblioteka")
    pg.reload()
    pg.wait_for_selector(".vcard")
    assert pg.locator(".vcard").count() == 3
    pg.click("#libclear")
    keep_title = pg.locator(".vcard h3").nth(1).inner_text()
    pg.locator(".vcard").nth(1).click()                          # zaznacz: zostaje
    assert pg.locator(".vcard.kept").count() == 1 and pg.url.endswith("#/biblioteka")
    assert "Zostaje: 1" in pg.locator(".selbar").inner_text() and "Do Kosza: 2" in pg.locator(".selbar").inner_text()
    pg.click("[data-sel=go]")                                     # pierwsze kliknięcie — tylko pytanie
    assert "Na pewno?" in pg.locator("[data-sel=go]").inner_text() and len(list(res.iterdir())) == 3
    pg.click("[data-sel=go]")
    pg.wait_for_function("document.querySelectorAll('.vcard').length === 1")
    assert pg.locator(".vcard h3").inner_text() == keep_title
    assert len(list(res.iterdir())) == 1 and not pg.locator(".selbar").count()


def test_ci_checks_recycle_bin_on_windows():
    wf = (ROOT / ".github/workflows/windows.yml").read_text(encoding="utf-8")
    assert "tests\\win_trash_check.py" in wf
