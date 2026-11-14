"""Testy serwera interfejsu (bez przeglądarki): API, token, wysyłanie pliku, wyniki, bezpieczeństwo ścieżek."""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"
TOKEN = "testtoken123"


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")   # Ollama "nieuruchomiona"
    from vidsum.gui import App, make_handler
    app = App(tmp_path / "wyniki", TOKEN)
    app.save_settings({"obraz": "brak", "streszczenie": "brak", "ocr": False})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", app
    srv.shutdown()


def req(base, path, data=None, headers=None, token=True, method=None):
    h = {"X-Token": TOKEN} if token else {}
    h.update(headers or {})
    r = urllib.request.Request(base + path, data=data, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=30) as resp:
        body = resp.read()
        return resp.status, (json.loads(body) if resp.headers.get_content_type() == "application/json" else body)


def wait_done(base, jid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        _, jobs = req(base, "/api/zadania")
        j = next(j for j in jobs if j["id"] == jid)
        if j["status"] in ("gotowe", "blad"):
            return j
        time.sleep(0.3)
    raise AssertionError("timeout")


def test_index_and_token(server):
    base, _ = server
    st, html = req(base, "/", token=False)
    assert st == 200 and b"Vidsumly" in html and b'lang="pl"' in html
    with pytest.raises(urllib.error.HTTPError) as e:
        req(base, "/api/status", token=False)
    assert e.value.code == 403
    with pytest.raises(urllib.error.HTTPError) as e:
        req(base, "/api/status", headers={"X-Token": "zly"}, token=False)
    assert e.value.code == 403


def test_status_reports_components(server):
    base, _ = server
    _, s = req(base, "/api/status")
    assert s["ffmpeg"] is True and s["ollama"] is False and "wersja" in s
    assert "Ollam" in s["ollama_info"]


def test_settings_roundtrip_and_whitelist(server, tmp_path):
    base, app = server
    _, s = req(base, "/api/ustawienia", data=json.dumps({"jezyk_ui": "en", "zlosliwe": 1}).encode(), method="POST")
    assert s["jezyk_ui"] == "en" and "zlosliwe" not in s
    saved = json.loads((tmp_path / "appdata" / "Vidsumly" / "ustawienia.json").read_text(encoding="utf-8"))
    assert saved["jezyk_ui"] == "en"


def test_quick_preview_is_automatic_without_switch(server):
    """0.11.0: wstępne streszczenie to stała część analizy z programu (zawsze włączone), a nie osobny tryb —
    stary przełącznik w ustawieniach niczego nie zmienia."""
    base, app = server
    assert app.options(app.settings).preview is True
    req(base, "/api/ustawienia", data=json.dumps({"podglad": False}).encode(), method="POST")
    assert app.options(app.settings).preview is True


def test_upload_polish_name_and_results(server):
    base, app = server
    data = (DATA / "bez_audio.mp4").read_bytes()
    name = "Mój film żółć.mp4"
    _, job = req(base, "/api/wyslij", data=data, method="POST",
                 headers={"X-Filename": urllib.parse.quote(name), "Content-Type": "application/octet-stream"})
    assert job["label"] == name
    j = wait_done(base, job["id"])
    assert j["status"] == "gotowe", j
    assert j["elapsed"] is not None and j["elapsed"] > 0                       # czas w interfejsie
    _, r = req(base, f"/api/zadania/{job['id']}/plik/analiza.json")
    assert r["zrodlo"]["plik"] == name and r["kadry"]
    st, img = req(base, f"/api/zadania/{job['id']}/plik/" + urllib.parse.quote(r["kadry"][0]["file"]))
    assert st == 200 and img[:2] == b"\xff\xd8"          # JPEG
    st, prompt = req(base, f"/api/zadania/{job['id']}/plik/prompt_dla_claude.md")
    assert "OŚ CZASU" in prompt.decode("utf-8")
    # przesłana kopia filmu jest sprzątana po analizie
    assert not any((Path(os.environ["LOCALAPPDATA"]) / "Vidsumly" / "wyslane").glob("*/*.mp4"))


def test_path_traversal_blocked(server):
    base, _ = server
    _, job = req(base, "/api/link", data=json.dumps({"zrodlo": str(DATA / "bez_audio.mp4")}).encode(), method="POST")
    assert wait_done(base, job["id"])["status"] == "gotowe"
    for evil in ("../../../../etc/passwd", "..%2F..%2F..%2Fetc%2Fpasswd", "kadry/../../x"):
        with pytest.raises(urllib.error.HTTPError) as e:
            req(base, f"/api/zadania/{job['id']}/plik/{evil}")
        assert e.value.code == 404


def test_bad_input_shows_error_not_crash(server):
    base, _ = server
    _, job = req(base, "/api/link", data=json.dumps({"zrodlo": "C:/nie/ma/takiego.mp4"}).encode(), method="POST")
    j = wait_done(base, job["id"])
    assert j["status"] == "blad" and "Nie ma takiego pliku" in j["error"]
    _, s = req(base, "/api/status")      # serwer dalej działa
    assert "wersja" in s


@pytest.mark.skipif(os.name == "nt", reason="atrapa claude jako skrypt POSIX")
def test_claude_button(server, tmp_path, monkeypatch):
    base, _ = server
    d = tmp_path / "bin"
    d.mkdir()
    fake = d / "claude"
    fake.write_text(f"#!{sys.executable}\nimport sys\nsys.stdin.read()\nprint('## Streszczenie\\nZ Claude')\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ["PATH"])
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _, job = req(base, "/api/link", data=json.dumps({"zrodlo": str(DATA / "bez_audio.mp4")}).encode(), method="POST")
    j = wait_done(base, job["id"])
    _, r = req(base, f"/api/zadania/{job['id']}/claude", method="POST", data=b"")
    assert "Z Claude" in r["markdown"]
    assert (Path(j["out"]) / "streszczenie_claude.md").is_file()


def test_video_streaming_with_range(server):
    base, _ = server
    data = (DATA / "bez_audio.mp4").read_bytes()
    _, job = req(base, "/api/wyslij", data=data, method="POST", headers={"X-Filename": "film.mp4"})
    assert wait_done(base, job["id"])["status"] == "gotowe"
    st, full = req(base, f"/api/zadania/{job['id']}/film")
    assert st == 200 and full == data                       # wysłany film zachowany do odtwarzacza
    r = urllib.request.Request(base + f"/api/zadania/{job['id']}/film", headers={"X-Token": TOKEN, "Range": "bytes=100-199"})
    with urllib.request.urlopen(r) as resp:
        assert resp.status == 206 and resp.headers["Content-Range"] == f"bytes 100-199/{len(data)}"
        assert resp.read() == data[100:200]


def test_library_survives_restart(server, tmp_path):
    base, app = server
    _, job = req(base, "/api/link", data=json.dumps({"zrodlo": str(DATA / "bez_audio.mp4")}).encode(), method="POST")
    assert wait_done(base, job["id"])["status"] == "gotowe"
    from vidsum.gui import App
    app2 = App(app.results, "x")                             # „ponowne uruchomienie”
    jobs = [j.to_dict() for j in app2.worker.jobs.values()]
    assert len(jobs) == 1 and jobs[0]["status"] == "gotowe"
    assert jobs[0]["card"]["tytul"] == "bez_audio.mp4" and jobs[0]["card"]["miniatura"].startswith("kadry/")


@pytest.mark.skipif(os.name == "nt", reason="atrapa claude jako skrypt POSIX")
def test_chat_with_video(server, tmp_path, monkeypatch):
    base, _ = server
    d = tmp_path / "bin"
    d.mkdir()
    fake = d / "claude"
    fake.write_text(f"#!{sys.executable}\nimport sys\np=sys.stdin.read()\n"
                    "assert 'QUESTION: Co jest w filmie?' in p and 'FRAMES' in p\nprint('Kolorowe paski `00:01`.')\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ["PATH"])
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _, job = req(base, "/api/link", data=json.dumps({"zrodlo": str(DATA / "bez_audio.mp4")}).encode(), method="POST")
    wait_done(base, job["id"])
    # domyślnie czat jest LOKALNY (samodzielna aplikacja) — Claude nie jest używany, nawet gdy jest zainstalowany;
    # tu Ollama „nie działa”, więc czytelny błąd zamiast cichego przejścia na Claude
    with pytest.raises(urllib.error.HTTPError) as e:
        req(base, f"/api/zadania/{job['id']}/pytanie", data=json.dumps({"pytanie": "Co jest w filmie?"}).encode(),
            method="POST")
    assert "Ollam" in json.loads(e.value.read())["error"]
    # Claude jako świadomie wybrany dodatek
    req(base, "/api/ustawienia", data=json.dumps({"streszczenie": "claude"}).encode(), method="POST")
    _, r = req(base, f"/api/zadania/{job['id']}/pytanie", data=json.dumps({"pytanie": "Co jest w filmie?"}).encode(),
               method="POST")
    assert "Kolorowe paski" in r["odpowiedz"] and len(r["historia"]) == 2
    _, hist = req(base, f"/api/zadania/{job['id']}/czat")
    assert hist[0]["rola"] == "user" and hist[1]["silnik"] == "claude-code" and len(hist) == 2
    # 0.11.8: pytanie o chwilę („co robi w 0:01?”) — odpowiedź z transkrypcji, bez modelu (działa też bez Ollamy)
    req(base, "/api/ustawienia", data=json.dumps({"streszczenie": "auto"}).encode(), method="POST")
    import vidsum.summary as S
    monkeypatch.setattr(S, "answer_moment", lambda a, q: "W 00:01 słychać [mowa]: 00:01 „Test.”" if "0:01" in q else None)
    _, r = req(base, f"/api/zadania/{job['id']}/pytanie", data=json.dumps({"pytanie": "co robi w 0:01?"}).encode(),
               method="POST")
    assert r["odpowiedz"].startswith("W 00:01 słychać") and r["historia"][-1]["silnik"] == "transkrypcja"


def test_fixed_port_persistent_token_single_instance(tmp_path):
    """Stały adres + stały klucz: stara karta działa po restarcie; drugie uruchomienie nie tworzy drugiego serwera."""
    import socket
    import subprocess
    from vidsum import gui
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", gui.DEFAULT_PORT)) == 0:
            pytest.skip("port 8765 zajęty")
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path / "app"))
    cmd = [sys.executable, "-m", "vidsum", "--ui", "--bez-przegladarki", "-o", str(tmp_path / "w")]
    p1 = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                          cwd=Path(__file__).parent.parent)
    try:
        for _ in range(50):
            time.sleep(0.2)
            if gui._running_instance(gui.DEFAULT_PORT):
                break
        token = (tmp_path / "app" / "Vidsumly" / "token.txt").read_text().strip()
        base = f"http://127.0.0.1:{gui.DEFAULT_PORT}"
        st, s = req(base, "/api/status", headers={"X-Token": token}, token=False)
        assert st == 200 and "wersja" in s
        p2 = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
                            cwd=Path(__file__).parent.parent)
        assert "już działa" in p2.stdout and token in p2.stdout       # drugie uruchomienie → ten sam adres i klucz
    finally:
        p1.kill()
        p1.wait(timeout=10)


