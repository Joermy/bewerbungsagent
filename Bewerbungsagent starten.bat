@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Lege Python-Umgebung an ...
    python -m venv .venv || goto :fehler
    ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -q -e ".[mcp,dev]" || goto :fehler
)

if not exist "config.yaml" (
    echo config.yaml fehlt - Vorlage config.example.yaml kopieren und anpassen.
    copy /-Y "config.example.yaml" "config.yaml" >nul
)

".venv\Scripts\python.exe" -m bewerbungsagent status
echo.
".venv\Scripts\python.exe" -m bewerbungsagent app
goto :eof

:fehler
echo.
echo Einrichtung fehlgeschlagen. Ist Python 3.11+ installiert und auf PATH?
pause
