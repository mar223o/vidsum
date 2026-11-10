"""Testy na syntetycznych filmach. Modele zastąpione atrapami (fałszywa Ollama, fałszywy `claude`)."""
from __future__ import annotations

import http.server
import json
import re
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
FAKE_SUMMARY = {
    "typ": "przepis", "tytul": "Szybki sos", "tytul_akcent": "z cebulą", "teza": "Krótki przepis na sos.",
    "streszczenie": ["Kroimy cebulę, wlewamy mleko i mieszamy."],
    "co_masz_zrobic": {"skladniki": [{"nazwa": "mleko", "ilosc": "200 ml", "zrodlo": "mowa+obraz"}],
                       "kroki": [{"t": "00:09", "tekst": "Wlej mleko", "zrodlo": "mowa"},
                                 {"t": 1, "tekst": "Pokrój cebulę", "zrodlo": "mowa"}],
                       "sprzet": [], "czas": "5 minut", "cwiczenia": [], "wskazowki": [], "bledy": [], "wnioski": []},
    "najwazniejsze": [{"t": 17, "tytul": "Mieszaj 5 minut", "opis": "Na małym ogniu.", "zrodlo": "mowa"}],
    "momenty": [{"t": 26, "tekst": "Gotowe"}], "cytaty": [{"t": 9, "tekst": "Teraz wlewamy", "tlumaczenie": ""}],
    "rozdzialy": [{"start": 0, "end": 999, "tytul": "Całość", "opis": "Wszystko.", "momenty": []}],
    "szczera_ocena": "Prosto.", "czego_nie_wiadomo": ["ile cebuli"], "pytania": ["Ile mleka?"],
}

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
        self._send({"models": [{"name": "fake-vl:latest"}, {"name": "fake-txt:latest"}]})

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
        if self.path == "/api/pull":
            return self._send({"status": "success"})
        msg = body["messages"][0]
        if "LINES:" in msg["content"]:                       # tłumaczenie: „EN: ” + oryginał, te same numery
            import re as _re
            lines = _re.findall(r"^(\d+)\. (.*)$", msg["content"].split("LINES:")[1], _re.M)
            content = json.dumps({n: "EN: " + t for n, t in lines})
        elif msg.get("images") and len(msg["images"]) == 2:
            one = {"scena": "deska i nóż", "czynnosci": ["krojenie"], "obiekty": ["nóż"], "tekst_na_ekranie": [],
                   "napisy_na_przedmiotach": [], "cialo": "", "pewnosc": "srednia"}
            content = json.dumps({"kadr_1": one, "kadr_2": {**one, "scena": "patelnia"}})
        elif msg.get("images"):
            content = json.dumps({"scena": "deska i nóż", "czynnosci": ["krojenie"], "obiekty": ["cebula", "nóż"],
                                  "tekst_na_ekranie": "Krok 1", "cialo": None, "pewnosc": "srednia"})
        elif body.get("format") == "json" and "ZAPIS:" in msg["content"] and "FAKTY Z FILMU" not in msg["content"]:
            content = json.dumps({"typ": FAKE_SUMMARY["typ"], **FAKE_SUMMARY["co_masz_zrobic"]})   # etap 1: fakty
        elif body.get("format") == "json":
            content = json.dumps(FAKE_SUMMARY)
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
    assert p.max_frames == 100 and 10 <= p.base_interval <= 30


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
    rc = main(["--bez-ocr", str(FILM), "-o", str(out_root), "--napisy", str(NAPISY), "--ollama", ollama,
               "--model-obrazu", "fake-vl", "--streszczenie", "ollama", "--model-tekstowy", "fake-txt"])
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
    assert r["streszczenie"]["silnik"] == "ollama:fake-txt"            # osobny model tekstowy
    # oryginał po polsku zostaje; tłumaczenie tylko na angielski (pl → [en]), te same czasy segmentów
    tr = r["transkrypcja"]
    assert tr["jezyk"] == "pl" and list(tr["tlumaczenia"]) == ["en"] and r["ustawienia"]["tlumaczenia"] == ["en"]
    en = tr["tlumaczenia"]["en"]
    assert en["silnik"] == "ollama:fake-txt" and en["nieprzetlumaczone"] == 0
    assert [(s["start"], s["end"]) for s in en["segmenty"]] == [(s["start"], s["end"]) for s in tr["segmenty"]]
    assert all(e["text"] == "EN: " + o["text"] for e, o in zip(en["segmenty"], tr["segmenty"]))
    assert (out / "transkrypcja.en.srt").read_text(encoding="utf-8").count("EN: ") == 4
    assert "tlumaczenie_s" in r["czasy"]
    dane = r["streszczenie"]["dane"]
    assert dane["typ"] == "przepis" and dane["schema"] == "vidsum.summary/1"
    assert [k["t"] for k in dane["co_masz_zrobic"]["kroki"]] == [1.0, 9.0]       # „00:09” → 9 s, posortowane
    assert dane["rozdzialy"][0]["end"] <= r["zrodlo"]["dlugosc_s"]               # czasy przycięte do długości
    assert "### Składniki" in r["streszczenie"]["markdown"] and "200 ml" in r["streszczenie"]["markdown"]
    imgs = [c for c in FakeOllama.calls if c.get("messages") and c["messages"][0].get("images")]
    assert len(imgs) == len(r["kadry"]) and imgs[0]["format"]["properties"]["obiekty"]["maxItems"] == 6   # schemat (0.7.7)
    assert any(c.get("keep_alive") == 0 for c in FakeOllama.calls)          # zwolnienie VRAM
    prompt = (out / "prompt_dla_claude.md").read_text(encoding="utf-8")
    assert "[mowa]" in prompt and "brak danych" in prompt and "Teraz wlewamy" in prompt
    md = (out / "raport.md").read_text(encoding="utf-8")
    assert "## W skrócie" in md and "(z mowy)" in md and "(z obrazu" in md
    assert "⏱ Czas analizy:" in md and "kadry " in md                     # czas w raporcie
    assert "## Tłumaczenie: angielski" in md and "oryginał: polski" in md
    assert (out / "transkrypcja.srt").read_text(encoding="utf-8").startswith("1\n00:00:00,500 --> 00:00:06,000")


def test_vision_failure_does_not_abort(tmp_path, ollama, monkeypatch):
    """Awaria modelu na jednym kadrze (np. brak pamięci): ponowna próba, potem 'brak danych'."""
    FakeOllama.fail_images = {2, 3, 4}   # kadr 2: obie próby padają; kadr 3: druga próba OK
    import vidsum.pipeline as pl
    monkeypatch.setattr(pl, "VISION_WORKERS", 1)    # numery żądań = kolejność kadrów
    rc = main(["--bez-ocr", str(FILM), "-o", str(tmp_path), "--napisy", str(NAPISY), "--ollama", ollama,
               "--model-obrazu", "fake-vl", "--max-kadrow", "4", "--streszczenie", "ollama", "--model-tekstowy", "fake-vl"])
    assert rc == 0
    r = json.loads((_only_dir(tmp_path) / "analiza.json").read_text(encoding="utf-8"))
    vis = [k["vision"] for k in r["kadry"]]
    assert len(vis) >= 3 and vis[1] is None and all(v for i, v in enumerate(vis) if i != 1)
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
        rc = main(["--bez-ocr", str(FILM), "-o", str(tmp_path), "--napisy", str(NAPISY), "--obraz", "brak",
                   "--streszczenie", "ollama", "--model-tekstowy", "fake-vl",
                   "--ollama", f"http://127.0.0.1:{srv.server_address[1]}"])
    finally:
        srv.shutdown()
    assert rc == 0
    r = json.loads((_only_dir(tmp_path) / "analiza.json").read_text(encoding="utf-8"))
    assert r["streszczenie"] is None and any("nie odpowiedziała" in g for g in r["luki"])