def test_partial_results_and_quit(server, monkeypatch):
    """Podgląd gotowych etapów w trakcie analizy + wyłączanie programu przyciskiem (działa bez okna)."""
    base, app = server
    import vidsum.gui as g
    gate = threading.Event()
    real = g.analyze

    def slow_analyze(src, opt, log):
        opt.on_partial("transkrypcja", {"jezyk": "pl", "segmenty": [{"start": 1.0, "end": 2.0, "text": "Cześć"}]})
        gate.wait(10)                                   # „opis obrazu” jeszcze trwa
        return real(src, opt, log)
    monkeypatch.setattr(g, "analyze", slow_analyze)
    _, job = req(base, "/api/link", data=json.dumps({"zrodlo": str(DATA / "bez_audio.mp4")}).encode(), method="POST")
    for _ in range(50):
        _, jobs = req(base, "/api/zadania")
        j = next(x for x in jobs if x["id"] == job["id"])
        if j["czesciowe"]:
            break
        time.sleep(0.1)
    assert j["status"] == "trwa" and j["czesciowe"] == ["transkrypcja"]
    _, part = req(base, f"/api/zadania/{job['id']}/czesciowe")
    assert part["transkrypcja"]["segmenty"][0]["text"] == "Cześć"
    gate.set()
    assert wait_done(base, job["id"])["czesciowe"] == []          # po zakończeniu — pełny wynik zamiast podglądu

    exits = []
    monkeypatch.setattr(g.os, "_exit", lambda code: exits.append(code))
    _, r = req(base, "/api/zakoncz", method="POST", data=b"")
    time.sleep(0.6)
    assert r["ok"] and exits == [0]
    with pytest.raises(urllib.error.HTTPError) as e:              # bez klucza nie da się wyłączyć
        req(base, "/api/zakoncz", method="POST", data=b"", token=False)
    assert e.value.code == 403


