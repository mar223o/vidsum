"""Testy na syntetycznych filmach. Modele zastąpione atrapami (fałszywa Ollama, fałszywy `claude`)."""
from __future__ import annotations

import http.server
import json
import os
import stat
import sys
import threading
from pathlib import Path

import pytest

from vidsum.analysis import FrameInfo, build_beats, ts
from vidsum.cli import main
from vidsum.media import SamplingPlan, choose_frames, plan_for, probe, scene_scores
from vidsum.transcribe import Segment, SidecarEngine

DATA = Path(__file__).parent / "data"
FILM = DATA / "Filmy testowe ąęś" / "przepis żółć test.mp4"
NAPISY = DATA / "napisy.json"


# ---------- atrapa Ollamy ----------
class FakeOllama(http.server.BaseHTTPRequestHandler):
    calls: list[dict] = []

    def log_message(self, *a):
        pass

    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._send({"models": [{"name": "fake-vl:latest"}]})

    fail_images: set[int] = set()   # numery żądań z obrazem (od 1), które mają zwrócić 500

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOllama.calls.append(body)
        if body.get("messages") and body["messages"][0].get("images"):
            n = sum(1 for c in FakeOllama.calls if c.get("messages") and c["messages"][0].get("images"))
            if n in FakeOllama.fail_images:
                b = b'{"error":"model runner has unexpectedly stopped"}'
                self.send_response(500)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
                return
        if self.path == "/api/generate":
            return self._send({"done": True})
        msg = body["messages"][0]
        if msg.get("images"):
            content = json.dumps({"scena": "deska i nóż", "czynnosci": ["krojenie"], "obiekty": ["cebula", "nóż"],
                                  "tekst_na_ekranie": "Krok 1", "cialo": None, "pewnosc": "srednia"})
        else:
            content = "## Streszczenie\nFilm pokazuje przepis [mowa+obraz].\n## Najważniejsze momenty\n- `00:00` krojenie [obraz]\n## Czego nie wiadomo\n- czas pieczenia: brak danych"
        self._send({"message": {"role": "assistant", "content": content}})


@pytest.fixture()
def ollama():
    FakeOllama.calls = []
    FakeOllama.fail_images = set()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


# ---------- testy jednostkowe ----------
def test_probe_polish_path():
    info = probe(FILM)
    assert 31 < info.duration < 33 and info.has_audio and info.width == 640


def test_scene_cuts_detected():
    scores = scene_scores(FILM, 2.0)
    thr = SamplingPlan(1, 1).scene_threshold
    cuts = [t for t, s in scores if s >= thr]
    # sceny zaczynają się w 8 s, 16 s, 26 s
    for expected in (8, 16, 26):
        assert any(abs(c - expected) <= 0.6 for c in cuts), (expected, cuts)


def test_choose_frames_rules():
    scores = [(i / 2, 0.0) for i in range(200)]
    scores[40] = (20.0, 0.9)                                    # cięcie
    for i in range(120, 160):                                   # ruch 60–80 s
        scores[i] = (i / 2, 0.1)
    plan = SamplingPlan(base_interval=10, max_frames=100)
    picks = choose_frames(scores, 100.0, plan)
    ts_ = [p.t for p in picks]
    assert ts_ == sorted(ts_)
    assert all(b - a >= plan.min_gap - 1e-9 for a, b in zip(ts_, ts_[1:]))
    assert any("zmiana_sceny" in p.reasons and abs(p.t - 20.5) < 0.01 for p in picks)
    dense = [p for p in picks if 60 <= p.t <= 80]
    sparse = [p for p in picks if 0 <= p.t <= 19]
    assert len(dense) > len(sparse)                             # gęściej tam, gdzie ruch
    capped = choose_frames(scores, 100.0, SamplingPlan(base_interval=10, max_frames=5))
    assert len(capped) == 5 and any("zmiana_sceny" in p.reasons for p in capped)


def test_plan_long_video():
    p = plan_for(40 * 60)
    assert p.max_frames == 150 and 10 <= p.base_interval <= 30


def test_beats_merge_and_sources():
    frames = [FrameInfo(0.5, "a.jpg", ["pokrycie"], 0, {"obiekty": ["cebula"], "czynnosci": []}),
              FrameInfo(8.5, "b.jpg", ["zmiana_sceny"], 0.9, {"obiekty": ["mleko"], "czynnosci": ["wlewanie"]}),
              FrameInfo(16.5, "c.jpg", ["zmiana_sceny"], 0.9, None)]
    # "wlewamy" zaczyna się 8.37 s — po cięciu (8.0), ale PRZED kadrem (8.5): regresja z prawdziwego przebiegu
    segs = [Segment(0.5, 6, "kroimy"), Segment(8.37, 14, "wlewamy"), Segment(17, 20, "mieszamy")]
    beats = build_beats(frames, segs, 32.0)
    # granica odcinka = moment cięcia (kadr 8.5 przy cięciu → odcinek od 8.0)
    assert [b["start"] for b in beats] == [0.0, 8.0, 16.0] and beats[-1]["end"] == 32.0
    assert beats[1]["slychac"] == {"tekst": "wlewamy", "zrodlo": "mowa"}
    assert beats[1]["widac"]["zrodlo"] == "obraz"
    assert beats[2]["widac"] == {"zrodlo": "brak_danych"}
    assert beats[1]["zmiana"]["nowe"] == ["mleko", "wlewanie"]


