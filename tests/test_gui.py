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
