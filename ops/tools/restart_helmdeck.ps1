# HelmDeck - restart the daemon so it imports current main.
#
# The companion verify_restart.ps1 has cited this script since it was written,
# but it never existed - every restart was done by hand. Written 2026-09-02 for
# the queued-turn fix (9eaf0ed), which is daemon-side code and therefore only
# takes effect on a fresh import.
#
# THE CONSTRAINT that shapes this script: the agent asking for the restart is
# itself a child of the daemon, so `taskkill /T` evicts the asker mid-sentence.
# The restart therefore cannot run in the requesting turn - it must be launched
# with its own parentage (schtasks) and wait out the turn before it kills:
#
#   schtasks /Create /TN HelmDeckRestart /SC ONCE /ST 23:59 /F /TR "<pwsh> -File <this> -DelaySeconds 90"
#   schtasks /Run    /TN HelmDeckRestart
#
# Recovery is the TRAY's job, not this script's: surfaces/desktop/tray.py runs a
# health-driven supervisor (_supervise, 4s beat) that adopts a live daemon and
# respawns a dead one. So the normal path here is kill-and-wait. The direct
# spawn below is only the fallback for a box where the tray is not running -
# without it, a restart on such a box would leave the daemon down.
param(
  [int]$DelaySeconds = 90,      # let the requesting card's turn finish first
  [int]$UpTimeoutSec = 120      # how long to wait for the daemon to serve again
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
Set-Location $root

$log = Join-Path $root 'daemon\restart_watch.log'
function Say($msg) {
  $line = "{0}  {1}" -f (Get-Date -Format 'HH:mm:ss'), $msg
  Add-Content -Path $log -Value $line -Encoding utf8
}

function DaemonProcs {
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'daemon\.swarm' }
}
function Healthy {
  # An auth-gated reply IS alive - the daemon answering 401/403 is serving.
  # Only "no reply at all" counts as down (same rule as tray.py's _health).
  try {
    $null = Invoke-WebRequest -Uri 'http://127.0.0.1:8140/health' -UseBasicParsing -TimeoutSec 5
    return $true
  } catch {
    if ($_.Exception.Response.StatusCode.value__) { return $true }
    return $false
  }
}

Say '================ HelmDeck daemon restart ================'
$commit = (git log -1 --format='%h %s' 2>$null)
Say ("target HEAD: {0}" -f $commit)

$before = @(DaemonProcs)
Say ("before     : {0} daemon.swarm process(es)" -f $before.Count)
foreach ($p in $before) { Say ("    pid={0} started {1}" -f $p.ProcessId, $p.CreationDate) }

if ($DelaySeconds -gt 0) {
  Say ("waiting {0}s so the requesting card's turn can finish before the tree-kill..." -f $DelaySeconds)
  Start-Sleep -Seconds $DelaySeconds
}

# Re-read: the daemon may have been restarted by someone else during the wait.
$procs = @(DaemonProcs)
if ($procs.Count -eq 0) {
  Say 'no daemon running - nothing to kill, going straight to the up-check.'
} else {
  foreach ($p in $procs) {
    Say ("tree-killing pid={0} (cascades to its claude.exe children by design)" -f $p.ProcessId)
    & taskkill.exe /F /T /PID $p.ProcessId 2>&1 | ForEach-Object { Say ("    " + $_) }
  }
}

# The tray supervisor should notice within ~4s and respawn. Give it the window
# before doing anything ourselves - a supervised respawn is the correct owner of
# the process, and racing it would produce two daemons fighting over :8140.
Say ("waiting up to {0}s for the tray supervisor to bring it back..." -f $UpTimeoutSec)
$deadline = (Get-Date).AddSeconds($UpTimeoutSec)
$up = $false
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 3
  if (Healthy) { $up = $true; break }
}

if (-not $up) {
  Say 'tray did NOT bring it back (tray.py not running?) - spawning the daemon directly.'
  # Same launch shape as tray.py's _spawn_daemon: module from the REPO ROOT,
  # never a bare script from inside daemon/ (absolute spine/cells imports).
  $py = 'python.exe'
  if ($before.Count -gt 0 -and $before[0].CommandLine -match '^"([^"]+)"') { $py = $matches[1] }
  Say ("    python  : {0}" -f $py)
  # --takeover: the scheduled task is the other explicit restart verb, so it
  # may depose a running daemon. A plain supervisor spawn exits 3 instead
  # (spine/http/startup.py, the daemon mutex).
  Start-Process -FilePath $py -ArgumentList '-m', 'daemon.swarm', 'serve', '--takeover' `
    -WorkingDirectory $root -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $root 'daemon\restart_stdout.log') `
    -RedirectStandardError  (Join-Path $root 'daemon\restart_stderr.log')
  $deadline = (Get-Date).AddSeconds(60)
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    if (Healthy) { $up = $true; break }
  }
}

$after = @(DaemonProcs)
Say ("after      : healthy={0}, {1} daemon.swarm process(es)" -f $up, $after.Count)
foreach ($p in $after) { Say ("    pid={0} started {1}" -f $p.ProcessId, $p.CreationDate) }
if ($after.Count -eq 1 -and $up) {
  Say 'RESULT     : OK - single daemon serving :8140 on current main.'
} elseif (-not $up) {
  Say 'RESULT     : FAILED - nothing is serving :8140. Check daemon/restart_stderr.log and daemon/daemon.out.log.'
} else {
  Say ("RESULT     : NOT SINGLETON - {0} daemons alive. Kill the extras." -f $after.Count)
}
Say '================ done ================'
