# -*- coding: utf-8 -*-
"""IDLE-CHECK ESCALATION (owner decree 2026-09-20: no fixed cleanup code, no
per-resource-type rules - deciding what an unused machine resource is and
whether it can go is Henry's and the workers' JUDGEMENT, not harness logic).

This module is the ONE trigger the daemon owns: once the owner has been away
past policy.idle_minutes (default 30) AND no card turn and no hands run is
live, it files exactly ONE kind=idle-check escalation per idle stretch,
carrying a factual situation snapshot (open HelmDeck-browser targets,
registered dev ports with their card's status, worktree folders with no git
registration, locks with a dead holder pid, RAM/CPU). The daemon NEVER closes,
kills or deletes anything here - Henry judges and acts in his own broker turn
(cells/copilot/broker/henry_broker.py._decide, which already picks up ANY
escalation kind generically) via his own hands, per the brief in
cells/copilot/broker/henry_broker.py's DEFAULT_POLICY (MASCHINEN-RESSOURCEN)
and cells/copilot/harness/agents/board-copilot.d/ops.md.

"Once per idle stretch": the daemon compares the latest idle-check ESCALATION
OPEN timestamp against presence's latest ACTIVITY timestamp, both read fresh
at call time (no stored "already fired" flag - the no-monkey-patch law). The
owner's next heartbeat is what allows the NEXT idle stretch to escalate
again."""
import time


def _idle_minutes():
    """policy.idle_minutes - a flat policy key (owner decree: this feature
    gets no on/off switch, no nested config; just the one threshold)."""
    from spine.storage import events
    pol = events.settings().get("policy") or {}
    try:
        return int(pol.get("idle_minutes") or 30)
    except (TypeError, ValueError):
        return 30


def _owner_idle_s():
    """Seconds since the owner was last seen anywhere (spine.comms.presence),
    or since this daemon booted when no client has EVER reported - never
    "away forever" on a fresh boot with nobody paired yet."""
    from spine.comms import presence
    last = presence.last_activity_ts()
    if last is None:
        from spine.ops import daemonctl
        last = daemonctl.boot_ts()
    return time.time() - last


def _anything_live():
    """True if a card turn or a hands run is actually in flight - the same
    facts daemonctl.status() already reports, read fresh (drivers.turn_active
    is an observation, not a stored flag)."""
    from spine.ops import daemonctl
    from cells.copilot.chat import hands
    return bool(daemonctl.running_turns() or daemonctl.background_work()
                or hands.running_ids())


