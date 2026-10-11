@echo off
rem Darkslide on Windows: pick a Python 3.9+ interpreter, then run launcher.py from this folder.
rem Any error launcher.py reports stays on screen; only a missing Python gets the install hint.
rem CALL is used because "python" may be a .bat/.cmd shim (pyenv-win and similar).
setlocal EnableExtensions
set "DS_PY="
call python -c "import sys; raise SystemExit(sys.version_info < (3, 9))" >nul 2>nul && set "DS_PY=python"
if not defined DS_PY call py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 9))" >nul 2>nul && set "DS_PY=py -3"
if not defined DS_PY goto need_python
call %DS_PY% "%~dp0launcher.py" %*
pause
goto :eof

:need_python
echo Python 3.9 or newer was not found on this PC.
echo Install it from https://www.python.org/downloads/ and run start.cmd again.
pause
