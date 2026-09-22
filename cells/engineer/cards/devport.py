# -*- coding: utf-8 -*-
"""Per-card dev port allocation - extracted from sessions.py (Paseo
PASEO_WORKTREE_PORT parity). A free port no OTHER card has claimed, persisted on
the track (tracks.json is durable; a worktree is regenerable). Depends only on
trackstore._load. sessions.py re-imports DEV_PORT_RANGE + _alloc_dev_port.
"""
from spine.storage.trackstore import _load

DEV_PORT_RANGE = (3401, 3999)   # settings.json "dev_port_range": [lo, hi] overrides


def _alloc_dev_port(exclude_tid=None):
    """A free port no OTHER card has claimed (Paseo's range allocator: random
    start, scan the whole range wrapping around, skip reserved, bind-check
    each candidate). Returns None when the range is exhausted - the card still
    runs, it just gets no reserved port."""
    import socket, random
    from spine.storage import events
    rng = events.settings().get("dev_port_range") or DEV_PORT_RANGE
    try:
        lo, hi = int(rng[0]), int(rng[1])
    except Exception:
        lo, hi = DEV_PORT_RANGE
    if lo > hi:
        lo, hi = hi, lo
    taken = {t.get("dev_port") for t in _load()
             if t.get("dev_port") and t.get("id") != exclude_tid}
    span = hi - lo + 1
    start = random.randrange(span)
    for i in range(span):
        port = lo + (start + i) % span
        if port in taken:
            continue
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            continue
        finally:
            s.close()
        return port
    return None


def _listeners_on(port):
    """PIDs listening on `port` (TCP, any interface), from netstat - the only
    port table available on the daemon's Windows PATH (no psutil, no
    PowerShell; see memory 'powershell.exe absent from owner-box PATH')."""
    import subprocess, os, re
    pids = set()
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True,
                             text=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:
        return pids
    pat = re.compile(r"^\s*TCP\s+\S+:%d\s+\S+\s+LISTENING\s+(\d+)\s*$" % port, re.M)
    for m in pat.finditer(out):
        pid = int(m.group(1))
        if pid and pid != os.getpid():
            pids.add(pid)
    return pids


def reclaim_dev_port(t, log=None):
    """Kill whatever a FINISHED card left listening on its dev port.

    Found live 2026-09-19: an `expo start --web --port 3891` from a card
    accepted on 09-18 17:04 ran for three days (63 CPU-hours, 680 MB) - the
    worktree reclaim never saw it because a DIRECT card has no worktree, and
    nothing else owned the process. The port is the card's by allocation
    (_alloc_dev_port), so on the card's terminal transition the listener is the
    card's too. Kills the process TREE (the dev server spawns bundlers).
    Best-effort: never breaks the accept/archive. Returns the PIDs killed."""
    import subprocess
    port = t.get("dev_port")
    if not port:
        return []
    killed = []
    for pid in sorted(_listeners_on(int(port))):
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            killed.append(pid)
        except Exception:
            pass
    if killed and log:
        log.log("note", "DEV-PORT %s zurueckgeholt - Prozess(e) %s beendet, die Karte ist fertig."
                % (port, ", ".join(map(str, killed))))
    return killed
