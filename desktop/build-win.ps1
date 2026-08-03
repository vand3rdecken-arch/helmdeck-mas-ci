# HelmDeck - Windows installer build (one command).
#
#   powershell -ExecutionPolicy Bypass -File build-win.ps1
#
# Produces:  release\HelmDeck-Setup-<version>-x64.exe
#
# It works around electron-builder's winCodeSign cache, which contains macOS
# symlinks that fail to extract on Windows unless the user has the symlink
# privilege (Developer Mode / elevated). We pre-extract that cache WITHOUT the
# darwin symlinks, so the build no longer needs the privilege. If you already
# have Developer Mode on, this step is harmless.
#
# Requirements on this machine (same as HelmDeck): Python 3.12 + the `claude` CLI.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> installing electron-builder deps (first run only)"
if (-not (Test-Path "node_modules\electron-builder")) { npm install }

Write-Host "==> preparing winCodeSign cache (skipping macOS symlinks)"
$cache = Join-Path $env:LOCALAPPDATA "electron-builder\Cache\winCodeSign"
$sevenZip = Join-Path $PSScriptRoot "node_modules\7zip-bin\win\x64\7za.exe"
New-Item -ItemType Directory -Force -Path $cache | Out-Null
$arc = Get-ChildItem "$cache\*.7z" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($arc) {
  $dest = Join-Path $cache "winCodeSign-2.6.0"
  if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
  & $sevenZip x $arc.FullName "-o$dest" "-xr!darwin" -y | Out-Null
  Write-Host "    winCodeSign cache prepared."
} else {
  Write-Host "    (winCodeSign not cached yet - electron-builder will fetch it. If the"
  Write-Host "     build then fails on a symlink error, just run this script a 2nd time.)"
}

Write-Host "==> building the UI (Next standalone) + the NSIS installer"
npm run dist:win

Write-Host ""
Write-Host "DONE. Installer -> release\ (HelmDeck-Setup-<version>-x64.exe)"
Get-ChildItem "release\*.exe" -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $($_.FullName)" }
