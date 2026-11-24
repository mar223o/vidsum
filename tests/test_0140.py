"""0.14.0: tryb „Konwersja” (link albo plik → MP4 / MP3) i powiadomienie o nowej wersji na stronie głównej."""
from __future__ import annotations

import http.server
import json
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from vidsum import convert as cv

ROOT = Path(__file__).resolve().parent.parent
from test_vidsum import FILM  # noqa: E402


# ---------------------------------------------------------------- konwersja: pliki

def test_safe_name_and_unique(tmp_path):
    assert cv.safe_name('AC/DC: "Back in Black" <Live>?') == "AC DC Back in Black Live"
    assert cv.safe_name("  ...  ") == "plik" and cv.safe_name("CON") == "_CON"
    assert len(cv.safe_name("x" * 400)) == 120
    (tmp_path / "a.mp3").write_bytes(b"1")
    assert cv.unique(tmp_path / "a.mp3").name == "a (2).mp3"


def test_file_to_mp3_and_mp4(tmp_path):
    ev = []
    mp3 = cv.convert(str(FILM), "mp3", tmp_path, log=lambda m: None, progress=lambda s, f: ev.append((s, f)))
    st = cv.streams(mp3)
    assert mp3.name == "przepis żółć test.mp3" and st["video"] is None and st["audio"] == "mp3"
    assert st["tags"].get("title") == "przepis żółć test"
    assert abs(st["duration"] - cv.streams(FILM)["duration"]) < 1.0
    assert ev[-1] == ("konwersja", 1.0) and all(0 <= f <= 1 for _, f in ev)
    mp4 = cv.convert(str(FILM), "mp4", tmp_path, log=lambda m: None)      # H.264 + AAC → bez przekodowania
    st = cv.streams(mp4)
    assert mp4.suffix == ".mp4" and st["video"] == "h264" and st["audio"] == "aac"
    again = cv.convert(str(FILM), "mp3", tmp_path, log=lambda m: None)    # nic nie nadpisuje
    assert again.name == "przepis żółć test (2).mp3"
    assert not list(tmp_path.glob(".vidsumly_tmp_*")) and not list(tmp_path.glob("*.part.*"))


@pytest.mark.skipif("libvpx-vp9" not in cv.encoders(), reason="ten ffmpeg nie ma kodera VP9 do przygotowania próbki")
def test_vp9_opus_becomes_h264_aac(tmp_path):
    src = tmp_path / "klip.webm"
    subprocess.run([cv.find_tool("ffmpeg"), "-v", "error", "-y", "-i", str(FILM), "-t", "5", "-c:v", "libvpx-vp9",
                    "-b:v", "400k", "-deadline", "realtime", "-c:a", "libopus", str(src)], check=True)
    out = cv.convert(str(src), "mp4", tmp_path / "out", log=lambda m: None)
    st = cv.streams(out)
    assert st["video"] == "h264" and st["audio"] == "aac"


def test_mp4_plans_fall_back_and_errors():
    plans = cv.mp4_plans({"video": "vp9", "audio": "opus"}, {"h264_mf", "h264_nvenc"})
    assert [p[1].split("(")[-1] for p in plans][:2] == ["h264_mf)", "h264_nvenc)"]
    assert "bez przekodowania" in plans[-1][1]                       # na końcu: VP9 w MP4 bez przekodowania
    assert "-c:a" in plans[0][0] and "aac" in plans[0][0]
    with pytest.raises(cv.ConvertError, match="MP3"):
        cv.mp4_plans({"video": None, "audio": "mp3"}, {"libx264"})
    with pytest.raises(cv.ConvertError):
        cv.mp4_plans({"video": "mpeg2video", "audio": "mp2"}, set())
    with pytest.raises(cv.ConvertError, match="MP3"):
        cv.mp3_args({"video": "h264", "audio": "aac"}, set(), "t", None)