def _last_idle_check_open_ts():
    """Epoch of the most recently OPENED kind=idle-check escalation - a
    bounded, indexed single-row read (daemonctl.relay_latency()'s pattern),
    never escalations.records()'s full fold. None if never opened."""
    from spine.storage import db
    try:
        row = db.conn().execute(
            "SELECT ts FROM escalations WHERE kind='idle-check' AND event='open' "
            "ORDER BY seq DESC LIMIT 1").fetchone()
    except Exception:
        return None
    if not row:
        return None
    try:
        return time.mktime(time.strptime(row[0], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return None


def _already_fired_this_stretch():
    """True when an idle-check has already been opened since the owner was
    last seen - the daemon must file at most ONE per idle stretch."""
    opened = _last_idle_check_open_ts()
    if opened is None:
        return False
    from spine.comms import presence
    present = presence.last_activity_ts()
    if present is None:
        from spine.ops import daemonctl
        present = daemonctl.boot_ts()
    return opened >= present


def _pid_alive(pid_s):
    import os
    try:
        os.kill(int(pid_s), 0)
        return True
    except (OSError, ValueError):
        return False


def _browser_targets_line():
    """Every open target in HelmDeck's OWN Chrome (own debug port, own
    user-data-dir - spine.media.browsercap.ensure_chrome) - by construction
    never the owner's daily browser (that is windows-mcp's separate path,
    which this function never touches or even names)."""
    from spine.media import browsercap
    port = browsercap.DEFAULT_PORT
    if not browsercap._cdp_up(port):
        return "browser: HelmDeck-Chrome nicht offen"
    try:
        import json
        import urllib.request
        with urllib.request.urlopen(
                "http://127.0.0.1:%d/json/list" % port, timeout=3) as r:
            targets = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return "browser: Ziel-Liste nicht lesbar (%s)" % str(e)[:80]
    pages = [t for t in targets if t.get("type") == "page"]
    if not pages:
        return "browser: 0 offene Tabs"
    items = "; ".join("%s (%s)" % ((t.get("title") or t.get("url") or "?")[:40],
                                   (t.get("id") or "")[:8])
                      for t in pages[:8])
    return "browser: %d offene Tab(s) in HelmDecks eigenem Chrome: %s" % (len(pages), items)


def _dev_ports_line():
    """Every card's REGISTERED dev port and its lane/status - not whether
    something still listens (Henry can check that himself if he needs to)."""
    from spine.storage import db
    rows = []
    for t in db.tracks_all():
        port = t.get("dev_port")
        if port:
            rows.append("%s:%s(%s/%s)" % (t.get("id"), port, t.get("lane"), t.get("status")))
    return "dev-ports: " + (", ".join(rows) if rows else "keine registriert")


def _orphan_worktree_dirs():
    """Worktree folders on disk that git itself no longer lists AND no card
    references - read-only listing, no reclaim (spine.git.worktrees.
    reclaim_worktree/sweep_worktrees stay the CODE that Henry or a follow-up
    card can call; this only OBSERVES for the snapshot)."""
    import os
    from spine.storage import db
    from spine.git.gitutil import _repo_hash, _git_try, WORKTREE_DIRNAME
    tracks = db.tracks_all()
    repos = {t.get("repo") for t in tracks if t.get("repo")}
    referenced = {os.path.realpath(t["worktree"]) for t in tracks if t.get("worktree")}
    out = []
    for repo in repos:
        if not repo or not os.path.isdir(repo):
            continue
        rc, listing, _ = _git_try(repo, "worktree", "list", "--porcelain")
        known = set()
        if rc == 0:
            for line in listing.splitlines():
                if line.startswith("worktree "):
                    known.add(os.path.realpath(line[len("worktree "):].strip()))
        hashdir = os.path.join(os.path.abspath(os.path.join(repo, "..", WORKTREE_DIRNAME)),
                               _repo_hash(repo))
        if not os.path.isdir(hashdir):
            continue
        for name in os.listdir(hashdir):
            p = os.path.join(hashdir, name)
            if os.path.isdir(p):
                rp = os.path.realpath(p)
                if rp not in known and rp not in referenced:
                    out.append(name)
    return out


def _worktrees_line():
    orphans = _orphan_worktree_dirs()
    if not orphans:
        return "worktrees ohne git-Registrierung: keine"
    shown = ", ".join(orphans[:10])
    more = " (+%d weitere)" % (len(orphans) - 10) if len(orphans) > 10 else ""
    return "worktrees ohne git-Registrierung: %d - %s%s" % (len(orphans), shown, more)


def _locks_line():
    """Any lock directory under HELMDECK_LOCK_DIR (today android-build, see
    ops/deploy/build_lock.sh) whose recorded holder pid is dead - read-only,
    the same staleness TEST the shell acquirer itself already applies on the
    next build, just reported here instead of acted on."""
    import os
    root = os.environ.get("HELMDECK_LOCK_DIR") or os.path.join(
        os.path.expanduser("~"), ".helmdeck", "locks")
    if not os.path.isdir(root):
        return "locks mit toter PID: keine"
    dead = []
    for name in os.listdir(root):
        pidfile = os.path.join(root, name, "pid")
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
        if not _pid_alive(pid_s):
            dead.append(name)
    return "locks mit toter PID: " + (", ".join(dead) if dead else "keine")


def _load_line():
    from spine.ops import resources
    s = resources.sample(0.2)
    cpu = ("%.0f%%" % s["cpu_pct"]) if s.get("cpu_pct") is not None else "?"
    ram = ("%.1f GB frei" % (s["free_ram_mb"] / 1024.0)) if s.get("free_ram_mb") else "?"
    return "last: CPU %s, RAM %s" % (cpu, ram)


def situation_snapshot():
    """The Lagebild an idle-check escalation carries as `detail` - facts
    only, no verdict. escalations.emit() caps this at 1500 chars regardless;
    every line here stays short and bounded on its own."""
    lines = [_browser_targets_line(), _dev_ports_line(), _worktrees_line(),
             _locks_line(), _load_line()]
    return "\n".join(lines)


def check(force=False):
    """The one entry point. Files a kind=idle-check escalation and returns
    its id, or None when the conditions aren't met (or, with force=False,
    it already fired this idle stretch)."""
    if not force:
        if _owner_idle_s() < _idle_minutes() * 60:
            return None
        if _anything_live():
            return None
        if _already_fired_this_stretch():
            return None
    from spine.registry import escalations
    return escalations.emit("idle-check", None, detail=situation_snapshot())


_CHECK_INTERVAL = 300      # poll every 5 min; idle_minutes/the once-per-stretch
_checker_started = False   # dedup do the real pacing


def start_idle_check_loop(interval=None):
    """Idempotent periodic loop, same shape as spine.agent.drivers.
    start_idle_sweeper."""
    import threading
    global _checker_started
    if _checker_started:
        return
    _checker_started = True
    iv = _CHECK_INTERVAL if interval is None else interval

    def loop():
        while True:
            time.sleep(iv)
            try:
                eid = check()
                if eid:
                    print("IDLE-CHECK: escalation %s filed" % eid)
            except Exception as e:
                print("idle-check error:", e)

    threading.Thread(target=loop, daemon=True).start()