def test_windowless_start_logs_to_file(tmp_path):
    """Bez okna konsoli (pythonw / Vidsumly Start.exe) sys.stdout to None — komunikaty idą do vidsumly.log."""
    import subprocess
    code = ("import sys; sys.stdout = None; sys.stderr = None\n"
            "from vidsum.cli import main\n"
            "try:\n    main(['--version'])\nexcept SystemExit:\n    pass\n")
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path))
    subprocess.run([sys.executable, "-c", code], env=env, cwd=Path(__file__).parent.parent, timeout=60, check=True)
    assert "Vidsumly" in (tmp_path / "Vidsumly" / "vidsumly.log").read_text(encoding="utf-8")


def test_window_opens_as_edge_app_without_gpu(monkeypatch, tmp_path):
    import subprocess
    from vidsum import gui
    got = {}
    monkeypatch.setattr(gui, "_edge_exe", lambda: r"C:\Edge\msedge.exe")
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: got.update(args=args))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("VIDSUM_PRZEGLADARKA", raising=False)
    gui.open_window("http://127.0.0.1:8765/?t=x")
    a = got["args"]
    assert a[0] == r"C:\Edge\msedge.exe" and "--app=http://127.0.0.1:8765/?t=x" in a and "--disable-gpu" in a
    assert any(x.startswith("--user-data-dir=") and x.endswith("okno") for x in a)