def test_audio_only_file_to_mp4_is_refused(tmp_path):
    mp3 = cv.convert(str(FILM), "mp3", tmp_path, log=lambda m: None)
    with pytest.raises(cv.ConvertError, match="nie ma obrazu"):
        cv.convert(str(mp3), "mp4", tmp_path, log=lambda m: None)
    assert not list(tmp_path.glob("*.mp4"))


def test_failed_encoder_tries_next(tmp_path, monkeypatch):
    """Koder obecny w ffmpeg, ale niedziałający na tym komputerze → następny sposób."""
    calls = []
    real = cv.ffmpeg

    def fake(src, dst, args, duration, on_frac=None):
        enc = args[args.index("-c:v") + 1]
        calls.append(enc)
        if enc == "libx264":
            raise cv.ConvertError("ffmpeg: udawany błąd kodera")
        args = [a for a in args if a not in ("-cq", "21", "-b:v", "0")]   # na tym komputerze nie ma NVENC —
        args[args.index("-c:v") + 1] = "libx264"                          # „drugi koder” liczy libx264
        return real(src, dst, args, duration, on_frac)
    monkeypatch.setattr(cv, "ffmpeg", fake)
    monkeypatch.setattr(cv, "streams", lambda p: {"video": "vp9", "audio": "aac", "duration": 30.0, "tags": {}})
    monkeypatch.setattr(cv, "encoders", lambda: {"h264_nvenc", "libx264", "libmp3lame"})
    log = []
    out = cv.convert(str(FILM), "mp4", tmp_path, log=log.append)
    assert calls == ["libx264", "h264_nvenc"] and out.is_file()
    assert any("próbuję inaczej" in m for m in log)


# ---------------------------------------------------------------- konwersja: link (yt-dlp, serwer lokalny)

@pytest.fixture()
def media_server(tmp_path):
    d = tmp_path / "www"
    d.mkdir()
    shutil.copy(FILM, d / "klip.mp4")

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(d), **kw)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/klip.mp4"
    srv.shutdown()


@pytest.mark.parametrize("fmt", ["mp3", "mp4"])
def test_link_download_and_convert(media_server, tmp_path, fmt):
    ev = []
    out = cv.convert(media_server, fmt, tmp_path / "out", log=lambda m: None, progress=lambda s, f: ev.append(s))
    st = cv.streams(out)
    assert out.suffix == f".{fmt}" and st["audio"] in ("mp3", "aac")
    assert (st["video"] == "h264") == (fmt == "mp4")
    assert ev[0] == "pobieranie" and ev[-1] == "konwersja"
    assert [p.name for p in (tmp_path / "out").iterdir()] == [out.name]  # bez plików tymczasowych


# ---------------------------------------------------------------- konwersja w kolejce programu

def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")
    from vidsum.gui import App
    res = tmp_path / "wyniki"
    res.mkdir()
    return App(res, "tok")


