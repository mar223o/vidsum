@echo off
rem Vidsumly bez czarnego okna: uruchamia program w tle (pythonw) i od razu zamyka to okno.
rem Program wyłączysz przyciskiem „Zakończ” w przeglądarce. Dziennik: %LOCALAPPDATA%\Vidsumly\vidsumly.log
set PYTHONUTF8=1
start "" "%~dp0python\pythonw.exe" -m vidsum --ui
