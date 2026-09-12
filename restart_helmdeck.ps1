# HelmDeck - FORWARDER ONLY. The real script is ops/tools/restart_helmdeck.ps1.
#
# Why this file exists in the repo root (2026-09-12): the HelmDeckRestart
# scheduled task was registered from an elevated session and its action points
# HERE; a non-elevated session gets "Access is denied" on /Change, /Create /F
# and /Delete (measured). Rather than leave an untracked Aug-30 copy of the old
# logic in place, this stub forwards every argument to the tracked script.
# Re-point the task from an admin shell when convenient, then delete this file:
#   schtasks /Change /TN HelmDeckRestart /TR "powershell.exe -ExecutionPolicy Bypass -File \"<repo>\ops\tools\restart_helmdeck.ps1\" -DelaySeconds 90"
param([int]$DelaySeconds = 90, [int]$UpTimeoutSec = 120)
$real = Join-Path $PSScriptRoot 'ops\tools\restart_helmdeck.ps1'
& powershell.exe -ExecutionPolicy Bypass -File $real -DelaySeconds $DelaySeconds -UpTimeoutSec $UpTimeoutSec
exit $LASTEXITCODE
