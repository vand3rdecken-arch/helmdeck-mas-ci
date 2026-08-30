# HelmDeck - verify a daemon restart from OUTSIDE the daemon's process tree.
#
# Companion to restart_helmdeck.ps1. The swap itself CANNOT be observed by the
# card agent that asked for it: the new daemon holds in SINGLETON grace while
# any card still has a live turn, and that live turn is usually the very agent
# scheduling the restart. So the proof has to outlive the turn - this script is
# launched by schtasks (own parentage, survives the `taskkill /F /T` eviction
# that cascades through the old daemon's children) and writes the verdict to
# daemon/restart_verify.log.
#
#   schtasks /Create /TN HelmDeckRestartVerify /SC ONCE /ST 23:59 /F /TR "<pwsh> -File <this>"
#   schtasks /Run /TN HelmDeckRestartVerify

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
Set-Location $root

$log = Join-Path $root 'daemon\restart_verify.log'
function Say($msg) {
  $line = "{0}  {1}" -f (Get-Date -Format 'HH:mm:ss'), $msg
  Add-Content -Path $log -Value $line -Encoding utf8
}

function DaemonProcs {
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'daemon\.swarm' }
}
function PortOwner {
  (Get-NetTCPConnection -LocalPort 8140 -State Listen -ErrorAction SilentlyContinue |
     Select-Object -First 1).OwningProcess
}

Say '================ HelmDeck daemon restart verify ================'

$commit     = (git log -1 --format='%h' 2>$null)
$commitTime = [datetime](git log -1 --format='%cI' 2>$null)
$dirty      = (git status --porcelain 2>$null | Measure-Object -Line).Lines
Say ("main HEAD  : {0} committed {1}  (working tree dirty lines: {2})" -f $commit, $commitTime.ToString('yyyy-MM-dd HH:mm:ss'), $dirty)

$oldPid = PortOwner
$oldProc = Get-CimInstance Win32_Process -Filter "ProcessId=$oldPid" -ErrorAction SilentlyContinue
Say ("old daemon : pid={0} started {1}" -f $oldPid, $(if ($oldProc) { $oldProc.CreationDate } else { 'n/a' }))
Say 'waiting for the SINGLETON swap (new daemon evicts only once every live card turn has ended)...'

$deadline = (Get-Date).AddSeconds(1900)
$newPid = $oldPid
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 10
  $cur = PortOwner
  if ($cur -and $cur -ne $oldPid) { $newPid = $cur; break }
}

if ($newPid -eq $oldPid) {
  Say 'NO SWAP within the window - :8140 is still owned by the old pid. Investigate daemon/restart_stderr.log.'
} else {
  Start-Sleep -Seconds 3
  $np = Get-CimInstance Win32_Process -Filter "ProcessId=$newPid" -ErrorAction SilentlyContinue
  $start = $np.CreationDate
  Say ("SWAP OK    - :8140 now owned by pid={0}" -f $newPid)
  Say ("  started  : {0}" -f $start)
  Say ("  cmdline  : {0}" -f $np.CommandLine)
  Say ("  pidfile  : {0}  (must equal {1})" -f (Get-Content (Join-Path $root 'daemon\daemon.pid') -ErrorAction SilentlyContinue), $newPid)
  if ($start -gt $commitTime) {
    Say ("  VERDICT  : start time is AFTER commit {0} -> this process imported current main. PREMISE CLOSED." -f $commit)
  } else {
    Say ("  VERDICT  : start time is BEFORE commit {0} -> STALE CODE. Restart did not take." -f $commit)
  }
  Say ("  old pid {0} still alive: {1}  (expected False)" -f $oldPid, [bool](Get-Process -Id $oldPid -ErrorAction SilentlyContinue))
}

$procs = @(DaemonProcs)
Say ("SINGLETON  : {0} daemon.swarm process(es) alive - {1}" -f $procs.Count, $(if ($procs.Count -eq 1) { 'CONFIRMED' } else { 'NOT SINGLETON' }))
foreach ($p in $procs) { Say ("    pid={0} started {1}" -f $p.ProcessId, $p.CreationDate) }

try {
  $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8140/health' -UseBasicParsing -TimeoutSec 10
  Say ("health     : HTTP {0} - answering" -f $r.StatusCode)
} catch {
  $code = $_.Exception.Response.StatusCode.value__
  if ($code) { Say ("health     : HTTP {0} - answering (an auth-gated reply IS alive - tray.py)" -f $code) }
  else { Say ("health     : NO REPLY - {0}" -f $_.Exception.Message) }
}

Say '--- SINGLETON / boot lines from the new daemon ---'
Get-Content (Join-Path $root 'daemon\restart_stdout.log') -ErrorAction SilentlyContinue |
  Where-Object { $_ -match 'SINGLETON|review server|Traceback|Error' } | ForEach-Object { Say ("    " + $_) }
Get-Content (Join-Path $root 'daemon\restart_stderr.log') -Tail 15 -ErrorAction SilentlyContinue |
  Where-Object { $_.Trim() } | ForEach-Object { Say ("    ERR " + $_) }

Say '================ done ================'
