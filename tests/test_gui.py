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
    assert st == 200 and b"VidSum" in html and b'lang="pl"' in html
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
    saved = json.loads((tmp_path / "appdata" / "VidSum" / "ustawienia.json").read_text(encoding="utf-8"))
    assert saved["jezyk_ui"] == "en"


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
    assert not any((Path(os.environ["LOCALAPPDATA"]) / "VidSum" / "wyslane").glob("*/*.mp4"))


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
                    "assert 'PYTANIE: Co jest w filmie?' in p and 'OŚ CZASU' in p\nprint('Kolorowe paski `00:01`.')\n")
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
        token = (tmp_path / "app" / "VidSum" / "token.txt").read_text().strip()
        base = f"http://127.0.0.1:{gui.DEFAULT_PORT}"
        st, s = req(base, "/api/status", headers={"X-Token": token}, token=False)
        assert st == 200 and "wersja" in s
        p2 = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
                            cwd=Path(__file__).parent.parent)
        assert "już działa" in p2.stdout and token in p2.stdout       # drugie uruchomienie → ten sam adres i klucz
    finally:
        p1.kill()
        p1.wait(timeout=10)