def test_window_falls_back_to_default_browser(monkeypatch):
    from vidsum import gui
    opened = []
    monkeypatch.setattr(gui, "_edge_exe", lambda: None)
    monkeypatch.setattr(gui.webbrowser, "open", opened.append)
    gui.open_window("http://x")
    assert opened == ["http://x"]
    monkeypatch.setattr(gui, "_edge_exe", lambda: "edge")
    monkeypatch.setenv("VIDSUM_PRZEGLADARKA", "1")
    gui.open_window("http://y")
    assert opened == ["http://x", "http://y"]


def test_native_window_asks_before_closing_during_analysis(monkeypatch, tmp_path):
    import sys
    import types
    from vidsum import gui
    calls = {}

    class Ev(list):
        def __iadd__(self, f):
            self.append(f)
            return self

    class Win:
        def __init__(self):
            self.events = types.SimpleNamespace(closing=Ev())

        def create_confirmation_dialog(self, title, msg):
            calls["dialog"] = msg
            return False

    fake = types.ModuleType("webview")
    fake.settings = {}
    win = Win()
    fake.create_window = lambda title, url, **kw: calls.update(title=title, url=url) or win
    fake.start = lambda *a, **kw: calls.update(start=kw, start_args=a)
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.delenv("VIDSUM_PRZEGLADARKA", raising=False)
    monkeypatch.delenv("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    job = types.SimpleNamespace(status="gotowe")
    app = types.SimpleNamespace(worker=types.SimpleNamespace(jobs={"a": job}), settings={"jezyk_ui": "pl"})
    assert gui.run_window("http://127.0.0.1:1/?t=x", app) is True
    assert calls["url"] == "http://127.0.0.1:1/?t=x" and calls["title"].startswith("Vidsumly")
    import os
    assert os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] == "--disable-gpu"
    close = win.events.closing[0]
    assert close() is True and "dialog" not in calls            # nic nie trwa — zamyka bez pytania
    job.status = "trwa"
    assert close() is False and "Trwa analiza" in calls["dialog"] and "kolejce" in calls["dialog"]
    app.settings["jezyk_ui"] = "en"                             # okno pytania w języku interfejsu
    assert close() is False and "queue" in calls["dialog"]


