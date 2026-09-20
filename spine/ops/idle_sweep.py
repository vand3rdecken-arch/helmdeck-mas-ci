# -*- coding: utf-8 -*-
"""IDLE RESOURCE SWEEPER (owner request 2026-09-20): once the owner has been
away for a while AND nothing HelmDeck runs is actually live, reclaim exactly
what the harness itself opened - never the owner's own windows or processes.

Reuses the reclaim paths that already exist for the terminal-transition case
(cells.engineer.cards.devport.reclaim_dev_port, spine.git.worktrees.
sweep_worktrees) rather than reimplementing them; this module is the missing
IDLE-TIME trigger for those plus the two domains that had no reclaim path at
all yet (orphaned CDP tabs, stale machine-global build locks).

Every action is one kind=sweep event (spine.storage.events.emit) - the
audit trail IS the "last sweep" record; last_sweep_summary() reads it back
with the same bounded, indexed query daemonctl.relay_latency() already
proved safe (never events_all()'s full-table scan - see its own docstring
for the 2026-09-19 incident that query shape caused).

Scope, exactly as specified: (1) browser tabs this repo's own CDP-attach
path registered (spine.media.browsercap) whose owning process is dead: (2)
a finished card's dev-port listener that outlived its own terminal-
transition reclaim; (3) worktree folders sweep_worktrees() already knows
how to reclaim safely (dirty trees, unmerged branches, live cohabitants all
kept - that logic is NOT duplicated here); (4) a machine-global build lock
whose recorded holder pid is dead."""
import time

from spine.storage import events


def sweep_policy():
    """policy.sweep {enabled, idle_minutes} - same shape and defaults-at-
    read pattern as cells.engineer.cards.dispatch.machine_policy(): nothing
    new in events.DEFAULTS, .setdefault() supplies the fallback on every
    read, a policy.swap-style write to workspace_config overrides it."""
    p = dict((events.settings().get("policy") or {}).get("sweep") or {})
    p.setdefault("enabled", True)
    p.setdefault("idle_minutes", 30)
    return p


def _owner_idle_s():
    """Seconds since the owner was last seen anywhere (spine.comms.presence,
    every client this boot has ever reported - not just the fresh ones), or
    since this daemon booted when no client has EVER reported. Never
    "away forever": a fresh boot with nobody paired yet must not sweep
    immediately."""
    from spine.comms import presence
    s = presence.idle_s()
    if s is not None:
        return s
    from spine.ops import daemonctl
    return time.time() - daemonctl.boot_ts()


def _anything_live():
    """True if a card turn or a hands run is actually in flight right now -
    the same three facts daemonctl.status() already reports, read fresh
    (drivers.turn_active is an observation, not a stored flag)."""
    from spine.ops import daemonctl
    from cells.copilot.chat import hands
    return bool(daemonctl.running_turns() or daemonctl.background_work()
                or hands.running_ids())


def sweep_browser_tabs():
    """Close every registered HelmDeck-opened tab whose owning process is
    dead. The registration's ONE owner is CdpTab itself (spine.media.
    browsercap); a live pid means a card or hands run is still actively
    using that tab (browser_mcp.py, its MCP-server subprocess, is still
    alive), a dead one means the run already ended - cleanly (which would
    already have unregistered it) or not (a forced kill skips the CdpTab.
    close() that normally would). Only ever touches ids THIS repo itself
    registered - the owner's own windows-mcp-driven Chrome has no such
    registry entry and is never named anywhere in this function."""
    from spine.agent import proctable
    from spine.media import browsercap
    alive_pids = {p for p, _pp, _exe in proctable._pid_table()}
    closed = []
    for target_id, info in browsercap.registered_tabs().items():
        if info.get("pid") in alive_pids:
            continue                                  # owning run still alive - never touch
        try:
            browsercap.close_target(int(info.get("port") or browsercap.DEFAULT_PORT), target_id)
        except Exception:
            pass                                       # already gone, or Chrome itself is down
        browsercap._unregister_tab(target_id)
        closed.append({"target_id": target_id, "run_id": info.get("run_id"),
                       "pid": info.get("pid")})
    return closed


