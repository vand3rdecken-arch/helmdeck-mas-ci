# HelmDeck - Windows installer build (one command).
#
#   powershell -ExecutionPolicy Bypass -File build-win.ps1
#   powershell -ExecutionPolicy Bypass -File build-win.ps1 -Version 0.2.2
#
# Produces:  release\HelmDeck-Setup-<version>-x64.exe
#
# -Version stamps the installer/app version WITHOUT editing package.json (the
# committed version can lag the released one - 0.2.1 was built from a committed
# 0.2.0). Omit it to use package.json's version. deploy/release_desktop.sh
# passes this so a GitHub release gets the right filename + auto-update version.
#
# It works around electron-builder's winCodeSign cache, which contains macOS
# symlinks that fail to extract on Windows unless the user has the symlink
# privilege (Developer Mode / elevated). We pre-extract that cache WITHOUT the
# darwin symlinks, so the build no longer needs the privilege. If you already
# have Developer Mode on, this step is harmless.
#
# Requirements on this machine (same as HelmDeck): Python 3.12 + the `claude` CLI.
param([string]$Version = "")
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

# The window/installer icon (assets\icon.ico) is git-ignored - generated from
# the tracked icon-1024.png. Regenerate it on a clean checkout, else NSIS dies
# with "cannot find specified resource assets/icon.ico".
if (-not (Test-Path "assets\icon.ico")) {
  Write-Host "==> generating assets\icon.ico (tools\make_icon.py)"
  py -3.12 (Join-Path $PSScriptRoot "..\tools\make_icon.py")
  if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }
}

Write-Host "==> building the UI (Expo web export) + the NSIS installer"
npm run build:web
if ($LASTEXITCODE -ne 0) { throw "web export failed" }
# -Version -> electron-builder extraMetadata override, so the installer name +
# app version reflect the release without a committed package.json bump. NB:
# electron-builder REWRITES package.json in place when extraMetadata is set
# (drops scripts/devDependencies) - snapshot it and restore it afterward so a
# release build never corrupts the source tree.
$ebArgs = @("--win", "--config", "electron-builder.yml")
$pkgBak = $null
if ($Version) {
  $ebArgs += "-c.extraMetadata.version=$Version"
  $pkgBak = [IO.File]::ReadAllText("package.json")
}
try {
  npx electron-builder @ebArgs
  if ($LASTEXITCODE -ne 0) { throw "electron-builder failed" }
} finally {
  if ($pkgBak -ne $null) { [IO.File]::WriteAllText("package.json", $pkgBak) }
}

Write-Host ""
Write-Host "DONE. Installer -> release\ (HelmDeck-Setup-<version>-x64.exe)"
Get-ChildItem "release\*.exe" -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $($_.FullName)" }