def test_native_window_missing_library_falls_back(monkeypatch):
    import builtins
    from vidsum import gui
    real = builtins.__import__

    def imp(name, *a, **k):
        if name == "webview":
            raise ImportError("brak")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", imp)
    monkeypatch.delenv("VIDSUM_PRZEGLADARKA", raising=False)
    assert gui.run_window("http://x") is False


def test_open_in_browser_endpoint(server, monkeypatch):
    from vidsum import gui
    base, app = server
    opened = []
    monkeypatch.setattr(gui.webbrowser, "open", opened.append)
    _, r = req(base, "/api/przegladarka", json.dumps({"hash": "#/wynik/abc123"}).encode(), method="POST")
    assert r["ok"] and opened[0].endswith("#/wynik/abc123") and "?t=" in opened[0]
    req(base, "/api/przegladarka", json.dumps({"hash": "javascript:alert(1)"}).encode(), method="POST")
    assert not opened[1].endswith("alert(1)")


def test_icon_served_without_token(server):
    base, _ = server
    _, svg = req(base, "/icon.svg", token=False)
    _, ico = req(base, "/favicon.ico", token=False)
    assert b"<svg" in svg and ico[:4] == b"\x00\x00\x01\x00"


def test_title_bar_colors_match_palette():
    """Pasek tytułu okna (0.10.0): kolory z palety jako COLORREF (0x00BBGGRR) — tło #0d111a, tekst #e9edf5, ramka #3d7bff."""
    from vidsum.gui import TITLE_BAR, _colorref
    assert _colorref(TITLE_BAR["tlo"]) == 0x00000000
    assert _colorref(TITLE_BAR["tekst"]) == 0x00E6EFF5
    assert _colorref(TITLE_BAR["ramka"]) == 0x00F8BD38


def test_comments_endpoint_only_for_links_and_cached(server, monkeypatch):
    """0.10.0: komentarze na żądanie — plik lokalny: niedostępne; link: pobrane raz i zapisane w komentarze.json."""
    base, app = server
    _, job = req(base, "/api/link", data=json.dumps({"zrodlo": str(DATA / "bez_audio.mp4")}).encode(), method="POST")
    wait_done(base, job["id"])
    _, st = req(base, f"/api/zadania/{job['id']}/komentarze")
    assert st == {"stan": "brak", "dostepne": False}
    with pytest.raises(urllib.error.HTTPError) as e:
        req(base, f"/api/zadania/{job['id']}/komentarze", data=b"{}", method="POST")
    assert "linku" in json.loads(e.value.read())["error"]
    out = app.worker.jobs[job["id"]].out
    r = json.loads((out / "analiza.json").read_text(encoding="utf-8"))
    r["zrodlo"].update({"rodzaj": "link", "url": "https://www.youtube.com/watch?v=abc"})
    (out / "analiza.json").write_text(json.dumps(r), encoding="utf-8")
    calls = []
    import vidsum.fetch as f
    monkeypatch.setattr(f, "fetch_comments", lambda url, limit=40, cookies_from_browser=None:
                        calls.append(url) or [{"autor": "@a", "tekst": "Super", "polubienia": 2, "odpowiedz": False}])
    _, c = req(base, f"/api/zadania/{job['id']}/komentarze", data=b"{}", method="POST")
    assert c["stan"] == "gotowe" and c["komentarze"][0]["tekst"] == "Super" and calls == ["https://www.youtube.com/watch?v=abc"]
    _, c2 = req(base, f"/api/zadania/{job['id']}/komentarze")
    assert c2["komentarze"] == c["komentarze"] and len(calls) == 1


