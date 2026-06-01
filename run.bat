@echo off
REM SpotifyConverter launcher for Windows.
cd /d "%~dp0"

echo ================================
echo   SpotifyConverter
echo ================================

if not exist ".venv\" (
    echo Creating virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    echo Installing dependencies...
    python -m pip install --upgrade pip >nul
    python -m pip install -r requirements.txt
    python setup_ffmpeg.py
) else (
    call .venv\Scripts\activate.bat
)

echo.
echo Opening http://127.0.0.1:8000
start "" http://127.0.0.1:8000
python run.py
pause
