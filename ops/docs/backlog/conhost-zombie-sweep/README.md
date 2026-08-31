# Orphaned conhost.exe pile-up: HelmDeck-spawned sessions leak console hosts (~4.5 GB found)

**Filed 2026-08-31**, found when the owner asked "why so many things open":
1158 `conhost.exe` on the box, 1143 of them orphans (parent dead), ~4.5 GB
working set combined. Swept manually the same day.

## Root cause (measured, not reasoned)

- Timestamps show bursts at ~3 s cadence exactly during active card-turn
  windows (2026-08-30 07:27–07:56 and 14:23–15:03) — the cadence of
  Bash/PowerShell tool calls inside Claude Code sessions. On Windows, every
  such tool call spawns a hidden console process, and each console process
  gets its own `conhost.exe`.
- Windows reaps the conhost when the client exits cleanly. It does NOT when
  the session tree dies hard — and HelmDeck kills trees hard in several
  places: the turn idle-watchdog (900 s silence kill), steer =
  interrupt-and-replace, daemon restarts killing live turns, and stale
  session cleanup via `taskkill /T /F`. Each hard kill strands the conhosts
  of every tool call the turn ever made.
- Repo code is NOT the spawner-side culprit: `surfaces/desktop/tray.py:132`
  and `spine/media/wincap.py:59` already use `CREATE_NO_WINDOW` correctly.
  The leak is on the reap side: the isolation/kill machinery has no
  console-host reclaim half — same shape as the worktree-reclamation gap
  (f28abe5).

## Fix

Extend the daemon's existing zombie/stale sweep with a Windows-only
conhost reaper:

- Sweep `OpenConsole.exe` too (2026-08-31 follow-up: with Windows Terminal
  set as default terminal app, every spawn leaks a VISIBLE terminal window
  hosted by OpenConsole — 24 more orphans piled up within two hours of the
  first sweep).
- Enumerate `conhost.exe` processes, resolve each parent PID against the
  live process table, kill only those whose parent is DEAD. This is derived
  state from the runtime's own signals (process table), one owner (the
  sweeper), fold-in at sweep time — NO-MONKEY-PATCH compliant, and
  fail-safe: a conhost with a live parent is never touched.
- Run it wherever `sweep_worktrees` / the zombie-sweeper already runs
  (periodic + on daemon start).
- Optional hardening: after any hard tree-kill the daemon itself performs
  (idle-watchdog, steer, restart), do a targeted reap pass.

Manual recipe that worked (PowerShell, 1143/1143 killed):

```powershell
$live = @{}; Get-Process | ForEach-Object { $live[$_.Id] = $true }
Get-CimInstance Win32_Process -Filter "Name='conhost.exe'" |
  Where-Object { -not $live.ContainsKey([int]$_.ParentProcessId) } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

## Non-goals

- Preventing the conhosts from being created (that is Claude Code / Windows
  behavior per tool call, not ours to change).
- Sweeping conhosts with live parents (those are real terminals).
