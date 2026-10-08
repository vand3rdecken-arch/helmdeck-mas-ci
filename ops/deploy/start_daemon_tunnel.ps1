# Keeps the HelmDeck daemon reachable for the glasses (Glance worker) and the watch:
# the named tunnel `daemon-origin.helmdeck.de` -> http://localhost:8140.
#
# WHY THIS EXISTS (2026-10-08): the tunnel had been down since 2026-09-21 and the
# lens showed no history / board / rooms - every request ended in Cloudflare error
# 1033. Nothing started it at logon. The Glance worker's DAEMON_URL secret is
# https://daemon-origin.helmdeck.de; this script is the process behind it.
#
# Idempotent: does nothing when a cloudflared for this config already runs.
# Autostart: a one-line .cmd in the Startup folder calls this file
# (shell:startup\helmdeck-daemon-tunnel.cmd).
$cf  = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$cfg = Join-Path $env:USERPROFILE ".cloudflared\daemon-origin.yml"
$id  = "7bfa7a98-53bd-41ff-86fd-b7738c7620c8"
$log = Join-Path $PSScriptRoot "..\..\daemon\daemon_origin_tunnel.log"

$running = Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" |
    Where-Object { $_.CommandLine -like "*daemon-origin.yml*" }
if ($running) { Write-Output "daemon tunnel already running (pid $($running.ProcessId))"; exit 0 }

# the config path contains spaces: it must travel inside quotes
$argline = "tunnel --config `"$cfg`" run $id"
Start-Process -FilePath $cf -ArgumentList $argline -WindowStyle Hidden `
    -RedirectStandardError $log -RedirectStandardOutput "$log.out" | Out-Null
Write-Output "daemon tunnel started"
