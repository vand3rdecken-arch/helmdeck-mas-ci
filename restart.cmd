@echo off
REM HelmDeck - restart the daemon with ONE command.
REM
REM Why this wrapper exists. Restarting the daemon by hand is a four-command
REM ritual with two traps that cost real time (2026-09-02): the schtasks /TR
REM value needs cmd-style \" escaping (PowerShell backticks silently split on
REM the space in "Tien Duy Vo"), and the verify task has to be created AND run
REM separately. Neither is interesting - so they live here instead of in the
REM owner's head.
REM
REM The schtasks indirection itself is NOT incidental and must stay: a card
REM agent runs as a CHILD of the daemon, and the singleton takeover in
REM spine/http/startup.py evicts the old daemon with `taskkill /F /T` whose /T
REM cascades to children. An agent that restarts the daemon from inside that
REM tree kills ITSELF mid-turn. Task Scheduler gives the restart its own
REM parentage, so the eviction can never reach the caller. See the header of
REM restart_helmdeck.ps1.
REM
REM   Usage (from anywhere):  restart.cmd          restart + verify
REM                           restart.cmd /n       restart only, no verify
REM
REM The swap is NOT instant by design: the new daemon holds in singleton grace
REM while any card still has a live turn (a restart is a deploy, a live turn is
REM the owner's running work). Expect the verify log to sit on "waiting for the
REM SINGLETON swap" until those turns end.

setlocal
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

if not exist "%ROOT%\restart_helmdeck.ps1" (
  echo ERROR: restart_helmdeck.ps1 not found next to this script ^(%ROOT%^).
  exit /b 1
)

echo [1/2] scheduling daemon restart ...
schtasks /Create /TN HelmDeckRestart /SC ONCE /ST 23:59 /F /TR "powershell.exe -ExecutionPolicy Bypass -File \"%ROOT%\restart_helmdeck.ps1\"" >nul
if errorlevel 1 ( echo ERROR: could not create the restart task. & exit /b 1 )
schtasks /Run /TN HelmDeckRestart >nul
if errorlevel 1 ( echo ERROR: could not start the restart task. & exit /b 1 )
echo       restart triggered.

if /i "%~1"=="/n" (
  echo Skipping verify ^(/n^). Daemon log: daemon\restart_stdout.log
  exit /b 0
)

echo [2/2] scheduling restart verify ...
schtasks /Create /TN HelmDeckRestartVerify /SC ONCE /ST 23:59 /F /TR "powershell.exe -ExecutionPolicy Bypass -File \"%ROOT%\ops\tools\verify_restart.ps1\"" >nul
if errorlevel 1 ( echo ERROR: could not create the verify task. & exit /b 1 )
schtasks /Run /TN HelmDeckRestartVerify >nul
echo       verify triggered.
echo.
echo Verdict is written to: daemon\restart_verify.log
echo   ^(it waits for the singleton swap - live card turns must end first^)
exit /b 0