def test_queue_order_pause_remove_retry_dedup_and_restore(tmp_path, monkeypatch):
    """0.11.0: kolejka — pauza, kolejność, usuwanie, bez dubli, błąd jednego filmu i ponowienie,
    zapis do kolejka.json i odtworzenie (wstrzymanej) po ponownym uruchomieniu."""
    from vidsum import gui
    from vidsum.pipeline import Options
    done, fail = [], {"b.mp4"}
    gate = threading.Event()

    def fake(src, opt, log):
        if Path(src).name == "slow.mp4":
            gate.wait(10)
        if Path(src).name in fail:
            raise RuntimeError("zepsuty plik")
        done.append(Path(src).name)
        return tmp_path
    monkeypatch.setattr(gui, "analyze", fake)
    state = tmp_path / "kolejka.json"
    w = gui.Worker(state, lambda s: Options())
    w.set_paused(True)
    mk = lambda n: gui.Job(n.split(".")[0], str(tmp_path / n), n, Options(), None)
    a, b, c, d = (w.submit(mk(n)) for n in ("a.mp4", "b.mp4", "c.mp4", "d.mp4"))
    assert w.submit(mk("a.mp4")) is a and len(w.pending) == 4            # ten sam film drugi raz — bez dubla
    assert w.move("c", 0) and w.remove("d") and not w.remove("zzz")
    assert [j.id for j in w.pending] == ["c", "a", "b"]
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert [z["id"] for z in saved["zadania"]] == ["c", "a", "b"] and saved["wstrzymana"] is True
    time.sleep(0.3)
    assert done == []                                                   # wstrzymana — nic nie rusza
    w.set_paused(False)
    for _ in range(100):
        if b.status in ("gotowe", "blad") and len(done) == 2:
            break
        time.sleep(0.05)
    assert done == ["c.mp4", "a.mp4"]
    assert b.status == "blad" and "zepsuty" in b.error
    fail.clear()
    assert w.retry("b") is b
    for _ in range(100):
        if b.status == "gotowe":
            break
        time.sleep(0.05)
    assert b.status == "gotowe" and done[-1] == "b.mp4"
    # zamknięcie w trakcie analizy: trwający film wraca jako pierwszy, kolejka wstrzymana
    s1 = w.submit(mk("slow.mp4"))
    w.submit(mk("e.mp4"))
    for _ in range(100):
        if s1.status == "trwa":
            break
        time.sleep(0.02)
    assert w.stop_for_exit() is s1
    with pytest.raises(RuntimeError):
        w.submit(mk("f.mp4"))                                           # zamyka się — nie przyjmuje nowych
    gate.set()
    w2 = gui.Worker(state, lambda s: Options())
    assert [j.id for j in w2.pending] == ["slow", "e"] and w2.paused and w2.restored == 2
    assert "przerwana" in w2.pending[0].log[0]


