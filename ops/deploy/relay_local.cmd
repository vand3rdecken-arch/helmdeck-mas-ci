@echo off
rem Local relay fallback: relay.py :6790 + cloudflared tunnel (helmdeck-relay).
rem Was registered as HKCU Run "HelmDeckRelay" (owner-approved 2026-09-08).
rem SUPERSEDED 2026-09-22: surfaces/desktop/tray.py supervises both (hidden,
rem logged, respawned) and removes that Run entry. Keep this only as a manual
rem fallback when the tray is not running - it opens two console windows.
cd /d "%~dp0..\.."
start "helmdeck-relay" /min py -3.12 surfaces\relay\relay.py
start "helmdeck-relay-tunnel" /min "%USERPROFILE%\bin\cloudflared.exe" tunnel run helmdeck-relay
