# HelmDeck - restart the daemon from OUTSIDE the daemon's own process tree.
#
# Why this file exists. A card agent runs as a CHILD of the daemon (measured:
# claude.exe <- pythonw.exe -m daemon.swarm serve <- tray.py). The singleton
# takeover in spine/http/startup.py evicts the prior daemon with
# `taskkill /F /T`, and /T cascades to children - so an agent that restarts the
# daemon by starting a rival, or by killing the old one, kills ITSELF mid-turn.
# The fix is not to be in that tree: schtasks launches this script under the
# Task Scheduler's own parentage, so the eviction can never reach the agent that
# asked for it.
#
# The wait is not a race, it is the same grace startup.py already implements: a
# new daemon holds off evicting while any card still has a live turn (a restart
# is a deploy, a live turn is the owner's running work). HELMDECK_RESTART_GRACE
# is raised here because the agent that schedules this is itself usually the
# live turn being waited on - the default 600s can expire on a long turn and
# evict the very work that queued the restart.
#
#   Usage (from the repo root):
#     schtasks /Create /TN HelmDeckRestart /SC ONCE /ST 23:59 /F /TR "<pwsh> -File <this>"
#     schtasks /Run /TN HelmDeckRestart
#
# The tray supervisor (surfaces/desktop/tray.py) supervises by HEALTH, not PID,
# so it adopts whatever ends up serving :8140 and needs nothing from us.

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# Same interpreter the running daemon uses, by absolute path: a scheduled task
# gets a bare environment, and `py -3.12` has resolved differently there before.
$py = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\pythonw.exe'
if (-not (Test-Path $py)) { $py = 'py' }

$env:HELMDECK_RESTART_GRACE = '1800'

$out = Join-Path $root 'daemon\restart_stdout.log'
$err = Join-Path $root 'daemon\restart_stderr.log'

$args = @('-m', 'daemon.swarm', 'serve')
if ($py -eq 'py') { $args = @('-3.12') + $args }

Start-Process -FilePath $py -ArgumentList $args -WorkingDirectory $root `
  -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
