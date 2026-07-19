@echo off
rem SwarmDeck daemon — one-time setup. Requires Python 3.10+ on PATH.
rem Creates a local venv, installs deps, downloads the Playwright browser helper.
cd /d "%~dp0"
echo === SwarmDeck daemon setup ===
where python >nul 2>&1 || (echo Python not found on PATH. Install Python 3.10+ first. & pause & exit /b 1)

if not exist ".venv" (
  echo Creating virtual environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
echo Installing dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
echo Fetching Playwright browser helper (video encoder)...
python -m playwright install ffmpeg
echo.
echo === Setup complete. Run the daemon with:  run.bat ===
pause
