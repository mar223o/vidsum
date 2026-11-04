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
    assert len(imgs) == len(r["kadry"]) and imgs[0]["format"] == "json"
    assert any(c.get("keep_alive") == 0 for c in FakeOllama.calls)          # zwolnienie VRAM
    prompt = (out / "prompt_dla_claude.md").read_text(encoding="utf-8")
    assert "[mowa]" in prompt and "brak danych" in prompt and "Teraz wlewamy" in prompt
    md = (out / "raport.md").read_text(encoding="utf-8")
    assert "## W skrócie" in md and "(z mowy)" in md and "(z obrazu" in md
    assert "⏱ Czas analizy:" in md and "kadry " in md                     # czas w raporcie
    assert "## Tłumaczenie: angielski" in md and "oryginał: polski" in md
    assert (out / "transkrypcja.srt").read_text(encoding="utf-8").startswith("1\n00:00:00,500 --> 00:00:06,000")


def test_vision_failure_does_not_abort(tmp_path, ollama):
    """Awaria modelu na jednym kadrze (np. brak pamięci): ponowna próba, potem 'brak danych'."""
    FakeOllama.fail_images = {2, 3, 4}   # kadr 2: obie próby padają; kadr 3: druga próba OK
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
    assert len(e.prompts) >= 3                                                 # ≥2 porcje + opis
    c = d["co_masz_zrobic"]
    assert d["typ"] == "przepis" and d["tytul"] == "Frytki"
    assert [k["t"] for k in c["kroki"]] == sorted(k["t"] for k in c["kroki"]) and len(c["kroki"]) == len(e.prompts) - 1
    assert c["skladniki"] == [{"nazwa": "ziemniaki", "ilosc": "brak danych", "zrodlo": "mowa"}]   # bez dubli z porcji
    assert c["wskazowki"] == ["nie przypal"]


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
