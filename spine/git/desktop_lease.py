# -*- coding: utf-8 -*-
"""THE DESKTOP LEASE - who owns the one physical cursor/keyboard right now.

Replaces the per-TURN in-process desktop lock (2026-09-22). Measured
2026-09-19: every machine card is forced onto the claude-desktop driver
(dispatch.new_machine_task), so every machine card took the exclusive cursor
lock for its WHOLE turn - a Handtest card that ran Node + Haiku scoring for
over an hour never touched the desktop but held the cursor the entire time.
Three sibling cards, one hands run and the card's OWN re-dispatch queued
behind it and bounced after 960s each (12 desktop_wait events that morning).
Henry fanned out correctly; the harness serialized him back to one.

The lease binds the lock to the runtime's own signal instead: a windows-mcp
CONTROL tool call. ops/tools/card_tool_guard.py (the PreToolUse hook every
card and hands spawn already runs) acquires the lease right before such a
call and touches it after (PostToolUse). Nothing else holds the desktop:

  * a card that never clicks holds nothing, no matter how long its turn is;
  * a card mid-GUI-sequence keeps the lease across calls through an IDLE
    GRACE (renewed by every call) so a sibling cannot click into its dialog
    between two of its own clicks;
  * the owner's turn ending releases the lease at once (turnrunner's finally
    and hands' _run finally - the two event-time owners), so a finished
    card never leaves a stale lease behind;
  * a wedged call (holder never reached PostToolUse) expires after the
    busy TTL, sized to the per-call MCP_TOOL_TIMEOUT.

It is a FILE (daemon/state/desktop.lease), not a threading.Lock, because the
hook runs in a separate process inside the card's CLI: the CLI is the one that
knows a desktop call is about to happen, so the CLI's hook is where the lock
must be taken. The file is the single owner of the state; readers derive
"busy" from it (owner + touched + busy), never from a stored flag elsewhere.
Stdlib only - the hook imports this from a foreign cwd with no daemon around.
"""
import json
import os
import random
import time

# windows-mcp tools that only OBSERVE the screen (read pixels/inventory) or
# just pass time, never move the cursor or type. They do not contend for the
# one physical cursor and take no lease - otherwise a passive Screenshot card
# would starve a real driver. FAIL-SAFE: anything not listed is control.
READONLY = frozenset({
    "Screenshot", "Snapshot", "Scrape", "DisplayInventory", "Wait",
})
PREFIX = "mcp__windows-mcp__"

GRACE_S = 90.0        # idle hold-over after a control call (GUI sequences stay together)
BUSY_TTL_S = 330.0    # a call that never reported back: MCP_TOOL_TIMEOUT (300s) + margin


def _path():
    p = os.environ.get("HELMDECK_DESKTOP_LEASE")
    if p:
        return p
    from daemon.paths import DAEMON_ROOT
    return os.path.join(DAEMON_ROOT, "state", "desktop.lease")


def is_control_tool(name):
    """True for a windows-mcp tool that can drive mouse/keyboard/screen."""
    if not name or not str(name).startswith(PREFIX):
        return False
    return str(name)[len(PREFIX):] not in READONLY


def read():
    """The lease on disk, or None. A corrupt file counts as no lease."""
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("owner") else None
    except Exception:                                    # noqa: BLE001
        return None


def expired(lease, now=None):
    """Derived, never stored: a lease is dead when its holder went quiet -
    past the idle grace between calls, or past the busy TTL inside one."""
    if not lease:
        return True
    now = time.time() if now is None else now
    age = now - float(lease.get("touched") or 0)
    ttl = float(lease.get("busy_ttl") or BUSY_TTL_S) if lease.get("busy") else float(lease.get("grace") or GRACE_S)
    return age > ttl


def _write(d):
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.%d.%s.tmp" % (p, os.getpid(), d.get("token", ""))
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, p)                                   # atomic on one volume


def _create_exclusive(d):
    """First writer wins: O_EXCL create of the lease file itself."""
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f)
    return True


def acquire(owner, tool="", wait_s=0.0, grace=None, busy_ttl=None, pid=None):
    """Take (or renew) the lease for `owner`. Waits up to wait_s for a live
    holder to go idle. Returns (True, lease) when owned, (False, holder) when
    someone else still holds it - the caller turns that into a deny."""
    now = time.time()
    deadline = now + max(0.0, float(wait_s or 0))
    mine = {"owner": str(owner), "tool": str(tool or ""), "pid": pid or os.getpid(),
            "since": now, "touched": now, "busy": True,
            "grace": float(grace or GRACE_S), "busy_ttl": float(busy_ttl or BUSY_TTL_S),
            "token": "%x" % random.getrandbits(48)}
    while True:
        cur = read()
        if cur is None:
            if _create_exclusive(mine):
                return True, mine
        elif cur.get("owner") == str(owner):
            mine["since"] = cur.get("since") or now
            _write(mine)
            return True, mine
        elif expired(cur):
            _write(mine)
            time.sleep(0.05)                             # let a racing replacer land
            back = read()
            if back and back.get("token") == mine["token"]:
                return True, mine
        elif time.time() >= deadline:
            return False, cur
        time.sleep(min(1.0, max(0.05, deadline - time.time())))


def touch(owner, busy=False, tool=""):
    """PostToolUse: the call came back - hold-over starts now."""
    cur = read()
    if not cur or cur.get("owner") != str(owner):
        return False
    cur["touched"] = time.time()
    cur["busy"] = bool(busy)
    if tool:
        cur["tool"] = str(tool)
    _write(cur)
    return True


def release(owner):
    """The owner's turn ended: drop the lease if it is theirs. True if it was."""
    cur = read()
    if not cur or cur.get("owner") != str(owner):
        return False
    try:
        os.remove(_path())
    except FileNotFoundError:
        pass
    return True


def status(now=None):
    """For the daemon status line / diagnostics: {} when the desktop is free."""
    cur = read()
    if not cur or expired(cur, now):
        return {}
    now = time.time() if now is None else now
    return {"owner": cur.get("owner"), "tool": cur.get("tool"), "busy": bool(cur.get("busy")),
            "held_s": round(now - float(cur.get("since") or now), 1),
            "idle_s": round(now - float(cur.get("touched") or now), 1)}


def describe_holder(cur, now=None):
    now = time.time() if now is None else now
    return "%s (zuletzt %s vor %ds, haelt seit %ds)" % (
        cur.get("owner"), (cur.get("tool") or "?").replace(PREFIX, ""),
        int(now - float(cur.get("touched") or now)), int(now - float(cur.get("since") or now)))
