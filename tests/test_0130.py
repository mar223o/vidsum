"""0.13.0: nazwa „Vidsumly” wszędzie, imiona, fakty, cytaty, plik dla LLM, fiszki."""
import json
from pathlib import Path

from test_gui import server  # noqa: F401  (fikstura serwera GUI)


def test_data_folder_moved_from_old_name(tmp_path, monkeypatch):
    from vidsum import paths
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    old = tmp_path / "local" / "VidSum"
    (old / "modele").mkdir(parents=True)
    (old / "ustawienia.json").write_text('{"jezyk": "pl"}', encoding="utf-8")
    got = paths.app_dir()
    assert got == tmp_path / "local" / "Vidsumly" and not old.exists()
    assert json.loads((got / "ustawienia.json").read_text(encoding="utf-8")) == {"jezyk": "pl"}, "dane przeniesione, nie skasowane"
    assert (got / "modele").is_dir()


def test_new_folder_wins_and_old_is_left_alone(tmp_path):
    from vidsum.paths import migrate
    old, new = tmp_path / "VidSum", tmp_path / "Vidsumly"
    old.mkdir(); new.mkdir(); (old / "a.txt").write_text("x")
    assert migrate(old, new) == new and (old / "a.txt").exists(), "gdy są oba, nic nie ruszamy"
    assert migrate(tmp_path / "brak", tmp_path / "nowy") == tmp_path / "nowy"


def test_busy_old_folder_keeps_being_used(tmp_path, monkeypatch):
    from vidsum.paths import migrate
    old, new = tmp_path / "VidSum", tmp_path / "Vidsumly"
    old.mkdir()

    def busy(self, target):
        raise PermissionError("plik zajęty")

    monkeypatch.setattr(Path, "rename", busy)
    assert migrate(old, new) == old, "nie udało się przenieść — program dalej używa starego folderu, nic nie ginie"


def test_results_folder_moved_and_saved_paths_fixed(tmp_path, monkeypatch):
    from vidsum import paths
    home = tmp_path / "home"
    (home / "Documents" / "VidSum" / "Film_1").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    app = tmp_path / "local" / "Vidsumly"
    app.mkdir(parents=True)
    old_res = str(home / "Documents" / "VidSum")
    (app / "ustawienia.json").write_text(json.dumps({"wyniki": old_res}), encoding="utf-8")
    (app / "kolejka.json").write_text(json.dumps([{"wyniki": old_res + "\\Film_1"}]), encoding="utf-8")
    got = paths.default_results_dir()
    assert got == home / "Documents" / "Vidsumly" and (got / "Film_1").is_dir()
    assert json.loads((app / "ustawienia.json").read_text(encoding="utf-8"))["wyniki"] == str(got)
    assert str(got) in json.loads((app / "kolejka.json").read_text(encoding="utf-8"))[0]["wyniki"]


def test_update_finds_new_and_old_release_file_names():
    from vidsum.update import asset_names
    new = {"Vidsumly-0.13.0-aktualizacja.zip": 1, "Vidsumly-Setup-0.13.0.exe": 1}
    assert asset_names("0.13.0", new)[2] == "Vidsumly-Setup-0.13.0.exe"
    old = {"VidSum-0.12.0-aktualizacja.zip": 1, "VidSum-0.12.0-aktualizacja.json": 1, "VidSum-Setup-0.12.0.exe": 1}
    assert asset_names("0.12.0", old) == ("VidSum-0.12.0-aktualizacja.zip", "VidSum-0.12.0-aktualizacja.json",
                                          "VidSum-Setup-0.12.0.exe")


def test_no_old_name_left_in_user_visible_places():
    root = Path(__file__).parents[1]
    allowed = {"vidsum/paths.py", "vidsum/update.py", "packaging/vidsum.iss", "vidsum/gui.py", "vidsum/web/index.html",
               ".github/workflows/windows.yml", "tests/test_0130.py"}
    hits = []
    for p in [*root.glob("vidsum/**/*.py"), *root.glob("vidsum/web/*.html"), *root.glob("packaging/*"), *root.glob("docs/*.md"),
              root / "README.md", *root.glob("skill/**/*.md"), root / ".github/workflows/windows.yml"]:
        rel = p.relative_to(root).as_posix()
        if not p.is_file() or rel in allowed or rel.startswith("docs/STAN_0.11") or p.suffix in (".ico", ".png"):
            continue
        if "VidSum" in p.read_text(encoding="utf-8", errors="ignore"):
            hits.append(rel)
    assert not hits, hits
    iss = (root / "packaging" / "vidsum.iss").read_text(encoding="utf-8-sig")
    assert "OutputBaseFilename=Vidsumly-Setup-" in iss and "DefaultDirName={localappdata}\\Programs\\Vidsumly" in iss
    assert "UsePreviousAppDir=no" in iss and 'Name: "{localappdata}\\Programs\\VidSum"' in iss
    wf = (root / ".github/workflows/windows.yml").read_text(encoding="utf-8")
    assert '$old = "VidSum-Setup-$ver.exe"' in wf and "$env:SETUP_OLD" in wf, "kopia instalatora dla aktualizacji z 0.12.0"
    assert (root / "packaging" / "Vidsumly.cmd").is_file() and (root / "packaging" / "Vidsumly Start.cmd").is_file()