def _serve(app):
    from http.server import ThreadingHTTPServer
    from vidsum.gui import make_handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _call(base, path, body=None, headers=None, data=None):
    h = {"X-Token": "tok", **(headers or {})}
    if body is not None:
        data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
    req = urllib.request.Request(base + path, data=data, method="POST" if data is not None else "GET", headers=h)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _wait(app, jid, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = app.worker.jobs.get(jid)
        if j and j.status in ("gotowe", "blad"):
            return j
        time.sleep(0.2)
    raise AssertionError("konwersja się nie skończyła")


def test_upload_converts_in_queue_and_stays_out_of_library(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    srv, base = _serve(app)
    try:
        code, d = _call(base, "/api/wyslij", data=FILM.read_bytes(),
                        headers={"X-Filename": "film%20%C5%BC%C3%B3%C5%82%C4%87.mp4", "X-Convert": "mp3"})
        assert code == 200 and d["konwersja"]["format"] == "mp3"
        j = _wait(app, d["id"])
        assert j.status == "gotowe", j.error
        assert j.out.parent == tmp_path / "wyniki" / "Konwersje" and j.out.suffix == ".mp3"
        assert not j.upload.parent.exists()                            # wysłana kopia usunięta
        dd = j.to_dict()
        assert dd["konwersja"]["plik"] == j.out.name and dd["card"] == {} and dd["postep"] is None
        assert app.settings["format_konwersji"] == "mp3"                # wybór zapamiętany
        assert not (tmp_path / "wyniki" / "Konwersje" / "analiza.json").exists()
        app.scan_library()
        assert all(x.conv or (x.out and (x.out / "analiza.json").is_file()) for x in app.worker.jobs.values())
        assert _call(base, "/api/wyslij", data=b"x", headers={"X-Filename": "a.mp4", "X-Convert": "wav"})[0] == 400
    finally:
        srv.shutdown()


def test_link_conversion_and_duplicates(tmp_path, monkeypatch, media_server):
    app = _app(tmp_path, monkeypatch)
    app.worker.set_paused(True)                                          # nic nie rusza — sprawdzamy kolejkę
    srv, base = _serve(app)
    try:
        _, a = _call(base, "/api/link", {"zrodlo": media_server, "konwersja": "mp4"})
        _, b = _call(base, "/api/link", {"zrodlo": media_server, "konwersja": "mp4"})
        _, c = _call(base, "/api/link", {"zrodlo": media_server, "konwersja": "mp3"})
        assert b["duplikat"] and b["id"] == a["id"] and not c["duplikat"] and c["id"] != a["id"]
        saved = json.loads((tmp_path / "appdata" / "Vidsumly" / "kolejka.json").read_text(encoding="utf-8"))
        assert [z["konwersja"]["format"] for z in saved["zadania"]] == ["mp4", "mp3"]
        app.worker.set_paused(False)
        ja, jc = _wait(app, a["id"]), _wait(app, c["id"])
        assert ja.status == jc.status == "gotowe" and ja.out.suffix == ".mp4" and jc.out.suffix == ".mp3"
    finally:
        srv.shutdown()


def test_conversion_progress_shape(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    j = app.conv_job("https://example.com/v", "https://example.com/v", "mp3")
    j.status, j.started = "trwa", time.time() - 10
    j.conv_state = {"etap": "pobieranie", "frac": 0.5}
    p = j.to_dict()["postep"]
    assert p["kroki"] == ["pobieranie", "konwersja"] and p["teraz"] == "pobieranie" and p["proc"] == 35
    assert p["zostalo_s"] == pytest.approx(10 * 0.65 / 0.35, rel=0.05)
    j.conv_state = {"etap": "konwersja", "frac": 0.5}
    assert j.to_dict()["postep"]["proc"] == 85 and j.to_dict()["postep"]["nr"] == 2
    f = app.conv_job(str(FILM), "f.mp4", "mp4")
    f.status, f.started = "trwa", time.time()
    assert f.to_dict()["postep"]["kroki"] == ["konwersja"]
    app.save_settings({"folder_konwersji": str(tmp_path / "moje")})
    assert app.conv_job(str(FILM), "f", "mp4").conv["folder"] == str(tmp_path / "moje")


# ---------------------------------------------------------------- powiadomienie o aktualizacji

def test_update_check_auto_is_cached_and_can_be_disabled(tmp_path, monkeypatch):
    from vidsum import update
    app = _app(tmp_path, monkeypatch)
    calls = []

    def fake_check(token=None):
        calls.append(1)
        return {"aktualna": "0.14.0", "najnowsza": "0.14.1", "jest_nowsza": True, "rodzaj": "kod", "_assets": {}}
    monkeypatch.setattr(update, "check", fake_check)
    srv, base = _serve(app)
    try:
        assert _call(base, "/api/aktualizacja?auto=1")[1]["najnowsza"] == "0.14.1"
        assert _call(base, "/api/aktualizacja?auto=1")[1]["jest_nowsza"] and len(calls) == 1      # pamiętane 6 h
        assert "_assets" not in _call(base, "/api/aktualizacja?auto=1")[1]
        _call(base, "/api/aktualizacja")                                                          # ręcznie — zawsze świeże
        assert len(calls) == 2
        app.save_settings({"sprawdzaj_aktualizacje": False})
        assert _call(base, "/api/aktualizacja?auto=1")[1] == {"wylaczone": True}

        def boom(token=None):
            raise OSError("brak sieci")
        monkeypatch.setattr(update, "check", boom)
        app.save_settings({"sprawdzaj_aktualizacje": True})
        app.update_at = 0
        code, d = _call(base, "/api/aktualizacja?auto=1")
        assert code == 200 and "brak sieci" in d["error"]                                         # bez sieci: po cichu
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- przeglądarka

@pytest.fixture()
def ui(tmp_path, monkeypatch):
    pytest.importorskip("playwright.sync_api")
    app = _app(tmp_path, monkeypatch)
    app.update_info = {"aktualna": "0.14.0", "najnowsza": "0.14.1", "jest_nowsza": True, "rodzaj": "kod",
                       "rozmiar_mb": 3.1, "strona": "https://github.com/mar223o/vidsum/releases"}
    app.update_at = time.time()
    srv, base = _serve(app)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 900})
        yield base, app, pg
        b.close()
    srv.shutdown()


def test_ui_update_banner_and_later(ui):
    base, app, pg = ui
    pg.goto(base + "/?t=tok#/")
    pg.wait_for_selector(".updbar")
    txt = pg.locator(".updbar").inner_text()
    assert "0.14.1" in txt and "masz 0.14.0" in txt and "Zaktualizuj teraz" in txt
    pg.click("#updLater")
    assert pg.locator(".updbar").count() == 0
    pg.reload()
    pg.wait_for_selector("#drop")
    pg.wait_for_timeout(500)
    assert pg.locator(".updbar").count() == 0                                # „Później” = do następnej wersji
    pg.evaluate("localStorage.setItem('vs_upd_skip', '0.14.0')")
    pg.reload()
    pg.wait_for_selector(".updbar")


def test_ui_conversion_mode(ui, tmp_path):
    base, app, pg = ui
    pg.goto(base + "/?t=tok#/")
    pg.wait_for_selector("#appmode")
    assert pg.is_visible("#amoderow") and not pg.is_visible("#cfmtrow")
    pg.click("#appmode [data-app=konwersja]")
    assert pg.is_visible("#cfmtrow") and not pg.is_visible("#amoderow") and not pg.is_visible("#pvrow")
    assert pg.inner_text("#go") == "Konwertuj" and "Konwersje" in pg.inner_text("#convdir")
    pg.click("#cfmt [data-fmt=mp3]")
    assert "MP3" in pg.inner_text("#cfmthint")
    pg.wait_for_timeout(300)
    assert app.settings["tryb_aplikacji"] == "konwersja" and app.settings["format_konwersji"] == "mp3"
    pg.set_input_files("#pick", str(FILM))
    pg.wait_for_selector("#queue .qi.gotowe", timeout=60000)
    row = pg.locator("#queue .qi.gotowe").inner_text()
    assert "MP3" in row and "przepis żółć test.mp3" in row and "Pokaż w folderze" in row
    assert pg.url.endswith("#/")                                             # konwersja nie otwiera strony wyniku
    assert (tmp_path / "wyniki" / "Konwersje" / "przepis żółć test.mp3").is_file()
    pg.goto(base + "/?t=tok#/biblioteka")
    pg.reload()
    pg.wait_for_selector(".empty")                                           # konwersja nie trafia do Biblioteki
    pg.goto(base + "/?t=tok#/")
    pg.reload()
    pg.wait_for_selector("#appmode")
    assert pg.is_visible("#cfmtrow")                                         # tryb zapamiętany
