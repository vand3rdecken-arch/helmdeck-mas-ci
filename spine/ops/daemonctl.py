# -*- coding: utf-8 -*-
"""Daemon self-knowledge and the ONE restart verb (owner request 2026-09-12:
"das System soll sich selbst neu starten koennen, wenn Sachen haengen").

Until now a restart was a hand-typed schtasks command - by the owner, or by
Henry guessing shell syntax through a permission system (see the 2026-09-12
analysis: three identical failures, three invented reasons). A restart is an
infrastructure verb, not a judgement: this module owns it, the route exposes
it, the Settings > System panel shows it, Henry calls it.

status() is DERIVED at read time (no stored flag): the running interpreter's
pid and boot time are process facts, the commit it booted on was read from
git at import, the repo's HEAD is read again now - `stale` is the comparison,
so "code newer than the running daemon" is measured, never assumed.

restart() refuses while a card turn is live unless forced (a live turn is the
owner's running work - the same rule startup.py's eviction grace enforces),
then fires the HelmDeckRestart scheduled task: it runs OUTSIDE the daemon's
process tree (ops/tools/restart_helmdeck.ps1's whole reason to exist - the
eviction is `taskkill /T`, which would kill any child we spawned ourselves),
waits 90 s and lets the tray supervisor respawn. If the task is missing it is
created first (unelevated /Create works; /Change on the elevated one does not
- measured).
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TASK = "HelmDeckRestart"
SCRIPT = os.path.join(ROOT, "ops", "tools", "restart_helmdeck.ps1")
LOG = os.path.join(ROOT, "daemon", "restart_watch.log")

_BOOT_TS = time.time()


def _git_head():
    try:
        r = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


_BOOT_SHA = _git_head()


def running_turns():
    """Cards with a LIVE turn - drivers.turn_active (lifecycle is an
    observation), not the stored status flag alone."""
    out = []
    try:
        from spine.storage import db
        from spine.agent import drivers
        for t in db.tracks_all():
            if t.get("status") == "running" and drivers.turn_active(t.get("id")):
                out.append(t.get("id"))
    except Exception:
        pass
    return out


def background_work():
    """Cards whose TURN is over but whose background tasks still run -
    {card_id: [titles]}. As much the owner's running work as a live turn: the
    tasks are children of the card's worker process and die with the daemon
    tree. One reading (sessions_bg.running_bg), shared with the board
    snapshot and restart_daemon.py."""
    out = {}
    try:
        from spine.storage import db
        from cells.engineer.cards import sessions_bg
        for t in db.tracks_all():
            titles = sessions_bg.running_bg(t)
            if titles:
                out[t.get("id")] = titles
    except Exception:
        pass
    return out


def _task_present():
    try:
        r = subprocess.run(["schtasks", "/Query", "/TN", TASK],
                           capture_output=True, text=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def _last_restart():
    """The watcher's last RESULT line, if any - what the previous restart did."""
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()[-40:]
        for line in reversed(lines):
            if "RESULT" in line:
                return line.strip()
    except OSError:
        pass
    return ""


def status():
    head = _git_head()
    return {
        "pid": os.getpid(),
        "python": sys.executable,
        "started": _BOOT_TS,
        "uptime_s": int(time.time() - _BOOT_TS),
        "commit": _BOOT_SHA[:12],
        "repo_head": head[:12],
        "stale": bool(_BOOT_SHA and head and _BOOT_SHA != head),
        "running_turns": running_turns(),
        "background": background_work(),
        "restart_task": _task_present(),
        "last_restart": _last_restart(),
        "relay_latency": relay_latency(),
    }


RELAY_LATENCY_WINDOW_MIN = 15

def relay_latency(window_min=RELAY_LATENCY_WINDOW_MIN):
    """The phone's path, judged: how often in the last `window_min` minutes a
    request breached the bridge's budget, and the worst case. DERIVED from the
    two measurements the bridge already writes ("daemon took Ns to answer",
    "frame waited Ns in the relay queue") - relay_client._serve_one is their one
    owner; nothing here is stored or guessed. 2026-09-19: both root causes of
    "Relay nicht erreichbar" sat fully described in these rows for hours while
    every surface showed green. A number that nobody reads is not a measurement."""
    import json, re
    from spine.storage import db
    out = {"window_min": window_min, "slow_daemon": 0, "bridge_stalls": 0,
           "worst_s": 0.0, "last": None}
    try:
        rows = db.conn().execute(
            "SELECT ts, data FROM events WHERE kind='relay' AND ts >= "
            "datetime('now','localtime', ?) ORDER BY seq DESC LIMIT 500",
            ("-%d minutes" % int(window_min),)).fetchall()
    except Exception:
        return out
    pat = re.compile(r"(daemon took|frame waited) ([\d.]+)s")
    for ts, data in rows:
        try:
            msg = json.loads(data).get("msg", "")
        except ValueError:
            continue
        m = pat.search(msg)
        if not m:
            continue
        secs = float(m.group(2))
        out["slow_daemon" if m.group(1) == "daemon took" else "bridge_stalls"] += 1
        if secs > out["worst_s"]:
            out["worst_s"] = secs
        if out["last"] is None:
            out["last"] = ts
    return out


def _run(argv):
    r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    return r.returncode, (r.stdout + r.stderr).strip()


def restart(force=False, actor="owner", runner=None):
    """Fire the out-of-tree restart. Returns {ok, reason?, turns?, detail}.
    `runner` is injectable so a test can prove the decision without touching
    the Task Scheduler. It resolves to the module's `_run` AT CALL TIME, so a
    test can disarm EVERY path at once (`daemonctl._run = fake`): bound as a
    default argument it was unreachable through the route, and on 2026-09-17 a
    slipped precondition in test_daemonctl fired the REAL task and tree-killed
    the owner's running benchmark."""
    runner = runner or _run
    live = running_turns()
    if live and not force:
        return {"ok": False, "reason": "turn_active", "turns": live,
                "detail": "Karte(n) mitten im Turn - Neustart wuerde laufende Arbeit killen"}
    bg = background_work()
    if bg and not force:
        return {"ok": False, "reason": "background_active", "turns": sorted(bg), "background": bg,
                "detail": "Hintergrund-Task(s) laufen noch (%s) - Neustart wuerde sie killen"
                          % "; ".join(t[:60] for ts in bg.values() for t in ts)}
    if not _task_present():
        tr = 'powershell.exe -ExecutionPolicy Bypass -File "%s" -DelaySeconds 90' % SCRIPT
        rc, out = runner(["schtasks", "/Create", "/TN", TASK, "/SC", "ONCE", "/ST", "23:59",
                          "/F", "/TR", tr])
        if rc != 0:
            return {"ok": False, "reason": "task_create_failed", "detail": out[:300]}
    rc, out = runner(["schtasks", "/Run", "/TN", TASK])
    ok = rc == 0
    try:
        from spine.storage import events
        events.emit("daemon/restart", "", actor=actor, forced=bool(force),
                    ok=ok, turns=live, detail=out[:200])
    except Exception:
        pass
    if not ok:
        return {"ok": False, "reason": "task_run_failed", "detail": out[:300]}
    return {"ok": True, "delay_s": 90, "forced": bool(force), "turns": live,
            "detail": "Neustart ausgeloest - der Task wartet 90 s, dann respawnt das Tray den Daemon"}