def test_user_run_0120_names_facts_quotes():
    """Analiza dokumentu na 0.12.0 u użytkownika (13.11): „Michał chce postawić…”, fakt „Praktycznie zdarza się to tylko
    wtedy…”, cytat „Something like data?”. Te same odpowiedzi modelu, nowy kod."""
    from test_0120 import replay
    from vidsum.story import localize
    from vidsum.translate import restore_names
    d, s, eng, log = replay("dokument_ambasada_0120")
    pl = [{**p, "text": restore_names(p["text"], " ".join(x["text"] for x in d["segmenty"]))} for p in d["pl"]]
    localize(s, d["segmenty"], pl)
    blob = json.dumps(s, ensure_ascii=False)
    assert "Michał" not in blob, "imię z oryginału"
    assert "Michael chce postawić zakład w kwocie 420 milionów funtów" in blob
    facts = [f["oryginal"] for f in s["co_masz_zrobic"]["fakty"]]
    assert not any(f.startswith("In practice, that tends") for f in facts)
    assert any("343 million" in f for f in facts) and any("54 overseas police" in f for f in facts)
    assert not any(q["tekst"] == "Something like data?" for q in s["cytaty"])
    assert sum(q["tekst"].rstrip().endswith("?") for q in s["cytaty"]) <= 1
    assert s["reklamy"] and s["reklamy"][0]["marka"] == "Delete Me"


def test_llm_file_has_legend_line_refs_and_numbered_transcript():
    from vidsum.note import llm_text
    d = json.loads((Path(__file__).parent / "data" / "frytki_0114" / "analiza.json").read_text(encoding="utf-8"))
    t = llm_text(d)
    assert t.startswith("---\ntytul: ") and "## Jak czytać ten plik" in t and "[obraz] = automatyczny opis kadru" in t
    segs = d["transkrypcja"]["segmenty"]
    assert f"[L1 00:{int(segs[0]['start']):02d}] {segs[0]['text'].strip()}" in t
    assert f"[L{len(segs)} " in t, "każda linia transkrypcji ma numer"
    import re
    steps = re.findall(r"^\d+\. \[L\d+ \d\d:\d\d\] ", t, re.M)
    assert len(steps) == len(d["streszczenie"]["dane"]["co_masz_zrobic"]["kroki"]), "każdy krok z odwołaniem do linii"
    assert "![" not in t and "Zasoby komputera" not in t


def test_gui_writes_and_serves_llm_file(server):
    """Analiza z GUI zapisuje dla_llm.md; endpoint /dla_llm buduje plik z analiza.json (działa też dla starszych analiz)."""
    from test_gui import DATA, req, wait_done
    base, app = server
    _, job = req(base, "/api/link", data=json.dumps({"zrodlo": str(DATA / "bez_audio.mp4")}).encode(), method="POST")
    assert wait_done(base, job["id"])["status"] == "gotowe"
    out = app.worker.jobs[job["id"]].out
    assert (out / "dla_llm.md").is_file()
    (out / "dla_llm.md").unlink()                      # jak w analizie sprzed 0.13.0
    st, body = req(base, f"/api/zadania/{job['id']}/dla_llm")
    assert st == 200 and "## Jak czytać ten plik" in body.decode("utf-8")
    st, body = req(base, f"/api/zadania/{job['id']}/notatka")
    assert st == 200 and body.decode("utf-8").startswith("Notatka z analizy")


def test_index_has_llm_button_flashcards_and_map_facts():
    html = (Path(__file__).parents[1] / "vidsum" / "web" / "index.html").read_text(encoding="utf-8")
    for k in ('data-a="llm"', "/dla_llm?pobierz=1", "function flashcards(d)", 'tl.push(["cards"', 'data-a="cards_copy"',
              "co_masz_zrobic?.fakty) || []).filter(f => f.t >= ch.start"):
        assert k in html, k
    assert html.count("t_cards:") == 2 and html.count("llm_copied:") == 2


def test_restore_names_only_when_name_in_source():
    from vidsum.translate import restore_names
    src = "Michael wants to bet 420 million pounds. He sends the order to his trader, Nick."
    assert restore_names("Michał chce postawić. Komputer Michała. Wysyła Michałowi.", src) == \
        "Michael chce postawić. Komputer Michaela. Wysyła Michaelowi."
    assert restore_names("Jan poszedł do sklepu.", "Jan went to the shop") == "Jan poszedł do sklepu."
    assert restore_names("Pan Jerzy.", "George said") == "Pan George."
    assert restore_names("Kup jerzyny.", "George said") == "Kup jerzyny."
