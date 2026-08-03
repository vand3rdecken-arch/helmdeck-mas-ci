@echo off
rem HelmDeck daemon — launch the capture + control + review server.
rem Prints the LAN address you type into the phone app (Pair) and the glasses viewer.
cd /d "%~dp0"
if not exist ".venv" ( echo Run setup.bat first. & pause & exit /b 1 )
call .venv\Scripts\activate.bat

echo === HelmDeck daemon ===
echo Pair the phone / open the glasses viewer at:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
  for /f "tokens=* delims= " %%b in ("%%a") do echo    http://%%b:8140
)
echo    (or http://localhost:8140 in this PC's browser)
echo.
python swarm.py serve 8140
