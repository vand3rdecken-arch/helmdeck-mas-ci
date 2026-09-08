@echo off
rem Local relay fallback: relay.py :6790 + cloudflared tunnel (helmdeck-relay).
rem Registered as HKCU Run "HelmDeckRelay" (owner-approved 2026-09-08).
cd /d "%~dp0..\.."
start "helmdeck-relay" /min py -3.12 surfaces\relay\relay.py
start "helmdeck-relay-tunnel" /min "%USERPROFILE%\bin\cloudflared.exe" tunnel run helmdeck-relay
