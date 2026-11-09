"""Aktualizacje: podmiana kodu, sprawdzanie wydania, klucz w Menedżerze poświadczeń (Windows)."""
import io
import json
import os
import zipfile

import pytest

from vidsum import update


def _zip(tmp_path, version, extra=None):
    z = tmp_path / "akt.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("vidsum/__init__.py", f'__version__ = "{version}"\n')
        f.writestr("vidsum/nowy.py", "X = 1\n")
        f.writestr("VidSum Start.cmd", "@echo nowy\n")
        for k, v in (extra or {}).items():
            f.writestr(k, v)
    return z


def test_swap_code_replaces_whole_package_and_keeps_data(tmp_path):
    root = tmp_path / "app"
    (root / "vidsum").mkdir(parents=True)
    (root / "vidsum" / "__init__.py").write_text('__version__ = "0.7.6"\n')
    (root / "vidsum" / "stary_nieuzywany.py").write_text("old\n")       # plik usunięty w nowej wersji
    (root / "dane.txt").write_text("moje")                                 # nie należy do kodu
    update.swap_code(_zip(tmp_path, "0.7.7"), "0.7.7", root)
    assert '0.7.7' in (root / "vidsum" / "__init__.py").read_text()
    assert (root / "vidsum" / "nowy.py").is_file()
    assert not (root / "vidsum" / "stary_nieuzywany.py").exists()          # stary kod nie zostaje
    assert not (root / "vidsum.stare").exists() and (root / "dane.txt").read_text() == "moje"
    assert (root / "VidSum Start.cmd").read_text() == "@echo nowy\n"
    assert not list(root.glob("vidsum_akt_*"))


def test_swap_code_rejects_wrong_version_and_bad_paths(tmp_path):
    root = tmp_path / "app"
    (root / "vidsum").mkdir(parents=True)
    (root / "vidsum" / "__init__.py").write_text('__version__ = "0.7.6"\n')
    with pytest.raises(update.UpdateError):
        update.swap_code(_zip(tmp_path, "0.7.5"), "0.7.7", root)
    assert '0.7.6' in (root / "vidsum" / "__init__.py").read_text()        # nic nie zmienione
    bad = _zip(tmp_path, "0.7.7", {"../poza.txt": "x"})
    with pytest.raises(update.UpdateError):
        update.swap_code(bad, "0.7.7", root)
    assert not (tmp_path / "poza.txt").exists()


def test_check_picks_code_update_only_when_libraries_match(monkeypatch):
    rel = {"tag_name": "v9.9.9", "html_url": "u", "body": "notatki", "assets": [
        {"name": "VidSum-9.9.9-aktualizacja.zip", "url": "A", "size": 3_000_000},
        {"name": "VidSum-9.9.9-aktualizacja.json", "url": "M", "size": 50},
        {"name": "VidSum-Setup-9.9.9.exe", "url": "S", "size": 280_000_000}]}
    deps = {"v": "abc"}

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_open(url, token, accept="", timeout=60):
        assert token == "tok"
        return R(json.dumps(rel if url.endswith("/latest") else {"zaleznosci": deps["v"]}).encode())
    monkeypatch.setattr(update, "_open", fake_open)
    monkeypatch.setattr(update, "can_swap_code", lambda: True)
    monkeypatch.setattr(update, "build_info", lambda: {"zaleznosci": "abc"})
    r = update.check("tok")
    assert r["jest_nowsza"] and r["rodzaj"] == "kod" and r["rozmiar_mb"] == 3.0
    deps["v"] = "inne"                                                      # biblioteki zmienione → pełny instalator
    assert update.check("tok")["rodzaj"] == "pelna"
    rel["tag_name"] = "v0.0.1"
    assert update.check("tok")["jest_nowsza"] is False


def test_redirect_drops_github_key():
    import urllib.request
    h = update._NoAuthOnRedirect()
    req = urllib.request.Request("https://api.github.com/x", headers={"Authorization": "Bearer t"})
    new = h.redirect_request(req, None, 302, "", {}, "https://objects.githubusercontent.com/plik")
    assert "Authorization" not in new.headers and "authorization" not in {k.lower() for k in new.header_items()}


def test_token_format_checked():
    with pytest.raises(update.UpdateError):
        update.token_set("to nie klucz")


@pytest.mark.skipif(os.name != "nt", reason="Menedżer poświadczeń tylko w Windows")
def test_credential_manager_roundtrip(monkeypatch):
    monkeypatch.setattr(update, "CRED_TARGET", "VidSum/test-ci")
    update.token_set("github_pat_" + "A" * 40)
    try:
        assert update.token_get() == "github_pat_" + "A" * 40
    finally:
        update.token_delete()
    assert update.token_get() is None


def test_check_works_without_key_on_public_repo(monkeypatch):
    """Od 0.7.8 repozytorium jest publiczne: bez klucza nie wysyłamy nagłówka Authorization."""
    import urllib.request
    seen = {}

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Op:
        def open(self, req, timeout=60):
            seen["auth"] = req.get_header("Authorization")
            return R(json.dumps({"tag_name": "v0.0.1", "assets": []}).encode())
    monkeypatch.setattr(update, "token_get", lambda: None)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a: Op())
    assert update.check()["jest_nowsza"] is False and seen["auth"] is None
