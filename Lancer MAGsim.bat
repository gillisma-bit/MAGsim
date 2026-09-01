@echo off
cd /d "%~dp0"
call .venv\Scripts\activate
python main.py
if errorlevel 1 (
    echo.
    echo === ERREUR au demarrage ===
    pause
)
