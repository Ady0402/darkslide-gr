@echo off
rem Darkslide launcher for Windows (needs Python 3.9+)
cd /d "%~dp0"
where py >nul 2>nul && (py -3 launcher.py %*) || (python launcher.py %*)
pause
