"""Sprawdzenie na prawdziwym Windows (CI): „Wyczyść bibliotekę” przenosi folder analizy do Kosza systemu.
Uruchomienie: python tests/win_trash_check.py <folder instalacji>"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, sys.argv[1])
from vidsum import trash  # noqa: E402

name = f"vidsumly_kosz_test_{int(time.time())}"
d = Path(tempfile.gettempdir()) / name
d.mkdir()
(d / "analiza.json").write_text("{}", encoding="utf-8")
print("folder:", d, "dysk stały:", trash._has_recycle_bin(d))
where = trash.to_trash(d)
print("gdzie:", where)
assert where == "kosz", where
assert not d.exists(), "folder nadal istnieje"
ps = ("$i=(New-Object -ComObject Shell.Application).NameSpace(10).Items() | Where-Object { $_.Name -eq '%s' };"
      " if ($i) { 'jest' } else { 'brak' }") % name
out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip()
print("w Koszu:", out)
assert out == "jest", "folderu nie ma w Koszu"
print("kosz: ok")
