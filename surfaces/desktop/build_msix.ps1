# HelmDeck - Microsoft Store (MSIX/AppX) build. The Windows twin of
# build-mas.sh: same shell, same daemon, same surfaces/app/dist, DIFFERENT
# packaging (electron-builder.appx.yml - appx target, Store-safe updater/
# autostart guards already wired in main.js via process.windowsStore).
#
#   powershell -ExecutionPolicy Bypass -File build_msix.ps1                  # unsigned test build
#   powershell -ExecutionPolicy Bypass -File build_msix.ps1 -Version 0.2.22  # stamp a release version
#   powershell -ExecutionPolicy Bypass -File build_msix.ps1 -NoWeb           # reuse an existing surfaces/app/dist
#
# Produces in surfaces/desktop/release/: HelmDeck-<version>-x64.appx
#
# UNSIGNED BY DEFAULT, unlike build-mas.sh - and that is fine, not a stop-gap:
# Partner Center signs whatever is uploaded during ingestion, so a local test
# build's only job is to prove the manifest/identity/capabilities are correct.
# electron-builder's own AppxTarget falls back to publisher "CN=ms" with no
# signing certificate present (verified in the installed
# node_modules/app-builder-lib/out/targets/AppxTarget.js), which is exactly
# what an unsigned local build needs.
#
# Identity (identityName/publisher) - Partner Center assigns both once the app
# is registered there (DEPLOY.md 1g). Until then electron-builder.appx.yml
# ships placeholders that build fine locally. Once real values exist, put them
# in a gitignored surfaces/desktop/build/appx-identity.json:
#   { "identityName": "12345Publisher.HelmDeck", "publisher": "CN=...",
#     "publisherDisplayName": "..." }
# or export HELMDECK_APPX_IDENTITY_NAME / HELMDECK_APPX_PUBLISHER /
# HELMDECK_APPX_PUBLISHER_DISPLAY_NAME - either way this script passes them to
# electron-builder as `-c.appx.*` overrides, the same shape build-mas.sh
# already uses for `-c.extraMetadata.version`.
param([string]$Version = "", [switch]$NoWeb)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> installing electron-builder deps (first run only)"
if (-not (Test-Path "node_modules\electron-builder")) { npm install }

# Same winCodeSign symlink workaround as build-win.ps1 - makeappx.exe (what
# actually builds the .appx) ships in the SAME cached bundle as the NSIS
# signing tools, so a fresh machine hits the identical macOS-symlink
# extraction failure here.
Write-Host "==> preparing winCodeSign cache (skipping macOS symlinks)"
$cache = Join-Path $env:LOCALAPPDATA "electron-builder\Cache\winCodeSign"
$sevenZip = Join-Path $PSScriptRoot "node_modules\7zip-bin\win\x64\7za.exe"
New-Item -ItemType Directory -Force -Path $cache | Out-Null
$arc = Get-ChildItem "$cache\*.7z" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($arc) {
  $dest = Join-Path $cache "winCodeSign-2.6.0"
  if (-not (Test-Path (Join-Path $dest "windows-10\x64\makeappx.exe"))) {
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    & $sevenZip x $arc.FullName "-o$dest" "-xr!darwin" -y | Out-Null
  }
  Write-Host "    winCodeSign cache prepared."
} else {
  Write-Host "    (winCodeSign not cached yet - electron-builder will fetch it, which"
  Write-Host "     already contains makeappx.exe; no separate Windows SDK install needed.)"
}

if (-not (Test-Path "assets\icon.ico")) {
  Write-Host "==> generating assets\icon.ico (ops/tools/make_icon.py)"
  py -3.12 (Join-Path $PSScriptRoot "..\..\ops\tools\make_icon.py")
  if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }
}

if (-not $NoWeb) {
  Write-Host "==> building the UI (Expo web export -> surfaces/app/dist)"
  npm run build:web
  if ($LASTEXITCODE -ne 0) { throw "web export failed" }
}
if (-not (Test-Path "..\app\dist")) { throw "surfaces/app/dist missing - drop -NoWeb" }

# Identity overrides: a gitignored build/appx-identity.json wins over env
# vars, which win over the placeholders already in electron-builder.appx.yml.
$identityFile = Join-Path $PSScriptRoot "build\appx-identity.json"
$identityName = $env:HELMDECK_APPX_IDENTITY_NAME
$publisher = $env:HELMDECK_APPX_PUBLISHER
$publisherDisplayName = $env:HELMDECK_APPX_PUBLISHER_DISPLAY_NAME
if (Test-Path $identityFile) {
  $j = Get-Content $identityFile -Raw | ConvertFrom-Json
  if ($j.identityName) { $identityName = $j.identityName }
  if ($j.publisher) { $publisher = $j.publisher }
  if ($j.publisherDisplayName) { $publisherDisplayName = $j.publisherDisplayName }
}

# `--win appx` (not bare `--win`) for the same reason build-mas.sh uses
# `--mac mas` - config-level `win.target` does not replace the base config's
# `[nsis]` via `extends` (electron-builder concatenates extended arrays); CLI
# target selection bypasses that merge.
$ebArgs = @("--win", "appx", "--config", "electron-builder.appx.yml", "--publish", "never")
if ($identityName) { $ebArgs += "-c.appx.identityName=$identityName" }
if ($publisher) { $ebArgs += "-c.appx.publisher=$publisher" }
if ($publisherDisplayName) { $ebArgs += "-c.appx.publisherDisplayName=$publisherDisplayName" }

# electron-builder REWRITES package.json in place when extraMetadata is set -
# snapshot + restore, same trap build-mas.sh/build-win.ps1 already document.
$pkgJsonPath = Join-Path $PSScriptRoot "package.json"
$pkgBak = $null
if ($Version) {
  $ebArgs += "-c.extraMetadata.version=$Version"
  $pkgBak = [IO.File]::ReadAllText($pkgJsonPath)
}

Write-Host "==> npx electron-builder $($ebArgs -join ' ')"
try {
  npx electron-builder @ebArgs
  if ($LASTEXITCODE -ne 0) { throw "electron-builder failed" }
} finally {
  if ($null -ne $pkgBak) { [IO.File]::WriteAllText($pkgJsonPath, $pkgBak) }
}

Write-Host ""
Write-Host "DONE. Artifact -> release\ (HelmDeck-<version>-x64.appx)."
Write-Host "This is UNSIGNED - do not distribute it outside this machine; Partner Center"
Write-Host "signs on upload. Local install test (needs Developer Mode ON):"
Write-Host "  Add-AppxPackage -Path release\HelmDeck-<version>-x64.appx"
Get-ChildItem "release\*.appx" -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Host ("  {0}  ({1:N1} MB)" -f $_.FullName, ($_.Length / 1MB))
}