def test_srt_sidecar(tmp_path):
    srt = tmp_path / "x.srt"
    srt.write_text("1\n00:00:01,500 --> 00:00:03,000\nZażółć gęślą\njaźń\n\n2\n00:01:00,000 --> 00:01:02,250\nDrugi\n", encoding="utf-8")
    t = SidecarEngine(srt).transcribe()
    assert [(s.start, s.end, s.text) for s in t.segments] == [(1.5, 3.0, "Zażółć gęślą jaźń"), (60.0, 62.25, "Drugi")]


def test_ts():
    assert ts(0) == "00:00" and ts(75.4) == "01:15" and ts(3725) == "1:02:05"


# ---------- testy całego przebiegu ----------
def _only_dir(root: Path) -> Path:
    dirs = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith("_")]
    assert len(dirs) == 1
    return dirs[0]


def test_end_to_end_ollama(tmp_path, ollama):
    out_root = tmp_path / "wyniki ąę"
    rc = main([str(FILM), "-o", str(out_root), "--napisy", str(NAPISY), "--ollama", ollama,
               "--model-obrazu", "fake-vl", "--streszczenie", "ollama"])
    assert rc == 0
    out = _only_dir(out_root)
    assert out.name.startswith("przepis żółć test_")
    r = json.loads((out / "analiza.json").read_text(encoding="utf-8"))
    assert r["schema"] == "vidsum.analysis/1"
    assert r["zrodlo"]["plik"] == "przepis żółć test.mp4" and len(r["zrodlo"]["sha256"]) == 64
    assert len(r["transkrypcja"]["segmenty"]) == 4
    assert 4 <= len(r["kadry"]) <= 40
    for k in r["kadry"]:
        assert (out / k["file"]).is_file()
        assert k["vision"]["tekst_na_ekranie"] == ["Krok 1"] and k["vision"]["cialo"] == ""   # normalizacja
    assert {b["widac"]["zrodlo"] for b in r["os_czasu"]} == {"obraz"}
    assert r["streszczenie"]["silnik"] == "ollama:fake-vl"
    imgs = [c for c in FakeOllama.calls if c.get("messages") and c["messages"][0].get("images")]
    assert len(imgs) == len(r["kadry"]) and imgs[0]["format"] == "json"
    assert any(c.get("keep_alive") == 0 for c in FakeOllama.calls)          # zwolnienie VRAM
    prompt = (out / "prompt_dla_claude.md").read_text(encoding="utf-8")
    assert "[mowa]" in prompt and "brak danych" in prompt and "Teraz wlewamy" in prompt
    md = (out / "raport.md").read_text(encoding="utf-8")
    assert "## Streszczenie" in md and "(z mowy)" in md and "(z obrazu" in md
    assert (out / "transkrypcja.srt").read_text(encoding="utf-8").startswith("1\n00:00:00,500 --> 00:00:06,000")


def test_vision_failure_does_not_abort(tmp_path, ollama):
    """Awaria modelu na jednym kadrze (np. brak pamięci): ponowna próba, potem 'brak danych'."""
    FakeOllama.fail_images = {2, 3, 4}   # kadr 2: obie próby padają; kadr 3: druga próba OK
    rc = main([str(FILM), "-o", str(tmp_path), "--napisy", str(NAPISY), "--ollama", ollama,
               "--model-obrazu", "fake-vl", "--max-kadrow", "4", "--streszczenie", "ollama"])
    assert rc == 0
    r = json.loads((_only_dir(tmp_path) / "analiza.json").read_text(encoding="utf-8"))
    vis = [k["vision"] for k in r["kadry"]]
    assert vis[1] is None and vis[0] and vis[2] and vis[3]
    assert r["os_czasu"][1]["widac"] == {"zrodlo": "brak_danych"}
    assert any("Nie udało się opisać kadrów" in g for g in r["luki"])


def test_summary_timeout_still_writes_results(tmp_path, monkeypatch):
    """Regresja: przekroczenie czasu przy streszczeniu kończyło cały film bez wyników."""
    import time as _t

    class Slow(FakeOllama):
        def do_POST(self):
            _t.sleep(2)
            super().do_POST()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    import vidsum.llm as llm
    orig = llm.Ollama.__init__
    monkeypatch.setattr(llm.Ollama, "__init__", lambda self, m, h=None, timeout=600: orig(self, m, h, timeout=0.5))
    try:
        rc = main([str(FILM), "-o", str(tmp_path), "--napisy", str(NAPISY), "--obraz", "brak",
                   "--streszczenie", "ollama", "--ollama", f"http://127.0.0.1:{srv.server_address[1]}"])
    finally:
        srv.shutdown()
    assert rc == 0
    r = json.loads((_only_dir(tmp_path) / "analiza.json").read_text(encoding="utf-8"))
    assert r["streszczenie"] is None and any("nie odpowiedziała" in g for g in r["luki"])