def test_shutdown_kills_child_processes_and_keeps_ollama(tmp_path, monkeypatch):
    """0.11.0: zamknięcie kończy własne procesy potomne (tu: długi proces jak ffmpeg), zapisuje kolejkę
    i nie dotyka Ollamy (wywołuje tylko zwolnienie modeli przerwanej analizy)."""
    import subprocess
    from vidsum import gui, procs, tools
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    unloaded = []
    monkeypatch.setattr(gui.Ollama, "unload", lambda self: unloaded.append(self.model))
    app = gui.App(tmp_path / "wyniki", "tok")
    started = threading.Event()
    err = {}

    def fake(src, opt, log):
        started.set()
        try:
            tools.run([sys.executable, "-c", "import time; time.sleep(60)"])
        except Exception as e:
            err["e"] = e
            raise
    monkeypatch.setattr(gui, "analyze", fake)
    job = gui.Job("x1", str(tmp_path / "film.mp4"), "film.mp4", app.options(app.settings), None)
    app.worker.submit(job)
    assert started.wait(5)
    for _ in range(50):
        if procs.running():
            break
        time.sleep(0.05)
    child = procs.running()[0]
    t0 = time.time()
    info = app.shutdown("test")
    assert child.poll() is not None and time.time() - t0 < 5           # proces potomny zakończony
    assert info["zakonczone_procesy"] == 1 and info["przerwany_film"] == "film.mp4"
    assert set(unloaded) == {"qwen3-vl:4b-instruct", app.settings["model_tekstowy"]}
    for _ in range(50):
        if job.status != "trwa":
            break
        time.sleep(0.05)
    assert job.status == "przerwane" and "e" in err
    q = json.loads((tmp_path / "Vidsumly" / "kolejka.json").read_text(encoding="utf-8"))
    assert q["zadania"][0]["przerwane"] and q["wstrzymana"]
    with pytest.raises(tools.ToolError):
        tools.run([sys.executable, "-c", "pass"])                       # po zamknięciu nic nowego nie startuje
    assert json.loads((tmp_path / "Vidsumly" / "zamkniecie.json").read_text(encoding="utf-8"))["powod"] == "test"


def test_result_translated_after_analysis_before_next_video(tmp_path, monkeypatch):
    """0.11.0: po streszczeniu wynik tłumaczy się na angielski w wątku kolejki — następny film rusza dopiero potem
    (karta graficzna po kolei); wyłączone w Ustawieniach → bez tłumaczenia."""
    from vidsum import gui
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    order = []

    def fake(src, opt, log):
        out = tmp_path / Path(src).stem
        out.mkdir(exist_ok=True)
        (out / "analiza.json").write_text(json.dumps({"streszczenie": {"silnik": "ollama:gemma3:4b", "dane": {"teza": "x"}}}),
                                          encoding="utf-8")
        order.append(("analiza", Path(src).stem))
        return out
    monkeypatch.setattr(gui, "analyze", fake)

    def tr(self, p, lang, st=None):
        order.append(("tlumaczenie", p.parent.name, lang))
        time.sleep(0.2)
        return {}
    monkeypatch.setattr(gui.App, "translate_result", tr)
    app = gui.App(tmp_path / "wyniki", "tok")
    a = app.worker.submit(gui.Job("a", str(tmp_path / "a.mp4"), "a", app.options(app.settings), None))
    b = app.worker.submit(gui.Job("b", str(tmp_path / "b.mp4"), "b", app.options(app.settings), None))
    for _ in range(100):
        if len(order) == 4:
            break
        time.sleep(0.05)
    assert order == [("analiza", "a"), ("tlumaczenie", "a", "en"), ("analiza", "b"), ("tlumaczenie", "b", "en")]
    app.settings["tlumacz_wynik"] = False
    order.clear()
    app.worker.submit(gui.Job("c", str(tmp_path / "c.mp4"), "c", app.options(app.settings), None))
    for _ in range(60):
        if order:
            break
        time.sleep(0.05)
    time.sleep(0.2)
    assert order == [("analiza", "c")] and a.status == b.status == "gotowe"


def test_old_uploads_cleaned_but_queued_kept(tmp_path, monkeypatch):
    """0.11.0: przy starcie znikają stare wysłane filmy spoza kolejki; te w kolejce zostają."""
    from vidsum import gui
    from vidsum.pipeline import Options
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    up = tmp_path / "Vidsumly" / "wyslane"
    old, queued, fresh = up / "stary", up / "wkolejce", up / "swiezy"
    for d in (old, queued, fresh):
        d.mkdir(parents=True)
        (d / "f.mp4").write_bytes(b"x")
    past = time.time() - 3 * 86400
    for d in (old, queued):
        os.utime(d, (past, past))
    w = gui.Worker(tmp_path / "Vidsumly" / "kolejka.json", lambda s: Options())
    w.set_paused(True)
    w.submit(gui.Job("q", str(queued / "f.mp4"), "f.mp4", Options(), queued / "f.mp4"))
    monkeypatch.setattr(gui, "Worker", lambda *a, **k: w)
    gui.App(tmp_path / "wyniki", "tok")
    assert not old.exists() and queued.exists() and fresh.exists()