@pytest.mark.skipif(os.name == "nt", reason="atrapa claude jako skrypt POSIX")
def test_auto_summary_is_local_even_with_claude(tmp_path, monkeypatch, ollama):
    """Faza 6: aplikacja jest samodzielna — auto = lokalny model, nawet gdy Claude Code jest zainstalowany."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("PATH", str(_fake_claude(tmp_path)) + os.pathsep + os.environ["PATH"])
    main(["--bez-ocr", str(FILM), "-o", str(tmp_path / "a"), "--napisy", str(NAPISY), "--obraz", "brak",
          "--ollama", ollama, "--model-tekstowy", "fake-txt"])
    r = json.loads((_only_dir(tmp_path / "a") / "analiza.json").read_text(encoding="utf-8"))
    assert r["streszczenie"]["silnik"] == "ollama:fake-txt"
    main(["--bez-ocr", str(FILM), "-o", str(tmp_path / "b"), "--napisy", str(NAPISY), "--obraz", "brak",
          "--ollama", ollama, "--model-streszczenia", "fake-vl", "--tlumacz", "brak"])      # dawna opcja działa
    r = json.loads((_only_dir(tmp_path / "b") / "analiza.json").read_text(encoding="utf-8"))
    assert r["streszczenie"]["silnik"] == "ollama:fake-vl" and r["transkrypcja"]["tlumaczenia"] == {}


def test_text_model_is_pulled_when_missing(tmp_path, ollama):
    """Model tekstowy, którego nie ma w Ollamie, jest pobierany automatycznie (bez ręcznego `ollama pull`)."""
    main(["--bez-ocr", str(FILM), "-o", str(tmp_path), "--napisy", str(NAPISY), "--obraz", "brak",
          "--ollama", ollama, "--model-tekstowy", "nowy-model:8b", "--tlumacz", "brak"])
    pulls = [c for c in FakeOllama.calls if c.get("model") == "nowy-model:8b" and "messages" not in c]
    assert pulls, "brak żądania /api/pull"
    chats = [c for c in FakeOllama.calls if c.get("messages") and c.get("model") == "nowy-model:8b"]
    assert chats and chats[0].get("think") is False                    # qwen3 itp. bez „myślenia”


def test_no_audio_and_no_vision(tmp_path):
    rc = main(["--bez-ocr", str(DATA / "bez_audio.mp4"), "-o", str(tmp_path), "--obraz", "brak", "--streszczenie", "brak"])
    assert rc == 0
    r = json.loads((_only_dir(tmp_path) / "analiza.json").read_text(encoding="utf-8"))
    assert r["zrodlo"]["audio"] is False and r["transkrypcja"]["segmenty"] == []
    assert any("Brak ścieżki dźwiękowej" in g for g in r["luki"])
    assert any("Analiza obrazu wyłączona" in g for g in r["luki"])
    assert r["streszczenie"] is None
    assert all(b["slychac"]["zrodlo"] == "brak_danych" for b in r["os_czasu"])
    assert all(b["end"] - b["start"] >= 0.5 for b in r["os_czasu"])            # bez pustych odcinków
    assert sum("ścieżki dźwiękowej" in g for g in r["luki"]) == 1               # bez dubli w lukach


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
    rc = main(["--bez-ocr", str(FILM), "-o", str(tmp_path / "a"), "--napisy", str(NAPISY), "--obraz", "brak",
               "--streszczenie", "claude", "--tlumacz", "brak"])
    assert rc == 0
    r = json.loads((_only_dir(tmp_path / "a") / "analiza.json").read_text(encoding="utf-8"))
    assert r["streszczenie"]["silnik"] == "claude-code" and "OK od Claude" in r["streszczenie"]["markdown"]

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")       # bezpiecznik: nie płacimy przypadkiem za API
    rc = main(["--bez-ocr", str(FILM), "-o", str(tmp_path / "b"), "--napisy", str(NAPISY), "--obraz", "brak",
               "--streszczenie", "claude", "--tlumacz", "brak"])
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
        rc = main(["--bez-ocr", url, "-o", str(tmp_path), "--obraz", "brak", "--streszczenie", "brak"])
    finally:
        srv.shutdown()
    assert rc == 0
    r = json.loads((_only_dir(tmp_path) / "analiza.json").read_text(encoding="utf-8"))
    assert r["zrodlo"]["rodzaj"] == "link" and r["zrodlo"]["url"] == url


def test_bad_input_does_not_stop_batch(tmp_path, capsys):
    rc = main(["--bez-ocr", "nie_ma_takiego.mp4", str(DATA / "bez_audio.mp4"), "-o", str(tmp_path),
               "--obraz", "brak", "--streszczenie", "brak"])
    assert rc == 1
    assert "1/2 OK" in capsys.readouterr().out


def test_vision_cleanup_foreign_script_and_new_key():
    """Regresja z prawdziwego filmu: model wtrącał chińskie znaki („metalowy滤网”)."""
    from vidsum.llm import _clean_vision
    v = _clean_vision({"scena": "Widoczny jest metalowy滤网 z frytkami", "obiekty": ["metalowy滤网", "nóż"],
                       "napisy_na_przedmiotach": "Do not hammer", "pewnosc": "wysoka"})
    assert v["scena"] == "Widoczny jest metalowy [?] z frytkami"
    assert v["obiekty"] == ["metalowy [?]", "nóż"]
    assert v["napisy_na_przedmiotach"] == ["Do not hammer"] and v["tekst_na_ekranie"] == []
    assert v["pewnosc"] == "srednia"
    assert _clean_vision({"scena": "ok", "pewnosc": "wysoka"})["pewnosc"] == "wysoka"


def test_parse_vtt_youtube_rolling_captions():
    from vidsum.transcribe import parse_vtt
    raw = ("WEBVTT\nKind: captions\nLanguage: en\n\n"
           "00:00:00.160 --> 00:00:02.310 align:start position:0%\n \n"
           "today<00:00:00.640><c> we</c><c> make</c><c> fries</c>\n\n"
           "00:00:02.310 --> 00:00:02.320 align:start position:0%\ntoday we make fries\n \n\n"
           "00:00:02.320 --> 00:00:05.000 align:start position:0%\ntoday we make fries\n"
           "cut<00:00:02.800><c> the</c><c> potatoes</c>\n\n"
           "7\n01:00:02.000 --> 01:00:04.500\nZażółć gęślą jaźń\n")
    segs = [(s.start, s.end, s.text) for s in parse_vtt(raw)]
    assert segs == [(0.16, 2.31, "today we make fries"), (2.32, 5.0, "cut the potatoes"),
                    (3602.0, 3604.5, "Zażółć gęślą jaźń")]


def test_subtitles_only_in_original_language(tmp_path):
    """Transkrypcja ZAWSZE w języku oryginału: napisy autora w innym języku i tłumaczenia YouTube odpadają."""
    from vidsum.fetch import choose_subtitle_lang, pick_subtitles
    c = choose_subtitle_lang
    # film po angielsku: autor dał też napisy PL (to przekład) → bierzemy angielskie od autora
    assert c({"language": "en", "subtitles": {"pl": [], "en": []}, "automatic_captions": {"en-orig": [], "pl": []}}) == ("en", "autor")
    # tylko polskie od autora do filmu po angielsku → nie; automatyczne en-orig → tak
    assert c({"language": "en", "subtitles": {"pl": []}, "automatic_captions": {"en-orig": [], "pl": []}}) == ("en-orig", "automatyczne")
    # niemiecki film (dowolny język, nie tylko pl/en)
    assert c({"language": "de", "subtitles": {}, "automatic_captions": {"de-orig": [], "en": [], "pl": []}}) == ("de-orig", "automatyczne")
    assert c({"language": "de-DE", "subtitles": {"de-DE": []}, "automatic_captions": {}}) == ("de-DE", "autor")
    # język nieznany: jedno „-orig” wskazuje oryginał; bez tego → Whisper
    assert c({"subtitles": {}, "automatic_captions": {"es-orig": [], "pl": []}}) == ("es-orig", "automatyczne")
    assert c({"subtitles": {"pl": []}, "automatic_captions": {}}) is None
    assert c({}) is None
    f = tmp_path / "x.en-orig.vtt"
    f.write_text("WEBVTT\n", encoding="utf-8")
    info = {"language": "en", "subtitles": {"pl": []}, "automatic_captions": {"en-orig": []},
            "requested_subtitles": {"en-orig": {"filepath": str(f)}}}
    assert pick_subtitles(info) == (f, "automatyczne")
    assert pick_subtitles({}) == (None, None)


def test_languages_all_whisper_codes_and_targets():
    from faster_whisper.tokenizer import _LANGUAGE_CODES
    from vidsum.languages import LANGUAGES, normalize, parse_list, translation_targets as tt
    assert set(LANGUAGES) == set(_LANGUAGE_CODES) and len(LANGUAGES) == 100
    assert normalize("DE") == "de" and normalize("auto") is None and normalize("") is None and normalize("pt-BR") == "pt"
    with pytest.raises(ValueError):
        normalize("xx")
    # oryginał zostaje zawsze; tłumaczenia: en → pl; pl → en; inne → pl i en
    assert tt("en") == ["pl"] and tt("pl") == ["en"] and tt("de") == ["pl", "en"] and tt("uk") == ["pl", "en"]
    assert tt(None) == [] and tt("en-orig") == ["pl"]
    assert tt("de", parse_list("pl")) == ["pl"] and parse_list("brak") == [] and parse_list("pl, en") == ["pl", "en"]


def test_cli_rejects_unknown_language(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main([str(DATA / "bez_audio.mp4"), "-o", str(tmp_path), "--jezyk", "klingon"])
    assert "Nieznany język" in capsys.readouterr().err


def test_translate_segments_chunks_retries_and_gaps():
    """Tłumaczenie porcjami; zła odpowiedź → ponowna próba i mniejsze porcje; nigdy zgadywany tekst."""
    from vidsum.translate import translate_segments
    import re as _re

    class Eng:
        def __init__(self):
            self.prompts = []

        def complete(self, prompt, as_json=False):
            self.prompts.append(prompt)
            lines = _re.findall(r"^(\d+)\. (.*)$", prompt.split("LINES:")[1], _re.M)
            if any("ZEPSUTE" in t for _, t in lines):
                return "to nie jest json"
            if any("CHINY" in t for _, t in lines):
                return json.dumps({n: "tekst 中文" for n, _ in lines})       # obce pismo → odrzucone
            return json.dumps({n: f"PL<{t}>" for n, t in lines})

    segs = [{"start": i, "end": i + 1, "text": f"line {i}"} for i in range(45)]
    segs[30]["text"] = "ZEPSUTE"
    segs[40]["text"] = "CHINY"
    e = Eng()
    out, failed = translate_segments(e, segs, "en", "pl", chunk=20)
    assert failed == 2 and out[30]["text"] is None and out[40]["text"] is None
    assert out[0]["text"] == "PL<line 0>" and out[44]["text"] == "PL<line 44>" and out[29]["text"] == "PL<line 29>"
    assert [(s["start"], s["end"]) for s in out] == [(s["start"], s["end"]) for s in segs]
    assert "from English into Polish" in e.prompts[0] and "Previous lines" in e.prompts[1]


def test_speech_runs_in_parallel_with_vision(tmp_path, ollama, monkeypatch):
    """Whisper na CPU liczy się w tle, gdy model obrazu opisuje kadry — czas całości < suma etapów."""
    import time as _t
    import vidsum.pipeline as pl
    from vidsum.transcribe import Segment, Transcript

    class SlowWhisper:
        coverage_hints: list = []
        recovered = 0

        def __init__(self, *a, **k):
            pass

        def resolve_device(self, log=None):
            return "cpu", None

        def transcribe(self, wav, language=None):
            _t.sleep(2.0)
            return Transcript("pl", "atrapa", [Segment(1, 2, "mowa z atrapy")])

    orig_describe = __import__("vidsum.llm", fromlist=["Ollama"]).Ollama.describe_frame

    def slow_describe(self, image, t_label):
        _t.sleep(0.5)
        return orig_describe(self, image, t_label)

    monkeypatch.setattr(pl, "WhisperEngine", SlowWhisper)
    monkeypatch.setattr(pl.Ollama, "describe_frame", slow_describe)
    rc = main(["--bez-ocr", str(FILM), "-o", str(tmp_path), "--ollama", ollama, "--model-obrazu", "fake-vl",
               "--max-kadrow", "4", "--streszczenie", "brak"])
    assert rc == 0
    r = json.loads((_only_dir(tmp_path) / "analiza.json").read_text(encoding="utf-8"))
    c = r["czasy"]
    assert r["transkrypcja"]["segmenty"][0]["text"] == "mowa z atrapy"
    assert c["transkrypcja_s"] >= 2.0 and c["obraz_s"] >= 1.0
    assert c["razem_s"] < c["transkrypcja_s"] + c["obraz_s"]      # nakładały się w czasie


def test_salvage_truncated_vision_json():
    """Regresja z prawdziwego filmu: model urwał JSON i w raporcie lądował surowy tekst."""
    from vidsum.llm import _clean_vision, salvage_json
    t = ('{ "scena": "Kucharz dodaje coś do dużego garnka.", "czynnosci": [ "dodawanie", "mieszanie" ], '
         '"obiekty": [ "garnek", "płytka indukcyjna", "ręk')
    v = _clean_vision(salvage_json(t))
    assert v["scena"] == "Kucharz dodaje coś do dużego garnka."
    assert v["czynnosci"] == ["dodawanie", "mieszanie"] and v["obiekty"] == []
    assert "{" not in v["scena"]


def _bench_video(tmp_path: Path) -> Path:
    """Film z wypalonymi napisami (jak Shorts) — tekst znany: „Maris Piper”, „Maldon sea salt”."""
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if not Path(font).is_file():
        pytest.skip("brak czcionki DejaVu")
    chunks = ["Start with Maris", "Piper potatoes", "sprinkle of Maldon", "sea salt"]
    draws = []
    for i, c in enumerate(chunks):
        f = tmp_path / f"c{i}.txt"
        f.write_text(c, encoding="utf-8")
        draws.append(f"drawtext=fontfile={font}:textfile={f}:fontsize=46:fontcolor=white:box=1:boxcolor=black@0.55:"
                     f"boxborderw=14:x=(w-tw)/2:y=h*0.7:enable='between(t,{i * 1.5},{i * 1.5 + 1.5})'")
    out = tmp_path / "napisy ąę.mp4"
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x2d4a22:s=720x1280:r=25:d=6",
                    "-vf", ",".join(draws), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
    return out


def test_ocr_reads_burned_captions_and_builds_hotwords(tmp_path):
    from vidsum.ocr import ensure_models, hotwords, read_captions
    v = _bench_video(tmp_path)
    mdir = ensure_models(tmp_path / "modele")
    lines = read_captions(v, 6.0, mdir, log=lambda *a: None)
    texts = [l.text for l in lines]
    assert texts == ["Start with Maris", "Piper potatoes", "sprinkle of Maldon", "sea salt"], texts
    assert abs(lines[0].start - 0.0) <= 0.5 and abs(lines[2].start - 3.0) <= 0.6
    hw = hotwords(lines, "The Perfect French Fry")
    assert "Maris Piper" in hw and "Maldon sea salt" in hw and hw.startswith("The Perfect French Fry")


def test_ocr_in_pipeline_and_timeline(tmp_path):
    v = _bench_video(tmp_path)
    rc = main([str(v), "-o", str(tmp_path / "w"), "--obraz", "brak", "--streszczenie", "brak",
               "--whisper-folder", str(tmp_path / "modele")])
    assert rc == 0
    r = json.loads((_only_dir(tmp_path / "w") / "analiza.json").read_text(encoding="utf-8"))
    assert [n["text"] for n in r["napisy_ekranowe"]][:2] == ["Start with Maris", "Piper potatoes"]
    assert any("Maldon" in b["napisy"] for b in r["os_czasu"])
    assert r["czasy"]["ocr_s"] > 0
    prompt = (_only_dir(tmp_path / "w") / "prompt_dla_claude.md").read_text(encoding="utf-8")
    assert "NAPISY: " in prompt and "Maris" in prompt


def test_parse_summary_robustness():
    from vidsum.summary import parse_summary, to_markdown
    assert parse_summary("to nie jest json", 60) is None
    d = parse_summary("Oto wynik:\n```json\n" + json.dumps(FAKE_SUMMARY) + "\n```", 30)
    assert d and d["rozdzialy"][0]["end"] == 30 and d["typ"] == "przepis"
    bad = dict(FAKE_SUMMARY, typ="cokolwiek", momenty=[{"t": "x", "tekst": "a"}, "śmieć"])
    d = parse_summary(json.dumps(bad), 30)
    assert d["typ"] == "inne" and d["momenty"] == [{"t": 0.0, "tekst": "a"}]
    md = to_markdown(d)
    assert "## Najważniejsze" in md and "`00:17` **Mieszaj 5 minut**" in md


def test_staged_summary_merges_facts_and_chunks():
    """Lokalne modele: najpierw fakty (porcjami dla długich filmów), potem opis całości; scalanie w jeden schemat."""
    from vidsum.summary import compact_timeline, staged_summary
    beats = [{"start": i * 10, "end": i * 10 + 10, "kadr": "", "napisy": "190°C" if i == 3 else "",
              "widac": {"zrodlo": "obraz", "scena": "kuchnia", "czynnosci": ["krojenie"], "obiekty": ["nóż", "deska"]},
              "slychac": {"zrodlo": "mowa", "tekst": f"zdanie {i}"}} for i in range(6)]
    tl = compact_timeline(beats)
    assert "[30s] MOWA: zdanie 3 | NAPISY: 190°C | OBRAZ: kuchnia (krojenie)" in tl and "nóż" not in tl

    class Eng:
        def __init__(self):
            self.prompts = []

        def complete(self, prompt, as_json=False):
            self.prompts.append(prompt)
            if "JEDNĄ czynność" in prompt:                                       # kontrola liczb
                n = prompt.split("zawiera liczbę ")[1].split()[0]
                return json.dumps({"tekst": f"zrób {n} razy"})
            if "FRAGMENTY:\n" in prompt:                                       # kontrola kompletności
                self.fill = prompt
                return json.dumps({"kroki": [{"t": 30, "tekst": "Rozgrzej olej do 190°C", "zrodlo": "obraz"},
                                             {"t": 0, "tekst": "krok od 0", "zrodlo": "mowa"}]})
            if "ZAPIS:\n" in prompt and "FAKTY Z FILMU" not in prompt:       # etap 1, porcja
                first = int(prompt.split("ZAPIS:\n")[1].split("s]")[0].strip("["))
                return json.dumps({"typ": "przepis", "kroki": [{"t": first, "tekst": f"krok od {first}", "zrodlo": "mowa"}],
                                   "skladniki": [{"nazwa": "ziemniaki", "ilosc": "brak danych", "zrodlo": "mowa"}],
                                   "wskazowki": [{"tekst": "nie przypal"}], "fakty": []})
            assert '"krok od 0"' in prompt                                     # etap 2 dostaje fakty
            return json.dumps({"tytul": "Frytki", "teza": "Jak zrobić frytki.", "streszczenie": ["Akapit."],
                               "najwazniejsze": [{"t": 30, "tytul": "190", "opis": "x", "zrodlo": "obraz"}]})

    e = Eng()
    d = staged_summary(e, tl, "tytuł: test", 60.0, chunk_chars=120)
    assert len(e.prompts) >= 4                                                 # ≥2 porcje + uzupełnienie + liczby + opis
    c = d["co_masz_zrobic"]
    assert d["typ"] == "przepis" and d["tytul"] == "Frytki"
    assert [k["t"] for k in c["kroki"]] == sorted(k["t"] for k in c["kroki"])
    # kontrola kompletności: 190 z NAPISÓW nie było w krokach → dopisane; powtórzony „krok od 0” — nie
    assert "190°C" in e.fill and any("190" in k["tekst"] for k in c["kroki"])
    assert sum(1 for k in c["kroki"] if k["tekst"] == "krok od 0") == 1
    assert c["skladniki"] == [{"nazwa": "ziemniaki", "ilosc": "brak danych", "zrodlo": "mowa"}]   # bez dubli z porcji
    assert c["wskazowki"] == ["nie przypal"]


def test_missing_lines_and_parallel_presentation():
    """Brakujące fragmenty (bez kroku lub z pominiętą liczbą) i opis całości w dwóch częściach naraz."""
    import threading
    from vidsum.summary import missing_lines, staged_summary
    tl = ("[0s] MOWA: Start with agria potatoes today.\n[10s] MOWA: Heat the oil up to 190 degrees.\n"
          "[20s] MOWA: Extra crunch.\n[30s] MOWA: Fry until golden and crispy.")
    miss = missing_lines(tl, {"kroki": [{"t": 1, "tekst": "Użyj ziemniaków agria"}, {"t": 11, "tekst": "Rozgrzej olej"},
                                         {"t": 31, "tekst": "Smaż na złoto"}]})
    assert miss == ["[10s] MOWA: Heat the oil up to 190 degrees."]        # „Extra crunch.” za krótkie
    assert missing_lines(tl, {"kroki": [{"t": 1, "tekst": "a"}, {"t": 11, "tekst": "olej 190"}, {"t": 31, "tekst": "b"}]}) == []
    from vidsum.summary import missing_numbers
    assert missing_numbers(tl + " | NAPISY: 190°C", {"kroki": []}) == [(10.0, "190", "Heat the oil up to 190 degrees.", "mowa")]

    class Eng:
        parallel = 3

        def __init__(self):
            self.live, self.peak, self.lock = 0, 0, threading.Lock()

        def complete(self, prompt, as_json=False):
            import time as _t
            with self.lock:
                self.live += 1
                self.peak = max(self.peak, self.live)
            _t.sleep(0.2)
            with self.lock:
                self.live -= 1
            if "FAKTY Z FILMU" in prompt and '"momenty"' in prompt.split("JSON-em:")[-1]:
                return json.dumps({"momenty": [{"t": 1, "tekst": "m"}], "rozdzialy": [{"start": 0, "end": 40, "tytul": "R", "opis": "o"}]})
            if "FAKTY Z FILMU" in prompt:
                return json.dumps({"tytul": "T", "teza": "Teza.", "streszczenie": ["A."]})
            return json.dumps({"typ": "inne", "fakty": ["f"]})

    e = Eng()
    d = staged_summary(e, tl * 3, "", 40.0)
    assert e.peak >= 2 and d["teza"] == "Teza." and d["rozdzialy"] and d["momenty"]


def test_english_speech_original_kept_and_translated(tmp_path, ollama):
    """Oryginał EN zostaje w transkrypcji i trafia do streszczenia; tłumaczenie tylko na polski."""
    srt = tmp_path / "en.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:04,000\nHeat the oil to 190 degrees\n\n"
                   "2\n00:00:09,000 --> 00:00:12,000\nFry until golden\n", encoding="utf-8")
    rc = main(["--bez-ocr", str(FILM), "-o", str(tmp_path / "w"), "--napisy", str(srt), "--jezyk", "en",
               "--obraz", "brak", "--ollama", ollama, "--model-tekstowy", "fake-txt"])
    assert rc == 0
    r = json.loads((_only_dir(tmp_path / "w") / "analiza.json").read_text(encoding="utf-8"))
    tr = r["transkrypcja"]
    assert tr["segmenty"][0]["text"] == "Heat the oil to 190 degrees"            # oryginał nietknięty
    assert list(tr["tlumaczenia"]) == ["pl"]                                       # en → tylko pl
    extract = [c["messages"][0]["content"] for c in FakeOllama.calls
               if c.get("messages") and "ZAPIS:" in c["messages"][0]["content"] and "FAKTY Z FILMU" not in c["messages"][0]["content"]]
    assert extract and "MOWA: Heat the oil to 190 degrees" in extract[0]           # streszczenie z oryginału
    assert tr["tlumaczenia"]["pl"]["segmenty"][0]["text"] == "EN: Heat the oil to 190 degrees"   # (atrapa dopisuje „EN: ”)


def test_staged_summary_survives_repeat_limit():
    """Regresja z pomiaru: „prediction aborted, token repeat limit reached” nie może zabić streszczenia."""
    from vidsum.llm import LLMError
    from vidsum.summary import staged_summary
    n = {"i": 0}

    class Eng:
        def complete(self, prompt, as_json=False):
            n["i"] += 1
            if n["i"] == 1:
                raise LLMError('Ollama 500: {"error":"prediction aborted, token repeat limit reached"}')
            if "FAKTY Z FILMU" not in prompt:
                return json.dumps({"typ": "przepis", "kroki": [{"t": 1, "tekst": "Smaż w 190°C", "zrodlo": "mowa"}]})
            return json.dumps({"teza": "Frytki."})
    d = staged_summary(Eng(), "[1s] MOWA: fry at 190", "", 10.0)
    assert d["co_masz_zrobic"]["kroki"][0]["tekst"] == "Smaż w 190°C" and d["teza"] == "Frytki."


def test_pipeline_emits_partial_results(tmp_path, ollama):
    got = {}
    from vidsum.pipeline import Options, analyze
    opt = Options(out_root=tmp_path, transcript_file=NAPISY, ocr=False, ollama_host=ollama, vision_model="fake-vl",
                  text_model="fake-txt", on_partial=lambda k, d: got.__setitem__(k, d))   # ostatnia wersja każdej części
    analyze(str(FILM), opt, log=lambda m: None)
    assert list(got)[:3] == ["meta", "transkrypcja", "kadry"] and "tlumaczenie_en" in got
    assert got["meta"]["dlugosc_s"] > 0
    assert got["transkrypcja"]["segmenty"][0]["text"] and got["kadry"][0]["scena"] == "deska i nóż"


def test_gpu_order_whisper_first_then_hotword_pass(tmp_path, ollama, monkeypatch):
    """GPU: transkrypcja startuje od razu (nie czeka na OCR), po kadrach — druga z podpowiedziami z napisów."""
    import time as _t
    import vidsum.pipeline as pl
    import vidsum.ocr as ocr
    from vidsum.ocr import OcrLine
    from vidsum.transcribe import Segment, Transcript
    events = []

    class FakeWhisper:
        def __init__(self, *a, hotwords=None, **k):
            self.hotwords, self.coverage_hints, self.recovered, self.cuda_download = hotwords, [], 0, False

        def resolve_device(self, log=None):
            return "cuda", None

        def transcribe(self, wav, language=None):
            events.append(("whisper", self.hotwords, _t.time()))
            text = "Start with Agria potatoes" if self.hotwords else "Start with a grilled potatoes"
            return Transcript("en", "atrapa:cuda", [Segment(1, 3, text)])

    def slow_ocr(video, duration, mdir, log):
        _t.sleep(1.5)
        events.append(("ocr_done", None, _t.time()))
        return [OcrLine(1.0, 3.0, "start with agria potatoes", 0.95)]

    monkeypatch.setattr(pl, "WhisperEngine", FakeWhisper)
    monkeypatch.setattr(ocr, "read_captions", slow_ocr)
    monkeypatch.setattr(ocr, "ensure_models", lambda root, log=None: root)
    got = []
    opt = pl.Options(out_root=tmp_path, ollama_host=ollama, vision_model="fake-vl", text_model="fake-txt",
                     max_frames=4, translate=[], on_partial=lambda k, d: got.append((k, d)))
    out = pl.analyze(str(DATA / "Filmy testowe ąęś" / "przepis z mową.mp4"), opt, log=lambda m: None)
    w = [e for e in events if e[0] == "whisper"]
    ocr_t = next(e[2] for e in events if e[0] == "ocr_done")
    assert w[0][1] is None and w[0][2] < ocr_t                  # pierwsza transkrypcja przed końcem OCR
    assert w[1][1] and "agria" in w[1][1].lower()               # druga z podpowiedziami
    r = json.loads((out / "analiza.json").read_text(encoding="utf-8"))
    assert r["transkrypcja"]["segmenty"][0]["text"] == "Start with Agria potatoes"
    assert "transkrypcja_poprawka_s" in r["czasy"] and r["napisy_ekranowe"]
    assert [k for k, _ in got].count("transkrypcja") == 2       # podgląd: najpierw szybka, potem poprawiona
    assert (out / "przebieg.log").read_text(encoding="utf-8").count("kadr") >= 2


def test_quotes_must_be_in_transcript_and_type_fields():
    """Regresja z prawdziwego filmu: zmyślony cytat i „ćwiczenia” w przepisie."""
    from vidsum.summary import parse_summary, verify_quotes
    segs = [{"text": "We've got some duck fat too for flavor. And once it"}, {"text": "reaches around about 140°, we're going"}]
    d = parse_summary(json.dumps({"typ": "przepis", "teza": "x", "cytaty": [
        {"t": 1, "tekst": "Duck fat adds a deep flavor to the fries."},
        {"t": 2, "tekst": "We've got some duck fat too for flavour"},
        {"t": 3, "tekst": "once it reaches around about 140°"}],
        "co_masz_zrobic": {"cwiczenia": [{"nazwa": "Smażenie", "t": 1}]}}), 60)
    assert d["co_masz_zrobic"]["cwiczenia"] == []
    assert verify_quotes(d, segs) == 1 and [q["t"] for q in d["cytaty"]] == [2.0, 3.0]


def test_timing_history_csv(tmp_path):
    """Każda analiza dopisuje linijkę z czasami etapów do historia_czasow.csv (porównywanie w czasie)."""
    for _ in range(2):
        assert main(["--bez-ocr", str(DATA / "bez_audio.mp4"), "-o", str(tmp_path), "--obraz", "brak",
                     "--streszczenie", "brak"]) == 0
    rows = (tmp_path / "historia_czasow.csv").read_text(encoding="utf-8-sig").strip().splitlines()
    assert len(rows) == 3 and rows[0].startswith("data;wersja;tytul;dlugosc_s")
    cells = rows[1].split(";")
    assert cells[2] == "bez_audio.mp4" and "," in cells[7]                       # razem_s z przecinkiem


def test_youtube_auto_captions_replaced_by_whisper_on_gpu(tmp_path, monkeypatch, ollama):
    """Automatyczne napisy YouTube = tylko podgląd; na GPU docelowo Whisper (z podpowiedziami z OCR)."""
    import vidsum.pipeline as pl
    import vidsum.ocr as ocr
    from vidsum.fetch import Source
    from vidsum.ocr import OcrLine
    from vidsum.transcribe import Segment, Transcript
    vtt = tmp_path / "x.en-orig.vtt"
    vtt.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nStart with a grilled potatoes\n", encoding="utf-8")
    film = tmp_path / "pobrane.mp4"                       # kopia — pliki z linków są przenoszone do wyników
    film.write_bytes((DATA / "Filmy testowe ąęś" / "przepis z mową.mp4").read_bytes())
    monkeypatch.setattr(pl, "resolve", lambda inp, tmp, c=None: Source("link", inp, film, "Fries", "x", inp, vtt, "automatyczne"))
    calls = []

    class FakeWhisper:
        def __init__(self, *a, hotwords=None, **k):
            self.hotwords, self.coverage_hints, self.recovered, self.cuda_download = hotwords, [], 0, False

        def resolve_device(self, log=None):
            return "cuda", None

        def transcribe(self, wav, language=None):
            calls.append(self.hotwords)
            return Transcript("en", "atrapa:cuda", [Segment(1, 3, "Start with Agria potatoes")])
    monkeypatch.setattr(pl, "WhisperEngine", FakeWhisper)
    monkeypatch.setattr(ocr, "read_captions", lambda *a, **k: [OcrLine(1.0, 3.0, "start with agria potatoes", 0.95)])
    monkeypatch.setattr(ocr, "ensure_models", lambda root, log=None: root)
    got = []
    out = pl.analyze("https://youtube.com/shorts/x", pl.Options(out_root=tmp_path / "w", ollama_host=ollama, vision="brak",
                     summary="brak", translate=[], on_partial=lambda k, d: got.append(d) if k == "transkrypcja" else None),
                     log=lambda m: None)
    r = json.loads((out / "analiza.json").read_text(encoding="utf-8"))
    assert len(calls) == 1 and "agria" in calls[0].lower()
    assert r["transkrypcja"]["segmenty"][0]["text"] == "Start with Agria potatoes"
    assert "grilled" in got[0]["segmenty"][0]["text"]                            # podgląd z YouTube był od razu


@pytest.mark.skipif(os.name != "nt", reason="tylko Windows")
def test_power_throttling_disabled_on_windows():
    from vidsum.tools import disable_power_throttling
    assert disable_power_throttling() is True


def test_vision_model_preloaded_before_frames(tmp_path, ollama):
    """Model obrazu wczytuje się w tle (pusty /api/generate) zanim przyjdzie pierwszy kadr."""
    main(["--bez-ocr", str(FILM), "-o", str(tmp_path), "--napisy", str(NAPISY), "--ollama", ollama,
          "--model-obrazu", "fake-vl", "--max-kadrow", "4", "--streszczenie", "brak", "--tlumacz", "brak"])
    idx_pre = next(i for i, c in enumerate(FakeOllama.calls) if c.get("keep_alive") == "10m" and "messages" not in c)
    idx_img = next(i for i, c in enumerate(FakeOllama.calls) if c.get("messages") and c["messages"][0].get("images"))
    assert idx_pre < idx_img
    img = FakeOllama.calls[idx_img]
    assert img["options"]["num_predict"] == 400


def test_targeted_hotwords_from_real_fries_ocr():
    """Regresja (0.7.3): podpowiedź z samych napisów małymi literami wyłączała interpunkcję w transkrypcji."""
    from vidsum.ocr import OcrLine, hotwords_targeted
    lines = [OcrLine(0, 1, "this is it", .9), OcrLine(4.5, 6, "start with agria potatoes", .96),
             OcrLine(52, 53, "heat the oil up to 190°C", .93), OcrLine(55, 56, "sprinkle of maldon salt", .96)]
    first = "This is it. Start with the grill potatoes. Heat the oil up to 190. Finish with a sprinkle of molden."
    h = hotwords_targeted(lines, "The Perfect French Fry", first)
    assert h == "The Perfect French Fry. Start with agria potatoes. Heat the oil up to 190°C. Sprinkle of maldon salt."
    assert hotwords_targeted(lines[:1], None, first) == ""                 # nic nowego → bez drugiego przebiegu z podpowiedzią


def test_correct_from_captions_only_clear_cases():
    """Dane z analizy z komputera testowego (0.7.5): poprawiamy „Steering” i „chocolate”, nic więcej."""
    from vidsum.ocr import OcrLine, correct_from_captions
    from vidsum.transcribe import Segment
    segs = [Segment(6.56, 8.95, "particular potato variety is a very high"),
            Segment(26.11, 27.79, "Which is going to help them to fluff and break down."),
            Segment(28.43, 29.19, "Which is going to season them."),
            Segment(46.91, 48.33, "Steering constantly for ruffled edges."),
            Segment(54.85, 56.19, "Finish with a sprinkle of maldon chocolate.")]
    lines = [OcrLine(7.0, 8.5, "variety has a very", 0.94), OcrLine(8.5, 9.5, "high starch content", 0.95),
             OcrLine(9.5, 10.0, "and a very low", 0.9), OcrLine(26.5, 27.5, "to help them to fluff", 0.95),
             OcrLine(28.5, 29.5, "to season them", 0.93), OcrLine(47.0, 47.5, "stirring constantly for", 0.94),
             OcrLine(55.0, 56.5, "sprinkle of maldon salt", 0.96), OcrLine(52.0, 53.5, "heat the oil up to 190°C", 0.93)]
    fixes = correct_from_captions(segs, lines)
    assert [(f["bylo"], f["jest"]) for f in fixes] == [("Steering", "Stirring"), ("chocolate", "salt")]
    assert segs[3].text == "Stirring constantly for ruffled edges."
    assert segs[4].text == "Finish with a sprinkle of maldon salt."
    assert segs[0].text.endswith("very high") and "help" in segs[1].text and "season" in segs[2].text


def test_free_vram_without_nvidia_smi(monkeypatch):
    import shutil
    from vidsum.cuda import free_vram_mb
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert free_vram_mb() is None


def test_vision_bench_three_modes(tmp_path, ollama, monkeypatch):
    """--pomiar-kadrow: te same kadry trzema sposobami, wynik w folderze analizy."""
    monkeypatch.setenv("OLLAMA_NUM_PARALLEL", "2")
    rc = main(["--bez-ocr", str(FILM), "-o", str(tmp_path / "w"), "--ollama", ollama, "--model-obrazu", "fake-vl",
               "--streszczenie", "brak", "--tlumacz", "brak"])
    assert rc == 0
    folder = _only_dir(tmp_path / "w")
    from vidsum.vision_bench import run
    monkeypatch.setenv("OLLAMA_HOST", ollama)
    FakeOllama.calls = []
    out = run(folder, model="fake-vl", host=ollama, log=lambda s: None)
    r = json.loads((folder / "pomiar_kadrow.json").read_text(encoding="utf-8"))
    n = len(json.loads((folder / "analiza.json").read_text(encoding="utf-8"))["kadry"])
    assert set(r) == {"teraz", "schemat", "2w1"} and all(len(v["opisy"]) == n for v in r.values())
    assert any(isinstance(c.get("format"), dict) and "kadr_1" in c["format"]["properties"] for c in FakeOllama.calls)
    assert "| 2w1 |" in out.read_text(encoding="utf-8") and r["schemat"]["zgodnosc_slow_z_teraz"] == 1.0


# ---------------- 0.7.8: kroki zakotwiczone w liniach mowy ----------------
FRY = [  # fragment frytek (mowa z komputera testowego, 0.7.7)
    {"start": 38.89, "end": 39.67, "text": "Heat oil in a pot."},
    {"start": 39.81, "end": 41.21, "text": "We've got some duck fat too for flavour."},
    {"start": 41.39, "end": 43.67, "text": "And once it reaches around about 140 degrees."},
    {"start": 44.01, "end": 45.03, "text": "We're going to drop in our fries."},
    {"start": 50.03, "end": 51.07, "text": "And freeze or chill again."},
    {"start": 52.11, "end": 53.01, "text": "Heat the oil up to 190."},
    {"start": 53.41, "end": 54.63, "text": "Fry until golden and crispy."},
    {"start": 54.85, "end": 56.19, "text": "Finish with a sprinkle of maldon salt."},
]


class _Eng:
    """Atrapa modelu: linia po linii według słownika {oryginał: odpowiedź} (pierwsza i kolejne próby osobno)."""
    parallel = 1

    def __init__(self, first: dict, again: dict | None = None, stages=None, ingr=None):
        self.first, self.again, self.stages, self.ingr, self.prompts, self.seen = first, again or {}, stages, ingr, [], set()

    def complete(self, prompt, as_json=False):
        self.prompts.append(prompt)
        if prompt.startswith("Lines of a video transcript"):
            return json.dumps(self.ingr or {"skladniki": [], "sprzet": []}, ensure_ascii=False)
        if prompt.startswith("You turn numbered lines"):
            out = {}
            for m in re.finditer(r"^(\d+)\. (.*?)(?:   \[SCREEN: .*\])?$", prompt.split("LINES:")[1], re.M):
                src = m.group(2)
                ans = self.again.get(src, self.first.get(src, "")) if src in self.seen else self.first.get(src, "")
                self.seen.add(src)
                out[m.group(1)] = ans
            return json.dumps(out, ensure_ascii=False)
        if prompt.startswith("Kroki z filmu"):
            return json.dumps(self.stages or {}, ensure_ascii=False)
        return "{}"


def test_speech_lines_attach_screen_text():
    from vidsum.summary import speech_lines
    lines = speech_lines(FRY, [{"start": 52.0, "end": 53.5, "text": "heat the oil up to 190°C"}])
    assert [l["n"] for l in lines] == list(range(1, 9))
    assert lines[5]["ekran"] == ["heat the oil up to 190°C"] and not lines[4]["ekran"]


FIRST = {"Heat oil in a pot.": "Rozgrzej olej w garnku.",
         "We've got some duck fat too for flavour.": "Wyjaśnienie: tłuszcz z kaczki dodaje smaku.",
         "And once it reaches around about 140 degrees.": "Poczekaj, aż osiągnie 190 stopni.",      # zła liczba (0.7.7)
         "We're going to drop in our fries.": "Wrzuć frytki.",
         "And freeze or chill again.": "Zamroź albo schłodź ponownie.",
         "Heat the oil up to 190.": "Heat the oil up to 190.",                                     # po angielsku
         "Fry until golden and crispy.": "",                                                       # pominięta
         "Finish with a sprinkle of maldon salt.": "Posyp solą Maldon."}


def test_grounded_steps_fix_wrong_number_english_and_keep_order():
    from vidsum.summary import grounded_steps, speech_lines
    eng = _Eng(FIRST, again={"And once it reaches around about 140 degrees.": "Poczekaj, aż olej osiągnie około 140 stopni.",
                             "Heat the oil up to 190.": "Rozgrzej olej do 190 stopni."},
               stages={"1": "Pierwsze smażenie", "2": "Pierwsze smażenie", "3": "Gotowanie",   # pojedynczy „wyskok”
                       "4": "Drugie smażenie", "5": "Drugie smażenie"},
               ingr={"skladniki": [{"nazwa": "sól Maldon", "ilosc": "świeżo zmielona"},
                                   {"nazwa": "papryka", "ilosc": "2 łyżki"}], "sprzet": ["garnek", "papierowy ręcznik"]})
    g = grounded_steps(eng, speech_lines(FRY), "przepis", "")
    texts = [s["tekst"] for s in g["kroki"]]
    # „And once it reaches 140” (po linii-wyjaśnieniu o tłuszczu z kaczki) dokleja się do „Rozgrzej olej”
    assert texts == ["Rozgrzej olej w garnku, poczekaj, aż olej osiągnie około 140 stopni.", "Wrzuć frytki.",
                     "Zamroź albo schłodź ponownie.", "Rozgrzej olej do 190 stopni.", "Posyp solą Maldon."]
    t140 = g["kroki"][0]["t"]
    t190 = g["kroki"][3]["t"]
    assert t140 < 44 < 52 <= t190
    assert g["wyjasnienia"][0]["tekst"] == "tłuszcz z kaczki dodaje smaku."
    assert g["skladniki"] == [{"nazwa": "sól Maldon", "ilosc": "brak danych", "zrodlo": "mowa"}]   # bez zmyśleń
    assert g["sprzet"] == ["garnek"]
    assert sum(p.startswith("You turn numbered lines") for p in eng.prompts) == 2   # druga runda raz


def test_repair_cannot_invent_numbers():
    from vidsum.summary import grounded_steps, speech_lines
    bad = {"And once it reaches around about 140 degrees.": "Rozgrzej olej do 180 stopni przez 5 minut."}
    g = grounded_steps(_Eng(bad, again=bad), speech_lines(FRY[:3]), "przepis", "")
    assert not any("180" in s["tekst"] for s in g["kroki"])


def test_still_wrong_falls_back_to_polish_translation_line():
    from vidsum.summary import grounded_steps, looks_foreign, speech_lines
    assert looks_foreign("Then boil the fries until just tender") and not looks_foreign("Gotuj frytki do miękkości.")
    lines = speech_lines(FRY[5:7], pl=["Rozgrzej olej do 190 stopni.", "Smaż, aż będą złote i chrupiące."])
    eng = _Eng({"Heat the oil up to 190.": "Heat the oil up to 190.", "Fry until golden and crispy.": "Smaż na złoto."})
    g = grounded_steps(eng, lines, "poradnik", "")
    assert [s["tekst"] for s in g["kroki"]] == ["Rozgrzej olej do 190 stopni.", "Smaż na złoto."]


def test_chapters_follow_stage_changes():
    from vidsum.summary import chapters_from_steps
    steps = [{"t": 13, "tekst": "Obierz.", "etap": "Przygotowanie"}, {"t": 18, "tekst": "Namocz.", "etap": "Przygotowanie"},
             {"t": 24, "tekst": "Zagotuj wodę z sodą.", "etap": "Gotowanie"}, {"t": 39, "tekst": "Rozgrzej olej do 140.", "etap": "Pierwsze smażenie"},
             {"t": 50, "tekst": "Zamroź.", "etap": "Drugie smażenie"}, {"t": 53, "tekst": "Smaż na złoto.", "etap": "Drugie smażenie"}]
    ch = chapters_from_steps(steps, 58.31)
    assert [c["tytul"] for c in ch] == ["Wstęp", "Przygotowanie", "Gotowanie", "Pierwsze smażenie", "Drugie smażenie"]
    assert ch[0]["start"] == 0 and ch[-1]["end"] == 58.31
    assert all(a["end"] == b["start"] for a, b in zip(ch, ch[1:]))
    assert "Smaż na złoto" in ch[-1]["opis"]


def test_drop_sentences_with_numbers_not_in_video():
    from vidsum.summary import drop_unsupported_numbers, reading_seconds, target_words
    s = {"teza": "Frytki smażone dwa razy.", "streszczenie": ["Smaż w 140 stopniach. Potem 180 stopni przez 3 minuty.",
                                                               "Na koniec 190 stopni."],
         "najwazniejsze": [{"opis": "Ziemniaki gotuj 10 minut."}]}
    n = drop_unsupported_numbers(s, "around about 140 degrees. Heat the oil up to 190. two")
    assert s["streszczenie"] == ["Smaż w 140 stopniach.", "Na koniec 190 stopni."] and s["najwazniejsze"] == [] and n == 2
    assert reading_seconds({"streszczenie": ["słowo " * 190]}) == 60
    assert target_words(1000) == 270 and target_words(50) == 120


def test_staged_summary_grounded_path_end_to_end():
    from vidsum.summary import staged_summary
    first = {**FIRST, "And once it reaches around about 140 degrees.": "Poczekaj, aż olej osiągnie 140 stopni.",
             "Heat the oil up to 190.": "Rozgrzej olej do 190 stopni.", "Fry until golden and crispy.": "Smaż na złoto."}

    class E(_Eng):
        def complete(self, prompt, as_json=False):
            if prompt.startswith("Fragment transkrypcji"):
                return '{"typ": "przepis (gotowanie)"}'                   # tak odpowiadała gemma3:4b
            if prompt.startswith(("Kroki z filmu", "Lines of a video", "You turn")):
                return super().complete(prompt, as_json)
            if '"streszczenie"' in prompt.split("Odpowiedz WYŁĄCZNIE JSON-em:")[-1]:
                return json.dumps({"tytul": "Frytki", "teza": "Dwa smażenia.", "streszczenie": ["Smaż w 140, potem w 190 stopniach.", "Olej 175 stopni."],
                                   "do_zapamietania": "Dwa smażenia.", "najwazniejsze": []}, ensure_ascii=False)
            if prompt.startswith("Jesteś asystentem"):
                return json.dumps({"cytaty": [{"t": 52, "tekst": "Heat the oil up to 190."}], "pytania": ["?"],
                                   "rozdzialy": [{"start": 38, "tytul": "Rozgrzewanie oleju"}, {"start": 50, "tytul": "Drugie smażenie"},
                                                 {"start": 55, "tytul": "Parowanie"}]},   # ostatni nie pasuje do kroku
                                  ensure_ascii=False)
            return super().complete(prompt, as_json)

    got = {}
    eng = E(first, stages={"1": "Pierwsze smażenie", "2": "Pierwsze smażenie", "3": "Pierwsze smażenie",
                           "4": "Drugie smażenie", "5": "Drugie smażenie", "6": "Drugie smażenie"})
    s = staged_summary(eng, "[39s] MOWA: Heat oil in a pot.", "", 58.31, segments=FRY,
                       on_partial=lambda k, v: got.setdefault(k, v))
    assert s["metoda"] == "kroki z linii mowy" and s["typ"] == "przepis"
    assert len(s["co_masz_zrobic"]["kroki"]) == 6 and "kroki" in got
    assert s["streszczenie"] == ["Smaż w 140, potem w 190 stopniach."]            # zdanie ze 175 usunięte
    # rozdział przypięty do kroku po treści: „Drugie smażenie” startuje przy „Smaż na złoto” (53 s), a nie przy czasie 50
    assert [c["tytul"] for c in s["rozdzialy"]] == ["Wstęp", "Rozgrzewanie oleju", "Drugie smażenie"]
    assert s["rozdzialy"][2]["start"] == 53.41
    assert s["co_masz_zrobic"]["wskazowki"] == ["tłuszcz z kaczki dodaje smaku."] and s["czas_czytania_s"] > 0


def test_fix_terms_baking_soda_only_when_source_says_so():
    from vidsum.summary import fix_terms
    assert fix_terms("Dodaj proszek do pieczenia.", "Add baking soda.") == "Dodaj sodę oczyszczoną."
    assert fix_terms("Proszek do pieczenia pomoże.", "Add baking soda.") == "Soda oczyszczona pomoże."
    assert fix_terms("Dodaj proszek do pieczenia.", "Add baking powder.") == "Dodaj proszek do pieczenia."
    assert fix_terms("Dodanie sodы pomaga.", "") == "Dodanie sody pomaga."
    assert fix_terms("Smaż w oleju (duck fat).", "duck fat") == "Smaż w oleju (tłuszcz z kaczki)."


def test_every_line_is_sent_to_the_model_once():
    """Błąd znaleziony na prawdziwym modelu: krótka końcówka nadpisywała pierwszą część (pierwsze 20 linii znikały)."""
    from vidsum.summary import grounded_steps, speech_lines
    names = [f"Line {chr(97 + i // 26)}{chr(97 + i % 26)} here" for i in range(44)]     # bez liczb (bez drugiej rundy)
    segs = [{"start": float(i), "end": i + 0.9, "text": n} for i, n in enumerate(names)]
    eng = _Eng({})
    grounded_steps(eng, speech_lines(segs), "przepis", "")
    sent = [m for p in eng.prompts if p.startswith("You turn")
            for m in re.findall(r"^\d+\. (Line \w+ here)", p.split("LINES:")[1], re.M)]
    assert sorted(sent) == names


def test_summary_text_has_a_fallback_when_model_loops():
    """Pomiar (gemma3:4b): opis całości potrafił zapętlić się dwa razy — wtedy krótsze polecenie bez zapisu."""
    from vidsum.summary import staged_summary

    class E(_Eng):
        def complete(self, prompt, as_json=False, **kw):
            if prompt.startswith("Fragment transkrypcji"):
                return '{"typ": "przepis"}'
            if prompt.startswith(("Kroki z filmu", "Lines of a video", "You turn")):
                return super().complete(prompt, as_json)
            if "ZAPIS (czas" not in prompt and '"streszczenie"' in prompt:
                return json.dumps({"teza": "Dwa smażenia.", "streszczenie": ["Najpierw 140, potem 190 stopni."]}, ensure_ascii=False)
            return ""                                                      # pełne polecenie: pusto (zapętlenie)

    first = {**FIRST, "And once it reaches around about 140 degrees.": "Poczekaj, aż olej osiągnie 140 stopni.",
             "Heat the oil up to 190.": "Rozgrzej olej do 190 stopni."}
    s = staged_summary(E(first), "[39s] MOWA: Heat oil in a pot.", "", 58.31, segments=FRY)
    assert s["streszczenie"] == ["Najpierw 140, potem 190 stopni."] and s["teza"] == "Dwa smażenia."


def test_ingredients_keep_potato_starch_and_fix_names():
    """0.7.9 na karcie: skrobia ziemniaczana wypadała jako „duplikat” ziemniaków, „sol” i „malon sól”."""
    from vidsum.summary import grounded_steps, speech_lines
    segs = [{"start": 1.0, "end": 2.0, "text": "Start with agria potatoes."},
            {"start": 3.0, "end": 4.0, "text": "Drain just lightly with potato starch."},
            {"start": 5.0, "end": 6.0, "text": "Finish with a sprinkle of maldon salt."}]
    eng = _Eng({"Start with agria potatoes.": "Zacznij od ziemniaków agria.",
                "Drain just lightly with potato starch.": "Oprósz lekko skrobią ziemniaczaną.",
                "Finish with a sprinkle of maldon salt.": "Posyp solą Maldon."},
               ingr={"skladniki": [{"nazwa": "ziemniaki", "ilosc": "brak danych"},
                                   {"nazwa": "skrobia ziemniaczana", "ilosc": "brak danych"},
                                   {"nazwa": "malon sol", "ilosc": "brak danych"}], "sprzet": []})
    names = [x["nazwa"] for x in grounded_steps(eng, speech_lines(segs), "przepis", "")["skladniki"]]
    assert names == ["ziemniaki", "skrobia ziemniaczana", "sól Maldon"]


def test_highlight_snaps_to_step_with_its_number():
    from vidsum.summary import snap_highlights
    steps = [{"t": 39.0, "tekst": "Rozgrzej olej do 140 stopni."}, {"t": 52.0, "tekst": "Rozgrzej olej do 190 stopni."}]
    got = snap_highlights([{"t": 140, "tytul": "Temperatura", "opis": "Smaż w 190 stopniach."}], steps, 58.3)
    assert got[0]["t"] == 52.0                                       # model wpisał 140 jako czas (0.8.0: 00:58)


def test_neighbouring_note_fragments_are_joined():
    from vidsum.summary import merge_notes
    got = merge_notes([{"z": [6], "tekst": "Posiada bardzo wysoką zawartość skrobi."},
                       {"z": [7], "tekst": "I bardzo niską zawartość wody."}, {"z": [27], "tekst": "To doda warstwę."}])
    assert [g["tekst"] for g in got] == ["Posiada bardzo wysoką zawartość skrobi, bardzo niską zawartość wody.",
                                         "To doda warstwę."]


def test_gpu_snapshot_parses_nvidia_smi(monkeypatch):
    import subprocess
    from vidsum import cuda
    table = """|    0   N/A  N/A            9440    C+G   C:\\Windows\\explorer.exe               N/A      |
