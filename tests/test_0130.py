"""0.13.0: nazwa „Vidsumly” wszędzie — foldery danych, pliki wydania, klucz w Menedżerze poświadczeń."""
import json
from pathlib import Path


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