@pytest.mark.skipif(os.name != "nt", reason="obiekt zadania (Job Object) jest tylko w Windows")
def test_windows_children_die_with_program(tmp_path):
    """0.11.0 (Windows): program w obiekcie zadania z „zabij przy zamknięciu” — twarde wyjście programu (os._exit,
    jak przy zamknięciu okna albo awarii) kończy też jego proces potomny; proces „DETACHED” przeżywa."""
    import subprocess
    pidf, pidd = tmp_path / "child.pid", tmp_path / "det.pid"
    code = (
        "import os, subprocess, sys, time\n"
        "from vidsum import procs\n"
        "assert procs.setup_kill_on_close()\n"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open(r'{pidf}', 'w').write(str(c.pid))\n"
        "d = procs.popen_detached([sys.executable, '-c', 'import time; time.sleep(20)'])\n"
        f"open(r'{pidd}', 'w').write(str(d.pid))\n"
        "time.sleep(0.5)\n"
        "os._exit(0)\n")
    subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).parent.parent, timeout=60, check=True)
    time.sleep(1.5)

    def alive(pid: int) -> bool:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    child, det = int(pidf.read_text()), int(pidd.read_text())
    assert not alive(child)
    assert alive(det)
    subprocess.run(["taskkill", "/PID", str(det), "/F"], capture_output=True)


def test_preview_mode_setting(server):
    """0.11.4: wybór w Ustawieniach — „zawsze” (wstępne streszczenie zawsze) albo „najszybciej” (tylko gdy nic nie
    kosztuje, jak w 0.10.0: pomiar 1:15 zamiast 1:28)."""
    base, app = server
    assert app.options(app.settings).preview is True                       # domyślnie: zawsze
    req(base, "/api/ustawienia", data=json.dumps({"tryb_podgladu": "najszybciej"}).encode(), method="POST")
    assert app.options(app.settings).preview is None
    req(base, "/api/ustawienia", data=json.dumps({"tryb_podgladu": "zawsze"}).encode(), method="POST")
    assert app.options(app.settings).preview is True


def test_preview_mode_per_video_and_note(server, monkeypatch):
    """0.11.5: tryb wybierany przy dodaniu filmu (link albo plik) — dla tego filmu i jako domyślny dla następnych.
    Notatka: raport bez obrazków kadrów i bez sekcji o karcie, do wklejenia w inny LLM."""
    base, app = server
    seen = []
    monkeypatch.setattr(app.worker, "submit", lambda job: seen.append(job) or job)
    req(base, "/api/link", data=json.dumps({"zrodlo": "https://example.com/a", "tryb_podgladu": "najszybciej"}).encode(),
        method="POST")
    assert seen[-1].opt.preview is None and seen[-1].settings["tryb_podgladu"] == "najszybciej"
    assert app.settings["tryb_podgladu"] == "najszybciej"
    req(base, "/api/wyslij", data=b"abc", headers={"X-Filename": "f.mp4", "X-Preview": "zawsze"}, method="POST")
    assert seen[-1].opt.preview is True and app.settings["tryb_podgladu"] == "zawsze"
    req(base, "/api/link", data=json.dumps({"zrodlo": "https://example.com/b", "tryb_podgladu": "zle"}).encode(),
        method="POST")
    assert seen[-1].opt.preview is True                                   # zła wartość — zostaje ostatni wybór
    from vidsum.note import note_text
    raport = ("# Tytuł\n\n## W skrócie\nTekst.\n\n## Zasoby komputera (karta graficzna)\n\n- Karta: X\n\n"
              "## Oś czasu (mowa + obraz)\n\n### 00:00–00:05\n![kadr](kadry/kadr_001_00-01.jpg)  \n**Obraz**: deska\n")
    n = note_text(raport)
    assert "![kadr]" not in n and "Karta: X" not in n and "**Obraz**: deska" in n and "## W skrócie" in n