def test_auto_summary_picks_engine(tmp_path, monkeypatch, ollama):
    """auto: jest `claude` i brak klucza API → Claude; brak `claude` → Ollama."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("PATH", str(_fake_claude(tmp_path)) + os.pathsep + os.environ["PATH"])
    main([str(FILM), "-o", str(tmp_path / "a"), "--napisy", str(NAPISY), "--obraz", "brak"])
    r = json.loads((_only_dir(tmp_path / "a") / "analiza.json").read_text(encoding="utf-8"))
    assert r["streszczenie"]["silnik"] == "claude-code"
    monkeypatch.setenv("PATH", str(tmp_path / "pusty"))            # nie ma claude (ani niczego)
    monkeypatch.setenv("VIDSUM_FFMPEG", __import__("shutil").which("ffmpeg", path=os.defpath + ":/usr/local/bin") or "")
    monkeypatch.setenv("VIDSUM_FFPROBE", __import__("shutil").which("ffprobe", path=os.defpath + ":/usr/local/bin") or "")
    main([str(FILM), "-o", str(tmp_path / "b"), "--napisy", str(NAPISY), "--obraz", "brak",
          "--ollama", ollama, "--model-streszczenia", "fake-vl"])
    r = json.loads((_only_dir(tmp_path / "b") / "analiza.json").read_text(encoding="utf-8"))
    assert r["streszczenie"]["silnik"] == "ollama:fake-vl"


def test_no_audio_and_no_vision(tmp_path):
    rc = main([str(DATA / "bez_audio.mp4"), "-o", str(tmp_path), "--obraz", "brak", "--streszczenie", "brak"])
    assert rc == 0
    r = json.loads((_only_dir(tmp_path) / "analiza.json").read_text(encoding="utf-8"))
    assert r["zrodlo"]["audio"] is False and r["transkrypcja"]["segmenty"] == []
    assert any("Brak ścieżki dźwiękowej" in g for g in r["luki"])
    assert any("Analiza obrazu wyłączona" in g for g in r["luki"])
    assert r["streszczenie"] is None
    assert all(b["slychac"]["zrodlo"] == "brak_danych" for b in r["os_czasu"])


def _fake_claude(tmp_path: Path) -> Path:
    d = tmp_path / "bin"
    d.mkdir()
    p = d / "claude"
    p.write_text(f"#!{sys.executable}\nimport sys\ndata=sys.stdin.read()\n"
                 "assert '-p' in sys.argv\nprint('## Streszczenie\\nOK od Claude, znaki: ' + str(len(data)))\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return d


@pytest.mark.skipif(os.name == "nt", reason="atrapa claude jako skrypt POSIX")
def test_claude_summary_and_api_key_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(_fake_claude(tmp_path)) + os.pathsep + os.environ["PATH"])
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = main([str(FILM), "-o", str(tmp_path / "a"), "--napisy", str(NAPISY), "--obraz", "brak",
               "--streszczenie", "claude"])
    assert rc == 0
    r = json.loads((_only_dir(tmp_path / "a") / "analiza.json").read_text(encoding="utf-8"))
    assert r["streszczenie"]["silnik"] == "claude-code" and "OK od Claude" in r["streszczenie"]["markdown"]

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")       # bezpiecznik: nie płacimy przypadkiem za API
    rc = main([str(FILM), "-o", str(tmp_path / "b"), "--napisy", str(NAPISY), "--obraz", "brak",
               "--streszczenie", "claude"])
    r = json.loads((_only_dir(tmp_path / "b") / "analiza.json").read_text(encoding="utf-8"))
    assert r["streszczenie"] is None and any("ANTHROPIC_API_KEY" in g for g in r["luki"])
    assert "sk-test" not in json.dumps(r)                    # klucz nigdy w wynikach


def test_link_download_via_ytdlp(tmp_path):
    """Link http — yt-dlp (ekstraktor ogólny) pobiera plik z lokalnego serwera."""
    import functools
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DATA))
    handler.log_message = lambda *a: None  # type: ignore[attr-defined]
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/bez_audio.mp4"
        rc = main([url, "-o", str(tmp_path), "--obraz", "brak", "--streszczenie", "brak"])
    finally:
        srv.shutdown()
    assert rc == 0
    r = json.loads((_only_dir(tmp_path) / "analiza.json").read_text(encoding="utf-8"))
    assert r["zrodlo"]["rodzaj"] == "link" and r["zrodlo"]["url"] == url


def test_bad_input_does_not_stop_batch(tmp_path, capsys):
    rc = main(["nie_ma_takiego.mp4", str(DATA / "bez_audio.mp4"), "-o", str(tmp_path),
               "--obraz", "brak", "--streszczenie", "brak"])
    assert rc == 1
    assert "1/2 OK" in capsys.readouterr().out
