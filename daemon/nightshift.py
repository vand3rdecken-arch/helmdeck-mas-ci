# -*- coding: utf-8 -*-
"""The night shift: turn idle subscription-hours into shipped improvements.

On a flat-rate plan (Claude Max) unused night quota simply expires - the
5-hour windows reset whether you slept or worked. So instead of a token
budget, the constraint model is:

  PLAN  - before the owner sleeps (or on schedule), one cheap read-only
          scout per configured repo writes a prioritized improvement plan:
          what is broken, what is missing vs. comparable projects, what
          debt is registered. The plan is a reviewable artifact.
  WORK  - inside the night window, while the board is idle, items from the
          plan become ORDINARY cards - worktree, gates, review lane - one
          at a time. Nothing merges itself; the owner judges in the morning.
  STOP  - hard caps: max cards per night, window end, or the driver
          reporting a usage limit (that is the flat-plan "budget" signal).

Everything runs through the fixed harness (sessions.new_track); this module
only decides WHEN and WHAT, never HOW - policy is data, the harness is code.
"""
import json, os, re, subprocess, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
PLANS = os.path.join(HERE, "nightshift")
STATE = os.path.join(PLANS, "state.json")

DEFAULTS = {
    "enabled": False,
    "window": "01:00-07:00",     # local time; work only happens inside
    "repos": [],                  # absolute folders the owner selected
    "max_cards": 3,               # per night, across all repos
    "idle_minutes": 20,           # board must be this quiet before working
    "scout_model": "",            # empty = driver default
}

_lock = threading.Lock()


def cfg():
    import events
    c = dict(DEFAULTS)
    c.update(events.settings().get("nightshift") or {})
    return c


def _state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(s):
    os.makedirs(PLANS, exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)


def _today():
    return time.strftime("%Y%m%d")


def plan_path(day=None):
    return os.path.join(PLANS, "plan-%s.json" % (day or _today()))


