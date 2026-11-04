"""Faza 7: pobieranie bibliotek CUDA (atrapy paczek z lokalnego serwera — bez internetu i bez GPU)."""
from __future__ import annotations

import functools
import hashlib
import http.server
import os
import threading
import zipfile
from pathlib import Path

import pytest

from vidsum import cuda


@pytest.fixture()
def fake_pack(tmp_path):
    srv_dir = tmp_path / "serwer"
    srv_dir.mkdir()
    specs = [("nvidia_cublas_cu12-1-py3-none-win_amd64.whl", "nvidia/cublas/bin/",
              ["cublas64_12.dll", "cublasLt64_12.dll"]),
             ("nvidia_cudnn_cu12-1-py3-none-win_amd64.whl", "nvidia/cudnn/bin/",
              ["cudnn64_9.dll", "cudnn_ops64_9.dll"])]
    for whl, prefix, dlls in specs:
        with zipfile.ZipFile(srv_dir / whl, "w") as z:
            for d in dlls:
                z.writestr(prefix + d, b"MZ" + d.encode() * 1000)
            z.writestr(prefix.replace("bin/", "include/") + "x.h", "nie kopiować")
            z.writestr(prefix + "README.txt", "nie kopiować")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(srv_dir))
    handler.log_message = lambda *a: None  # type: ignore[attr-defined]
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"
    pack = []
    for whl, prefix, _ in specs:
        data = (srv_dir / whl).read_bytes()
        pack.append({"pakiet": whl.split("-")[0], "wersja": "1", "rozmiar": len(data),
                     "sha256": hashlib.sha256(data).hexdigest(), "url": base + whl, "katalog": prefix})
    yield pack
    srv.shutdown()


def test_pack_versions_match_ctranslate2():
    """Wersje bibliotek dobrane do CTranslate2 4.8 (CUDA 12, cuDNN 9) i przypięte sumami SHA-256."""
    import ctranslate2
    assert ctranslate2.__version__.startswith("4.")
    names = {p["pakiet"]: p for p in cuda.PACK}
    assert names["nvidia-cublas-cu12"]["wersja"].startswith("12.")
    assert names["nvidia-cudnn-cu12"]["wersja"].startswith("9.")
    for p in cuda.PACK:
        assert len(p["sha256"]) == 64 and p["url"].startswith("https://files.pythonhosted.org/")
        assert p["url"].endswith("win_amd64.whl")
    assert 1.0 < cuda.pack_size_gb() < 1.5


def test_download_extract_activate(tmp_path, fake_pack, monkeypatch):
    d = tmp_path / "app ąę" / "cuda"
    logs: list[str] = []
    assert not cuda.installed(d, fake_pack) and not cuda.activate(d, fake_pack)
    cuda.ensure(logs.append, d, fake_pack, force_platform=True)
    assert cuda.installed(d, fake_pack)
    files = sorted(p.name for p in d.iterdir())
    assert files == ["cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll", "cudnn_ops64_9.dll", "gotowe.json"]
    assert any("%" in m for m in logs)                                     # postęp w logu
    monkeypatch.setenv("PATH", "x")
    assert cuda.activate(d, fake_pack)
    assert os.environ["PATH"].split(os.pathsep)[0] == str(d.resolve())
    # druga wersja paczki = trzeba pobrać ponownie
    newer = [dict(p, wersja="2") for p in fake_pack]
    assert not cuda.installed(d, newer)
    # brakujący plik = niekompletna instalacja
    (d / "cudnn64_9.dll").unlink()
    assert not cuda.installed(d, fake_pack)


def test_bad_checksum_is_rejected(tmp_path, fake_pack):
    bad = [dict(fake_pack[0], sha256="0" * 64)]
    with pytest.raises(cuda.CudaError, match="suma kontrolna"):
        cuda.ensure(print, tmp_path / "c", bad, force_platform=True)
    assert not list((tmp_path / "c").rglob("*.dll")) and not list((tmp_path / "c").rglob("*.whl"))


@pytest.mark.skipif(os.name == "nt", reason="na Windows pobieranie jest właściwą ścieżką")
def test_non_windows_refuses_download(tmp_path):
    with pytest.raises(cuda.CudaError, match="tylko na Windows"):
        cuda.ensure(print, tmp_path / "c")


def test_whisper_device_downloads_when_gpu_present(tmp_path, monkeypatch):
    """Jest karta NVIDIA, brak bibliotek → pobranie → GPU; awaria pobierania → CPU z jasną uwagą."""
    from vidsum import transcribe
    from vidsum.transcribe import WhisperEngine
    state = {"missing": ["cublas64_12.dll"], "ensured": 0}
    monkeypatch.setattr(cuda, "gpu_count", lambda: 1)
    monkeypatch.setattr(transcribe, "_missing_cuda_libs", lambda: list(state["missing"]))

    def ok(log, *a, **k):
        state["ensured"] += 1
        state["missing"] = []
        return tmp_path
    monkeypatch.setattr(cuda, "ensure", ok)
    e = WhisperEngine("tiny")
    e.cuda_download = True
    assert e.resolve_device() == ("cuda", None) and state["ensured"] == 1
    assert e.resolve_device() == ("cuda", None) and state["ensured"] == 1   # wynik zapamiętany

    state["missing"] = ["cublas64_12.dll"]

    def fail(log, *a, **k):
        raise cuda.CudaError("Za mało miejsca na dysku")
    monkeypatch.setattr(cuda, "ensure", fail)
    e = WhisperEngine("tiny")
    e.cuda_download = True
    dev, note = e.resolve_device()
    assert dev == "cpu" and "Za mało miejsca" in note and "--pobierz-cuda" in note

    e = WhisperEngine("tiny")                       # pobieranie wyłączone → CPU bez prób
    dev, note = e.resolve_device()
    assert dev == "cpu" and "brak bibliotek CUDA" in note


def test_no_gpu_means_cpu_without_download(monkeypatch):
    from vidsum.transcribe import WhisperEngine
    monkeypatch.setattr(cuda, "gpu_count", lambda: 0)
    monkeypatch.setattr(cuda, "ensure", lambda *a, **k: pytest.fail("nie powinno pobierać"))
    e = WhisperEngine("tiny")
    e.cuda_download = True
    assert e.resolve_device() == ("cpu", None)