def sweep_dev_ports():
    """Backstop for devport.reclaim_dev_port: a finished (done/archived)
    card whose dev-port listener somehow outlived its own terminal-
    transition reclaim (cardadmin.py and lanemachine.py already call it
    there - this only catches a daemon that was down at that moment, or a
    server started again afterwards). Matches by PORT OWNERSHIP (the card's
    own registered dev_port) and kills the pid(s) actually found listening
    there, never by process name. A card that is not terminal is never even
    considered, so a working card's dev server is never at risk."""
    from cells.engineer.cards import devport
    from spine.storage import db
    out = []
    for t in db.tracks_all():
        if not (t.get("archived") or t.get("lane") == "done"):
            continue
        if not t.get("dev_port"):
            continue
        killed = devport.reclaim_dev_port(t)
        if killed:
            out.append({"card": t.get("id"), "port": t.get("dev_port"), "pids": killed})
    return out


def sweep_locks():
    """Any lock directory under HELMDECK_LOCK_DIR (today just android-build,
    ops/deploy/build_lock.sh) whose recorded holder pid is dead - the SAME
    staleness test the shell acquirer already applies on the NEXT build
    ("stale lock ... taking over"), just run proactively so a status line
    (cells.copilot.broker.henry_broker._android_lock_line) stops reporting a
    build as busy long after it actually died."""
    import os
    import shutil
    from spine.agent import proctable
    root = (os.environ.get("HELMDECK_LOCK_DIR")
            or os.path.join(os.path.expanduser("~"), ".helmdeck", "locks"))
    out = []
    if not os.path.isdir(root):
        return out
    alive_pids = {p for p, _pp, _exe in proctable._pid_table()}
    for name in os.listdir(root):
        lockdir = os.path.join(root, name)
        pidfile = os.path.join(lockdir, "pid")
        if not os.path.isfile(pidfile):
            continue
        try:
            lines = [l.strip() for l in
                     open(pidfile, encoding="utf-8").read().splitlines() if l.strip()]
        except OSError:
            continue
        if not lines:
            continue
        pid_s = lines[1] if len(lines) > 1 else lines[0]   # line 2 = real Windows pid
        try:
            pid = int(pid_s)
        except ValueError:
            continue
        if pid in alive_pids:
            continue                                        # a live build - never touch
        shutil.rmtree(lockdir, ignore_errors=True)
        if not os.path.isdir(lockdir):
            out.append({"lock": name, "pid": pid})
    return out


def run_sweep(force=False):
    """The one entry point: reclaim everything HelmDeck itself opened, IF
    the owner has been away past policy.sweep.idle_minutes AND nothing is
    live (unless force=True, for tests and a manual run). Returns the total
    item count, or None when the sweep didn't run at all (off, not idle
    enough, or something live) - never an empty-but-ran 0, so a caller can
    tell "nothing to do" from "didn't even look"."""
    pol = sweep_policy()
    if not force:
        if not pol.get("enabled"):
            return None
        if _owner_idle_s() < int(pol.get("idle_minutes") or 30) * 60:
            return None
        if _anything_live():
            return None
    tabs = sweep_browser_tabs()
    ports = sweep_dev_ports()
    from spine.git import worktrees
    wt_count = worktrees.sweep_worktrees()
    locks = sweep_locks()
    total = len(tabs) + len(ports) + wt_count + len(locks)
    events.emit("sweep", "-", tabs=tabs, dev_ports=ports, worktrees=wt_count,
               locks=locks, items=total)
    return total


_SWEEP_INTERVAL = 300      # poll every 5 min; policy.sweep.idle_minutes does the real pacing
_sweeper_started = False


def start_idle_resource_sweeper(interval=None):
    """Start the background idle-sweep loop (idempotent) - same shape as
    spine.agent.drivers.start_idle_sweeper."""
    import threading
    global _sweeper_started
    if _sweeper_started:
        return
    _sweeper_started = True
    iv = _SWEEP_INTERVAL if interval is None else interval

    def loop():
        while True:
            time.sleep(iv)
            try:
                n = run_sweep()
                if n:
                    print("SWEEP: reclaimed %d idle resource(s)" % n)
            except Exception as e:
                print("idle resource sweep error:", e)

    threading.Thread(target=loop, daemon=True).start()


def last_sweep_summary():
    """The latest kind=sweep event, straight off the events table - a
    bounded, indexed single-row read (relay_latency()'s pattern), never
    events_all()'s full-table scan. None if no sweep has run this
    install."""
    import json
    from spine.storage import db
    try:
        row = db.conn().execute(
            "SELECT ts, data FROM events WHERE kind='sweep' ORDER BY seq DESC LIMIT 1").fetchone()
    except Exception:
        return None
    if not row:
        return None
    ts, data = row
    try:
        extra = json.loads(data)
    except ValueError:
        extra = {}
    return {"at": ts, "items": extra.get("items", 0)}