def latest_plan():
    if not os.path.isdir(PLANS):
        return None
    days = sorted(f for f in os.listdir(PLANS) if f.startswith("plan-"))
    if not days:
        return None
    try:
        with open(os.path.join(PLANS, days[-1]), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def latest_report():
    """The most recent morning report (report-*.md), or None. status() surfaces it;
    it was referenced but never defined, which 500'd /nightshift + /automation."""
    if not os.path.isdir(PLANS):
        return None
    reps = sorted(f for f in os.listdir(PLANS) if f.startswith("report-"))
    if not reps:
        return None
    try:
        with open(os.path.join(PLANS, reps[-1]), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


# -- PLAN: delegated to the PM role (daemon/pm.py) -------------------------
# There is ONE planning brain now: the data-driven PM/CTO role. The night shift
# no longer runs its own hardcoded scout - it asks the PM for the plan and files
# the PM's NEW items as backlog cards. WHAT to build = the PM role (data);
# WHEN/whether to work = this ticker (code). No second brain.

def make_plan(actor="owner"):
    """Ask the PM role for the current plan and file its new items as backlog
    cards (deduped by title). The reviewable brief is stored as the day's plan."""
    import pm, sessions
    items, brief = pm.plan_items()
    have = {t.get("task", "").strip().lower() for t in sessions.list_tracks()}
    filed = 0
    for it in items:
        repo = it.get("repo") or ""
        if not repo or not os.path.isdir(repo):
            continue
        if it["title"].strip().lower() in have:
            continue
        sessions.new_track(
            repo, "pm-" + re.sub(r"[^a-z0-9]+", "-", it["title"].lower())[:24],
            it["title"], lane="backlog",
            description=it.get("description", ""),
            priority=it.get("priority", "medium"), actor="nightshift")
        filed += 1
        have.add(it["title"].strip().lower())
    plan = {"day": _today(), "made": time.strftime("%Y-%m-%d %H:%M"),
            "actor": actor, "brief": brief, "filed": filed, "candidates": len(items)}
    os.makedirs(PLANS, exist_ok=True)
    with open(plan_path(), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=1, ensure_ascii=False)
    print("NIGHTSHIFT plan (PM role): %d Kandidaten, %d neue Karten" % (len(items), filed))
    return plan


# -- WORK: the ticker -------------------------------------------------------

def _in_window(c):
    """Empty or "always" = work WHENEVER the board is idle - on a flat plan
    every quiet hour is quota that would otherwise expire, day or night. A
    time range restricts work to that window (midnight wrap supported)."""
    w = (c.get("window") or "").strip().lower()
    if w in ("", "always"):
        return True
    try:
        a, b = w.split("-")
        now = time.strftime("%H:%M")
        return a <= now < b if a <= b else (now >= a or now < b)
    except ValueError:
        return False


_last_touch = 0.0

def touch():
    """Server calls this on every authenticated request - any surface the
    owner is looking at (desktop, phone, glasses) counts as presence."""
    global _last_touch
    _last_touch = time.time()


def _board_idle(c):
    """Idle = nothing running and no user request for idle_minutes. This is
    the gate that matters in always-on mode: the shift must never compete
    with the owner for quota while they are actually around."""
    import sessions
    for t in sessions.list_tracks():
        if t.get("status") == "running":
            return False
    return time.time() - _last_touch >= c["idle_minutes"] * 60


def _limit_hit(track):
    """The flat-plan budget signal: the driver ran into a usage limit. Prefer the
    STRUCTURED error the driver surfaced from the stream-json result event
    (track.last_subtype / last_error); fall back to the prose reply only when a
    turn predates that field (legacy tracks)."""
    subtype = (track.get("last_subtype") or "").lower()
    if subtype:
        err = (track.get("last_error") or "").lower()
        return ("limit" in subtype or "usage limit" in err or "rate limit" in err
                or "limit reached" in err)
    txt = (track.get("last_reply") or "").lower()
    return "usage limit" in txt or "rate limit" in txt or "limit reached" in txt


def status():
    s = _state()
    plan = latest_plan()
    return {"config": cfg(), "plan": plan, "report": latest_report(),
            "tonight": s.get(_today(), {"started": [], "limit_hit": False})}


def _tick():
    c = cfg()
    if not (c["enabled"] and c["repos"] and _in_window(c)):
        return
    with _lock:
        s = _state()
        night = s.setdefault(_today(), {"started": [], "limit_hit": False})
        # a hit usage limit pauses the shift for one Max-plan window (5h),
        # not the whole day - the quota comes back, so should the worker
        if night.get("limit_at") and time.time() - night["limit_at"] < 5 * 3600:
            return
        if len(night["started"]) >= c["max_cards"]:
            return
        if not _board_idle(c):
            return
        # THE BOARD IS THE QUEUE. The shift picks the next un-started backlog
        # card whose repo is on the night list - owner's repo order first,
        # then card priority. No shadow list: what you see is what runs.
        import sessions
        rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
        order = {os.path.normcase(r): i for i, r in enumerate(c["repos"])}
        todo = []
        for t in sessions.list_tracks():
            if t.get("lane") != "backlog":
                continue
            ri = order.get(os.path.normcase(t.get("repo") or ""))
            if ri is None or t["id"] in night["started"]:
                continue
            todo.append((ri, rank.get(t.get("priority"), 2), t.get("created", ""), t["id"], t))
        if not todo:
            return
        todo.sort()
        _, _, _, tid, t = todo[0]
        night["started"].append(tid)
        _save_state(s)                        # claim BEFORE the long run
        print("NIGHTSHIFT working: %s (%s)" % (t.get("task", "")[:60], t.get("repo")))
        # blocks for the whole first agent turn - the shift is one worker
        t = sessions.move_lane(tid, "working", actor="nightshift")
        if _limit_hit(t):                     # flat-plan budget signal -> pause one 5h window
            night["limit_hit"] = True
            night["limit_at"] = time.time()
            print("NIGHTSHIFT: usage limit reported - pausing ~5h until the window resets")
        _save_state(s)
        verdict = _pre_review(t)
        _report(t, {"title": t.get("task", "")}, t.get("repo", ""), verdict)


def start():
    """Background ticker; cheap no-op while disabled or outside the window."""
    def loop():
        while True:
            try:
                _tick()
            except Exception as e:   # the night shift must never kill the daemon
                try:
                    import events
                    events.log("nightshift", "tick error: %s" % e)
                except Exception:
                    pass
            time.sleep(120)
    threading.Thread(target=loop, daemon=True, name="nightshift").start()
