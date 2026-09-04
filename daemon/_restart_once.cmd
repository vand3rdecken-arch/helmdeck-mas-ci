@echo off
REM One-shot wrapper for the scheduled daemon restart.
REM schtasks /TR mangles a command line containing both spaces and inner quotes,
REM so the launcher points at THIS file and the quoting lives here. No arguments
REM are passed in - deliberately, it is the .cmd-with-quoted-args shape that eats
REM arguments. Absolute interpreter path because powershell.exe is not reliably
REM on this box's PATH and a spawned process inherits whatever PATH it was given.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\ops\tools\restart_helmdeck.ps1" -DelaySeconds 120
