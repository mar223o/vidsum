@echo off
rem VidSum — wariant bez PyInstallera: oficjalny, podpisany Python z python.org.
rem Bez argumentow: interfejs w przegladarce. Z argumentami: wiersz polecen.
chcp 65001 >nul
set PYTHONUTF8=1
"%~dp0python\python.exe" -m vidsum %*