|    0   N/A  N/A           15828    C+G   ...s\\Mozilla Firefox\\firefox.exe      N/A      |
|    0   N/A  N/A           15829    C+G   ...s\\Mozilla Firefox\\firefox.exe      N/A      |
|    0   N/A  N/A           12345      C   ...\\ollama\\llama-server.exe         3120MiB |"""

    def run(args, **kw):
        out = "NVIDIA GeForce RTX 3070 Ti, 8192, 1772, 6420\n" if len(args) > 1 else table
        return subprocess.CompletedProcess(args, 0, out, "")
    monkeypatch.setattr(cuda.shutil if hasattr(cuda, "shutil") else __import__("shutil"), "which", lambda n: "nvidia-smi")
    monkeypatch.setattr(subprocess, "run", run)
    g = cuda.gpu_snapshot()
    assert g["karta"] == "NVIDIA GeForce RTX 3070 Ti" and g["zajete_mb"] == 1772 and g["wolne_mb"] == 6420
    assert [p["nazwa"] for p in g["programy"]] == ["explorer.exe", "firefox.exe", "llama-server.exe"]
    assert g["programy"][2]["pamiec_mb"] == 3120


def test_resources_section_in_report():
    from vidsum.pipeline import _resources_md
    z = {"przed": {"karta": "RTX", "pamiec_mb": 8192, "zajete_mb": 1772, "wolne_mb": 6420,
                   "programy": [{"nazwa": "firefox.exe", "pamiec_mb": None}]},
         "w_trakcie": {"najmniej_wolnej_mb": 920, "najwiecej_zajetej_mb": 7272},
         "modele": {"opis_kadrow": [{"model": "qwen3-vl:4b-instruct", "rozmiar_mb": 5100, "na_karcie_proc": 82}]}}
    md = "\n".join(_resources_md(z))
    assert "zajęte **1772 MB**" in md and "na karcie 82% (reszta na procesorze" in md and "firefox.exe" in md
    assert "⚠" in md and _resources_md(None) == []


def test_polish_number_inflection_counts_as_number():
    """Pomiar 0.8.1: „Około jednego centymetra kwadratowego.” (mowa: „Roughly one centimetre square.”) wyglądało
    na zgubioną liczbę 1 i krok z 1 cm odpadał."""
    from vidsum.summary import _nums, check_step
    assert "1" in _nums("Około jednego centymetra kwadratowego.")
    assert {"2", "5"} <= _nums("Smaż przez dwóch minut, potem pięciu")
    assert check_step("Około jednego centymetra kwadratowego.", [1], {1: {"tekst": "Roughly one centimetre square.", "ekran": []}}) \
        == (set(), set())


def test_par_fry_is_not_steaming():
    """Pomiar 0.8.1: model tłumaczył par-fry jako „parzenie”/„parowanie” (= na parze). Poprawka tylko, gdy w filmie
    padło par-fry i nie ma mowy o parze."""
    from vidsum.summary import fix_terms
    src = "And par-fry them. Or blanch them."
    assert fix_terms("a następnie parzenie i smażenie", src) == "a następnie wstępne smażenie i smażenie"
    assert fix_terms("znaczenie parowania frytek", src) == "znaczenie wstępnego smażenia frytek"
    assert fix_terms("Parowanie frytek", src) == "Wstępne smażenie frytek"
    assert fix_terms("parzenie", "Steam them for ten minutes") == "parzenie"


def test_quick_preview_on_text_model_before_frames(tmp_path, ollama, monkeypatch):
    """0.8.2 „Szybki podgląd”: wstępne streszczenie z mowy na modelu TEKSTOWYM (pomiar: model obrazu pisał „marchewka”
    zamiast „ziemniaki”), PRZED opisem kadrów (oba modele naraz nie mieszczą się na karcie 8 GB), potem pełne;
    wynik zapisuje, po ilu sekundach podgląd był gotowy."""
    import vidsum.pipeline as pl
    import vidsum.ocr as ocr
    from vidsum.llm import VISION_CTX
    from vidsum.transcribe import Segment, Transcript

    class FakeWhisper:
        def __init__(self, *a, hotwords=None, **k):
            self.hotwords, self.coverage_hints, self.recovered, self.cuda_download = hotwords, [], 0, False

        def resolve_device(self, log=None):
            return "cuda", None

        def transcribe(self, wav, language=None):
            return Transcript("pl", "atrapa:cuda", [Segment(1, 3, "Pokrój cebulę i wlej mleko"),
                                                    Segment(9, 12, "Mieszaj pięć minut na małym ogniu")])
    monkeypatch.setattr(pl, "WhisperEngine", FakeWhisper)
    monkeypatch.setattr(ocr, "read_captions", lambda *a, **k: [])
    monkeypatch.setattr(ocr, "ensure_models", lambda root, log=None: root)
    got = []
    opt = pl.Options(out_root=tmp_path, ollama_host=ollama, vision_model="fake-vl", text_model="fake-txt",
                     max_frames=3, translate=[], preview=True, on_partial=lambda k, d: got.append((k, d)))
    out = pl.analyze(str(DATA / "Filmy testowe ąęś" / "przepis z mową.mp4"), opt, log=lambda m: None)
    kinds = [k for k, _ in got]
    assert "wstepne" in kinds
    if "kroki" in kinds:
        assert kinds.index("wstepne") < kinds.index("kroki")
    w = dict(got)["wstepne"]
    assert w["wstepne"] is True and w["streszczenie"] and w["metoda"].startswith("szybki podgląd")
    calls = [c for c in FakeOllama.calls if c.get("messages")]
    qi = [i for i, c in enumerate(calls) if "QUICK PRELIMINARY" in c["messages"][0]["content"]]
    assert len(qi) == 1 and calls[qi[0]]["model"] == "fake-txt" and calls[qi[0]]["options"]["num_ctx"] != VISION_CTX
    first_frame = next(i for i, c in enumerate(calls) if c["messages"][0].get("images"))
    assert qi[0] < first_frame                                          # podgląd przed opisem kadrów
    # 0.8.3: model obrazu NIE jest wczytywany przed podglądem (wypychał go model tekstowy i wczytywał się drugi raz)
    every = FakeOllama.calls
    q_all = next(i for i, c in enumerate(every) if c.get("messages") and "QUICK PRELIMINARY" in c["messages"][0]["content"])
    assert all(c.get("model") != "fake-vl" for c in every[:q_all])
    # OCR włączony → lekki opis kadru: bez przepisywania napisów, krótsze listy
    fr = calls[first_frame]
    assert "tekst_na_ekranie" not in fr["format"]["properties"] and fr["format"]["properties"]["obiekty"]["maxItems"] == 5
    r = json.loads((out / "analiza.json").read_text(encoding="utf-8"))
    assert r["podglad"]["po_s"] > 0 and r["streszczenie"]["dane"].get("wstepne") is None   # pełne zastąpiło wstępne
    assert "Szybki podgląd" in (out / "raport.md").read_text(encoding="utf-8")


def test_no_quick_preview_when_switch_off(tmp_path, ollama):
    import vidsum.pipeline as pl
    out = pl.analyze(str(DATA / "bez_audio.mp4"), pl.Options(out_root=tmp_path, ollama_host=ollama, vision_model="fake-vl",
                                                            text_model="fake-txt", max_frames=3, translate=[], ocr=False),
                     log=lambda m: None)
    assert not [c for c in FakeOllama.calls if c.get("messages") and "QUICK" in c["messages"][0]["content"]]
    assert json.loads((out / "analiza.json").read_text(encoding="utf-8"))["podglad"] is None


def test_quick_summary_guards_numbers_and_long_transcripts():
    from vidsum.summary import quick_lines, quick_summary
    segs = [{"start": 1, "text": "Smaż w oleju w 140 stopniach."}]

    class E:
        def complete(self, prompt, as_json=False, **kw):
            self.kw = kw
            return json.dumps({"tytul": "Frytki", "teza": "Frytki smażone dwa razy.",
                               "streszczenie": ["Smaż w 140 stopniach. Potem w 200 stopniach."],
                               "najwazniejsze": [{"t": 1, "tytul": "Olej", "opis": "140 stopni."}]})
    e = E()
    d = quick_summary(e, segs, "", 60, num_ctx=3072)
    assert d["wstepne"] and d["streszczenie"] == ["Smaż w 140 stopniach."]      # 200 nie padło w filmie
    assert e.kw["num_ctx"] == 3072 and d["czas_czytania_s"] > 0
    long = [{"start": i, "text": "słowo " * 15} for i in range(600)]
    txt, cut = quick_lines(long, 5000)
    assert cut and len(txt) <= 5000 and txt.startswith("[0s]") and "[5" in txt.splitlines()[-1][:3]
    assert quick_summary(e, [], "", 60) is None


def test_measured_083_term_fixes():
    """Pomiar 0.8.2 u użytkownika: „posypaniem miodnym solą”, „Miód z solą Maldon”, „parować/blanszować”,
    „Wyrzuć frytki” (drop in), „Usuń je” (remove them); „Agria” + „ziemniaki” jako dwa składniki."""
    from vidsum.summary import _fix_name, _merge_variety, fix_terms
    src = ("We're going to drop in our fries. And par-fry them. Remove them. "
           "Finish with a sprinkle of maldon salt.")
    assert fix_terms("Zakończ posypaniem miodnym solą.", src) == "Zakończ posypaniem solą Maldon."
    assert fix_terms("Miód z solą Maldon", src) == "Sól Maldon"
    assert fix_terms("parować/blanszować w oleju", src) == "wstępnie smażyć/blanszować w oleju"
    assert fix_terms("Wyrzuć frytki.", src) == "Wrzuć frytki."
    assert fix_terms("Usuń je.", src) == "Wyjmij je."
    assert fix_terms("Usuń nadmiar skrobi.", src) == "Usuń nadmiar skrobi."
    assert fix_terms("Dodaj miód.", "Add honey and maldon salt") == "Dodaj miód."         # miód jest w filmie
    assert fix_terms("Wyrzuć skórki.", "Throw away the peel") == "Wyrzuć skórki."        # bez „drop in”
    assert _fix_name("Maldon salt", "maldon") == "sól Maldon"
    m = _merge_variety([{"nazwa": "Agria", "ilosc": "brak danych"}, {"nazwa": "ziemniaki", "ilosc": "brak danych"},
                        {"nazwa": "sól", "ilosc": "brak danych"}])
    assert [x["nazwa"] for x in m] == ["ziemniaki agria", "sól"]



def test_frame_count_scales_with_short_videos():
    """0.8.3: do 2 min kadr na ~4 s (10–20). Pomiar 0.8.2: 20 kadrów dla 58 s, sąsiednie prawie identyczne."""
    from vidsum.media import plan_for
    assert [plan_for(d).max_frames for d in (20, 58, 80, 120, 300)] == [10, 15, 20, 20, 45]
    assert plan_for(58, 30).max_frames == 30                               # ręczny limit wygrywa


def test_vision_answer_dedupes_repeated_actions():
    from vidsum.llm import _clean_vision
    v = _clean_vision({"scena": "Kucharz wyciera miskę.", "czynnosci": ["wycieranie", "wycieranie", "trzymanie miski"],
                       "obiekty": ["miska"], "cialo": "", "pewnosc": "wysoka"})
    assert v["czynnosci"] == ["wycieranie", "trzymanie miski"] and v["tekst_na_ekranie"] == []


def test_quotes_get_exact_text_and_time_from_transcript():
    """Pomiar 0.9.0: „This will add a beautiful crispy layer.” przy 0:13 (w filmie: „This is going to add…” przy 0:34)."""
    from vidsum.summary import verify_quotes
    segs = json.loads((Path(__file__).parent / "bench" / "data" / "frytki_077.json").read_text(encoding="utf-8"))["segmenty"]
    d = {"cytaty": [{"t": 13, "tekst": "This will add a beautiful crispy layer.", "tlumaczenie": "To doda…"},
                    {"t": 13, "tekst": "To add a beautiful crisping layer."},
                    {"t": 5, "tekst": "This is it. This is the perfect French fry."},
                    {"t": 1, "tekst": "Fry them in honey for ten minutes."}]}
    assert verify_quotes(d, segs) == 1                                    # zmyślony (miód) usunięty
    assert [(q["t"], q["tekst"]) for q in d["cytaty"]] == [
        (34.13, "This is going to add a beautiful crispy layer."),        # dokładny tekst i czas, bez duplikatu
        (0.0, "This is it. This is the perfect French fry.")]             # bez doklejania następnego zdania
    assert d["cytaty"][0]["tlumaczenie"] == "To doda…"


def test_false_missing_claims_are_removed():
    """Pomiar 0.9.0 (dwa przebiegi): „brakuje … dokładnej temperatury oleju”, a kroki mają 140 i 190 stopni."""
    from vidsum.summary import drop_false_missing
    todo = {"kroki": [{"tekst": "Rozgrzej olej do 140 stopni."}, {"tekst": "Rozgrzej olej do 190 stopni."}], "skladniki": []}
    d = {"co_masz_zrobic": todo,
         "szczera_ocena": "Dobry przepis. Jednak brakuje informacji o czasie smażenia, proporcjach składników oraz "
                          "dokładnej temperaturze oleju. Film skupia się na technice.",
         "czego_nie_wiadomo": ["Nie podano temperatury oleju.", "Czy smażyć w wysokiej temperaturze oleju (190°C) dłużej.",
                               "Nie podano temperatury, czasu ani ilości."]}
    assert drop_false_missing(d) == 3
    assert d["szczera_ocena"] == ("Dobry przepis. Jednak brakuje informacji o czasie smażenia, proporcjach składników. "
                                  "Film skupia się na technice.")
    assert d["czego_nie_wiadomo"] == ["Czy smażyć w wysokiej temperaturze oleju (190°C) dłużej.",   # cytuje liczbę
                                      "Nie podano czasu ani ilości."]
    d2 = {"co_masz_zrobic": {"kroki": [{"tekst": "Smaż na złoto."}]}, "szczera_ocena": "Brakuje temperatury oleju."}
    assert drop_false_missing(d2) == 0 and d2["szczera_ocena"] == "Brakuje temperatury oleju."    # naprawdę brak


def test_measured_091_term_fixes():
    from vidsum.summary import fix_terms
    src = "And par-fry them. Or blanch them."
    assert fix_terms("gotuj z sodą i parz/blanszuj w oleju.", src) == "gotuj z sodą i wstępnie smaż/blanszuj w oleju."
    assert fix_terms("o odpowiednim parowaniu w oleju", src) == "o odpowiednim wstępnym smażeniu w oleju"
    assert fix_terms("wstępnie smażyć/blanshować", src) == "wstępnie smażyć/blanszować"
    assert fix_terms("parz herbatę", src) == "parz herbatę"


def test_leftover_models_from_previous_analysis_are_freed(tmp_path, ollama, monkeypatch):
    """Pomiar 0.9.0: gemma z poprzedniej analizy zajmowała 3,1 GB („inne programy: 5515 MB”), model obrazu wczytywał się
    17 s zamiast ~10 s. Teraz: zwolniona na starcie, a raport mówi, co to było."""
    import vidsum.cuda as cuda
    import vidsum.pipeline as pl
    monkeypatch.setattr(cuda, "gpu_snapshot", lambda: {"karta": "RTX test", "pamiec_mb": 8192, "zajete_mb": 5515,
                                                       "wolne_mb": 2503, "programy": [{"nazwa": "steam.exe", "pamiec_mb": None}]})
    monkeypatch.setattr(cuda, "ollama_models", lambda host=None: [{"model": "fake-txt", "rozmiar_mb": 3101, "na_karcie_proc": 100}])
    logs: list[str] = []
    out = pl.analyze(str(DATA / "bez_audio.mp4"), pl.Options(out_root=tmp_path, ollama_host=ollama, vision_model="fake-vl",
                                                            text_model="fake-txt", max_frames=3, translate=[], ocr=False),
                     log=logs.append)
    calls = FakeOllama.calls
    free = next(i for i, c in enumerate(calls) if c.get("model") == "fake-txt" and c.get("keep_alive") == 0)
    first_img = next(i for i, c in enumerate(calls) if c.get("messages") and c["messages"][0].get("images"))
    assert free < first_img
    assert any("z poprzedniej analizy: fake-txt (3101 MB)" in m for m in logs)
    assert any("inne programy zajmują 2414 MB" in m for m in logs)          # 5515 − 3101: tylko naprawdę inne programy
    rep = (out / "raport.md").read_text(encoding="utf-8")
    assert "modele z poprzedniej analizy (zwolnione na starcie): `fake-txt` 3101 MB; inne programy **2414 MB**" in rep


def test_chat_prompt_uses_transcript_and_steps_not_whole_summary():
    """Pomiar 0.9.0: na „strzelanina w krakowie” czat wkleił całe streszczenie, a na „ile minut gotować” zmyślił
    „20–25 minut”. Teraz: transkrypcja z czasami i kroki zamiast markdownu, reguły i przykłady dla tych przypadków."""
    from vidsum.summary import _guess_lang, build_chat_prompt, check_chat_answer
    a = {"zrodlo": {"tytul": "The Perfect French Fry", "autor": "Fallow"},
         "transkrypcja": {"segmenty": [{"start": 29.3, "text": "Then boil the fries until just tender."},
                                       {"start": 52.1, "text": "Heat the oil up to 190."}]},
         "napisy_ekranowe": [{"text": "heat the oil up to 190°C"}],
         "streszczenie": {"markdown": "## W skrócie\nCAŁE STRESZCZENIE", "dane": {
             "teza": "Frytki smażone dwa razy.", "co_masz_zrobic": {"kroki": [{"t": 52.1, "tekst": "Rozgrzej olej do 190 stopni."}]}}}}
    p = build_chat_prompt(a, "ile minut gotować?", [])
    assert "CAŁE STRESZCZENIE" not in p and "[00:29] Then boil the fries" in p and "- 00:52 Rozgrzej olej" in p
    assert "Polish" in p and "does NOT give" in p
    assert _guess_lang("strzelanina w krakowie") == "pl" and _guess_lang("what is french fry") == "en"
    warned = check_chat_answer("Gotowanie frytek trwa około 20-25 minut.", a)
    assert "Tej liczby nie ma w filmie" in warned
    ok = "Olej rozgrzej do 190 stopni (00:52)."
    assert check_chat_answer(ok, a) == ok                                   # liczba jest w filmie
    gen = "Wiedza ogólna (nie z filmu): frytki smaży się zwykle 5 minut."
    assert check_chat_answer(gen, a) == gen                                 # oznaczona wiedza ogólna


def test_automatic_preview_only_when_it_costs_nothing(tmp_path, ollama, monkeypatch):
    """0.10.0: bez przełącznika. Inny model obrazu niż tekstowy → bez wstępnego streszczenia (przerzucanie modeli
    kosztowało +16 s); ten sam model (albo obraz wyłączony) → wstępne streszczenie od razu."""
    import vidsum.pipeline as pl
    from vidsum import ocr
    from vidsum.transcribe import Transcript

    class FakeWhisper:
        def __init__(self, *a, hotwords=None, **k):
            self.hotwords, self.coverage_hints, self.recovered, self.cuda_download = hotwords, [], 0, False

        def resolve_device(self, log=None):
            return "cuda", None

        def transcribe(self, wav, language=None):
            return Transcript("pl", "atrapa:cuda", [Segment(1, 3, "Pokrój cebulę i wlej mleko"),
                                                    Segment(9, 12, "Mieszaj pięć minut na małym ogniu")])
    monkeypatch.setattr(pl, "WhisperEngine", FakeWhisper)
    monkeypatch.setattr(ocr, "read_captions", lambda *a, **k: [])
    monkeypatch.setattr(ocr, "ensure_models", lambda root, log=None: root)
    film = str(DATA / "Filmy testowe ąęś" / "przepis z mową.mp4")
    got: list = []
    o = dict(out_root=tmp_path, ollama_host=ollama, text_model="fake-txt", max_frames=3, translate=[], ocr=False,
             on_partial=lambda k, d: got.append(k))
    pl.analyze(film, pl.Options(vision_model="fake-vl", **o), log=lambda m: None)
    assert "wstepne" not in got
    got.clear()
    pl.analyze(film, pl.Options(vision="brak", **o), log=lambda m: None)
    assert "wstepne" in got
    # 0.10.1: kadry na innym modelu → mały kontekst; na tym samym co tekst → kontekst tekstu (bez przeładowań w Ollamie)
    from vidsum.llm import TEXT_CTX, VISION_CTX
    ctx = lambda: {c["options"]["num_ctx"] for c in FakeOllama.calls
                   if c.get("messages") and c["messages"][0].get("images")}
    FakeOllama.calls.clear()
    pl.analyze(film, pl.Options(vision_model="fake-vl", **o), log=lambda m: None)
    assert ctx() == {VISION_CTX}
    FakeOllama.calls.clear()
    got.clear()
    pl.analyze(film, pl.Options(vision_model="fake-txt", **o), log=lambda m: None)
    assert ctx() == {TEXT_CTX} and "wstepne" in got


def test_author_description_chapters_and_comments_parsing():
    """0.10.0: opis i rozdziały od autora z informacji yt-dlp; komentarze: odpowiedzi na końcu, najpopularniejsze
    najpierw, puste pominięte."""
    from vidsum.fetch import author_chapters, parse_comments
    info = {"chapters": [{"start_time": 0, "end_time": 61.25, "title": "Start"},
                         {"start_time": 61.25, "end_time": 238.0, "title": " Smażenie "}, {"title": "zły"}]}
    assert author_chapters(info) == [{"start": 0.0, "end": 61.2, "tytul": "Start"},
                                     {"start": 61.2, "end": 238.0, "tytul": "Smażenie"}]
    assert author_chapters({}) is None
    raw = [{"author": "@a", "text": "ok", "like_count": 3, "parent": "root"},
           {"author": "@b", "text": "super", "like_count": 40, "parent": "root"},
           {"author": "@c", "text": "racja", "like_count": 99, "parent": "abc"},
           {"author": "@d", "text": "  ", "like_count": 500, "parent": "root"}]
    got = parse_comments(raw, limit=10)
    assert [c["autor"] for c in got] == ["@b", "@a", "@c"] and got[2]["odpowiedz"] is True
    assert len(parse_comments(raw, limit=1)) == 1
