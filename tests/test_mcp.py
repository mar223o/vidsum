"""Serwer MCP: prawdziwy proces, rozmowa JSON-RPC przez stdin/stdout, jak robi to Claude Desktop."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

DATA = Path(__file__).parent / "data"


def _rpc(proc, msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if "id" not in msg:
        return None
    return json.loads(proc.stdout.readline())


def test_mcp_protocol_and_tools(tmp_path):
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path / "app"), PYTHONIOENCODING="utf-8")
    (tmp_path / "app" / "VidSum").mkdir(parents=True)
    (tmp_path / "app" / "VidSum" / "ustawienia.json").write_text(json.dumps({"wyniki": str(tmp_path / "wyniki")}))
    proc = subprocess.Popen([sys.executable, "-m", "vidsum", "--mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env,
                            cwd=Path(__file__).parent.parent)
    try:
        r = _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test"}}})
        assert r["result"]["serverInfo"]["name"] == "vidsum" and r["result"]["capabilities"] == {"tools": {}}
        _rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        r = _rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert {t["name"] for t in r["result"]["tools"]} == {"analizuj_film", "lista_analiz", "pobierz_analize"}
        r = _rpc(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "lista_analiz", "arguments": {}}})
        assert "Brak zapisanych analiz" in r["result"]["content"][0]["text"]
        # pełna analiza przez MCP (film bez dźwięku, bez Ollamy → luka w wyniku, ale bez błędu protokołu)
        film = tmp_path / "Mój film.mp4"
        shutil.copy(DATA / "bez_audio.mp4", film)
        r = _rpc(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                        "params": {"name": "analizuj_film", "arguments": {"zrodlo": str(film)}}})
        res = r["result"]
        text = res["content"][0]["text"]
        assert res["isError"] is False, text
        assert "OŚ CZASU" in text and "Mój film.mp4" in text and "Napisz teraz streszczenie" in text
        r = _rpc(proc, {"jsonrpc": "2.0", "id": 41, "method": "tools/call", "params": {"name": "lista_analiz", "arguments": {}}})
        assert "Mój film.mp4" in r["result"]["content"][0]["text"]
        r = _rpc(proc, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                        "params": {"name": "pobierz_analize", "arguments": {"folder": str(tmp_path / "nie_ma")}}})
        assert r["result"]["isError"] is True and "Brak analiza.json" in r["result"]["content"][0]["text"]
        r = _rpc(proc, {"jsonrpc": "2.0", "id": 6, "method": "nieznana"})
        assert r["error"]["code"] == -32601
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
