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


# A live turn that has produced no frame for this long is STANDING STILL, not
# working: past the tool cap (BASH_MAX_TIMEOUT_MS, 5 min - one tool cannot be
# silent longer) and below the driver's own 900 s hung-watchdog, which would
# end it anyway. Owner 2026-10-14: "check der idle auch wenn was stehen
# geblieben ist" - a wedged card used to keep the idle-check silent for good.
STALL_S = 360


def _stalled():
    """[(kind, id, silent_seconds)] of work that is formally live but silent:
    card turns by the driver's own frame clock (drivers.turn_silence_s), hands
    runs by their last step stamp. Observations at call time, nothing stored."""
    from spine.ops import daemonctl
    from spine.agent import drivers
    from cells.copilot.chat import hands
    out = []
    for cid in daemonctl.running_turns():
        s = drivers.turn_silence_s(cid)
        if s is not None and s > STALL_S:
            out.append(("karte", cid, s))
    now = time.time()
    for hid, d in hands.tasks().items():
        if d.get("status") == "running" and now - float(d.get("updated") or now) > STALL_S:
            out.append((d.get("kind") or "hands", hid, now - float(d["updated"])))
    return out


def _anything_live():
    """True if a card turn or a hands run is actually in flight AND moving -
    the same facts daemonctl.status() already reports, read fresh
    (drivers.turn_active is an observation, not a stored flag). Work that is
    live but has gone silent (_stalled) does not count: that is exactly the
    situation the idle-check exists to look at."""
    from spine.ops import daemonctl
    from cells.copilot.chat import hands
    stalled = {i for _k, i, _s in _stalled()}
    turns = [c for c in daemonctl.running_turns() if c not in stalled]
    hand = [h for h in hands.running_ids() if h not in stalled]
    return bool(turns or daemonctl.background_work() or hand)


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


def _load_line():
    from spine.ops import resources
    s = resources.sample(0.2)
    cpu = ("%.0f%%" % s["cpu_pct"]) if s.get("cpu_pct") is not None else "?"
    ram = ("%.1f GB frei" % (s["free_ram_mb"] / 1024.0)) if s.get("free_ram_mb") else "?"
    return "last: CPU %s, RAM %s" % (cpu, ram)


def _owner_line():
    m = int(_owner_idle_s() // 60)
    live = "Karte oder Haende live" if _anything_live() else "keine Karte, keine Haende live"
    return "owner: seit %d min nicht gesehen; %s" % (m, live)


def _owned_line():
    """WHICH processes are the daemon's own (spine.agent.proctable.owned: the
    OS's job + parent links, read now). The one fact Henry cannot fetch for
    himself - 2026-10-13 he ended a Paseo-owned claude.exe because nothing told
    him whose it was. Everything NOT listed here is the owner's or another
    program's."""
    from spine.agent import proctable
    rows = []
    now = time.time()
    for pid, exe, started in proctable.owned():
        if (exe or "").lower() in ("conhost.exe",):
            continue                                    # console plumbing, never a decision
        if not started:
            age = "?"
        elif now - started >= 3600:
            age = "%dh" % ((now - started) // 3600)
        else:
            age = "%dm" % ((now - started) // 60)
        rows.append("%s %d (%s)" % (exe, pid, age))
    return ("dem Daemon gehoeren: " + (", ".join(rows) if rows else "keine Kindprozesse")
            + " - alles andere gehoert dem Owner oder fremden Programmen")


def _stalled_line():
    st = _stalled()
    if not st:
        return ""
    return "stehen still: " + ", ".join("%s %s (%d min ohne Ausgabe)" % (k, i, s // 60)
                                        for k, i, s in st)


def situation_snapshot():
    """The Lagebild an idle-check escalation carries as `detail` - facts
    only, no verdict, and only the facts Henry cannot fetch himself. Tabs,
    dev ports, worktrees and locks used to be listed here (owner decree
    2026-09-20); he reads those with his own hands, so the daemon no longer
    curates what he looks at (owner 2026-10-14: "offener, die AI muss selber
    ueberlegen")."""
    lines = [_owner_line(), _stalled_line(), _owned_line(), _load_line()]
    return "\n".join(ln for ln in lines if ln)


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
