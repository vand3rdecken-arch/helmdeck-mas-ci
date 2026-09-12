# -*- coding: utf-8 -*-
"""Pins backlog/direct-cards-never-land (owner report 2026-09-12: "Henry
schiebt Karten mit Antworten nicht auf Review/Done und shipt nicht").
Henry's broker decided every escalation it got; the engineer cell never
SENT one for the card classes that are the default today. Three causes,
three pins, each RED on the pre-fix code:

  1. FIRST turn of a direct fast-track card lands: dispatch._start_machine
     runs the same landing branch as the steer path -> autocommit + a
     ship-decision escalation, no owner move (was: nothing at all).
  2. A plain direct card (no fast_track) that parks needs_you emits
     delivered-parked (was: excluded as "has its own pipeline").
  3. A worktree card whose DELIVERED sits past char 200 emits
     delivered-parked (was: regex on the first 200 chars only).
  + the ship decision row carries ship_kind (audit).

Self-sandboxing: FakeDB, patched settings/emit/notify, stubbed _turn, temp
git repo, in-memory escalation bus. Run: py -3.12 ops/tests/test_direct_cards_land.py
"""
import os, subprocess, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SANDBOX = tempfile.mkdtemp(prefix="hd-direct-land-")
from spine.storage import db as _db
_db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
_db.init()
from spine.ops import runs as _runs
_runs.REC = os.path.join(SANDBOX, "runs"); os.makedirs(_runs.REC, exist_ok=True)
from spine.registry import escalations
from cells.engineer.cards import sessions, lanemachine, dispatch
sessions.REC = _runs.REC
from spine.storage import trackstore
from spine.comms import notify


class FakeDB:
    def __init__(self):
        self.tracks = {}
    def tracks_all(self):
        return [dict(t) for t in self.tracks.values()]
    def tracks_replace(self, ts):
        self.tracks = {t["id"]: dict(t) for t in ts}
    def track_put(self, t):
        self.tracks[t["id"]] = dict(t)
    def track_get(self, tid):
        t = self.tracks.get(tid)
        return dict(t) if t else None


def check(desc, ok):
    assert ok, desc
    print("  ok: " + desc)


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def wait_ship(timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        ships = [th for th in threading.enumerate() if "_ship" in th.name]
        if not ships:
            return
        for th in ships:
            th.join(max(0.1, deadline - time.time()))


tmp = tempfile.mkdtemp(prefix="hd-direct-land-")
repo = os.path.join(tmp, "repo")
os.makedirs(repo)
git(repo, "init", "-q"); git(repo, "config", "user.email", "t@t.t"); git(repo, "config", "user.name", "t")
with open(os.path.join(repo, "base.txt"), "w", encoding="utf-8") as f:
    f.write("base\n")
git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "init")

SETTINGS = {"drivers": {"claude": {"type": "claude"}}, "policy": {},
            "desktop_lock_wait_s": 5, "value_per_card": 0,
            "repo_hooks": {os.path.abspath(repo): {"deploy": "echo deploy"}}}
events.settings = lambda: SETTINGS
events.emit = lambda *a, **k: None
events.read_events = lambda: []
notify.card_event = lambda *a, **k: None
notify.push_fcm = lambda *a, **k: None
trackstore._db = FakeDB()

# in-memory escalation bus - the real append is the live db (guarded)
BUS = []
escalations._append = lambda rec: (BUS.append(dict(rec, ts=time.strftime("%Y-%m-%dT%H:%M:%S"))), BUS[-1])[1]
escalations.records = lambda: list(BUS)
lanemachine._gate = lambda t: (True, [])
lanemachine._merge_to_main = lambda t: (True, "merged", "ok")


def opens(kind, card):
    return [r for r in BUS if r.get("event") == "open" and r.get("kind") == kind and r.get("card") == card]


# -- 1) first turn of a direct fast-track card lands ---------------------------
def turn_edit(t, prompt, model=None, perm=None):
    with open(os.path.join(t["worktree"], "new_file.txt"), "w", encoding="utf-8") as f:
        f.write("edited\n")
    return ("sid-1", "DELIVERED: done.", {"usage": {}, "models": [], "cost_usd": 0.0})


dispatch._turn = sessions._turn = turn_edit
# the PM/owner path for a QUICK fix: new_direct_task(fast_track=True) - no steer follows
t = sessions.new_direct_task(repo, "quick fix", actor="owner", dispatch=True, fast_track=True)
wait_ship()
tid = t["id"]
cur = trackstore._db.track_get(tid)
check("1. direct+fast_track card ran its first turn to needs_you", cur["status"] == "needs_you")
check("1. FIRST turn autocommitted the edit (no steer needed)", git(repo, "ls-files", "new_file.txt")[1] != "")
check("1. ship-decision escalation open after the FIRST turn", len(opens("ship-decision", tid)) == 1)
check("1. delivered-parked also open - Henry can land the card", len(opens("delivered-parked", tid)) == 1)

# -- 2) plain direct card (no fast_track) parks -> delivered-parked -----------
dispatch._turn = sessions._turn = lambda t, p, model=None, perm=None: (
    "sid-2", "Working tree is clean, committed as abc123. Finding: nothing to build.",
    {"usage": {}, "models": [], "cost_usd": 0.0})
t2 = sessions.new_direct_task(repo, "investigate", actor="owner", dispatch=True, fast_track=False)
wait_ship()
check("2. plain direct card parks needs_you", trackstore._db.track_get(t2["id"])["status"] == "needs_you")
check("2. delivered-parked open although the reply has no DELIVERED literal",
      len(opens("delivered-parked", t2["id"])) == 1)

# -- 3) worktree card, DELIVERED past char 200 -------------------------------
late = "I fixed the cause, and the chat works again. " * 6 + "\n\nDELIVERED: root cause fixed."
assert "DELIVERED" not in late[:200]
dispatch._turn = sessions._turn = lambda t, p, model=None, perm=None: (
    "sid-3", late, {"usage": {}, "models": [], "cost_usd": 0.0})
t3 = sessions.new_track(repo, "late-delivered", "fix chat")
t3 = sessions._start(t3["id"])
check("3. worktree card parks needs_you", trackstore._db.track_get(t3["id"])["status"] == "needs_you")
check("3. delivered-parked open with DELIVERED past char 200", len(opens("delivered-parked", t3["id"])) == 1)

# -- 4) a card ASKING the owner still does not escalate (rail kept) ----------
asking = trackstore._db.track_get(t3["id"])
asking["question"] = {"id": "q1", "kind": "choice", "questions": [{"header": "x"}]}
BUS_len = len(BUS)
from cells.engineer.cards import turnrunner
turnrunner._emit_delivered_parked(asking, "needs_you", "which one?")
check("4. a pending owner question never becomes delivered-parked", len(BUS) == BUS_len)

# -- 5) decision row carries ship_kind ---------------------------------------
escalations.record_decision("ship-decision-1", "ship", card=tid, why="js only", kind="ota")
check("5. ship decision records ship_kind", BUS[-1].get("ship_kind") == "ota")
escalations.record_decision("x-1", "move", card=tid, why="")
check("5. non-ship decision has no ship_kind", "ship_kind" not in BUS[-1])

print("test_direct_cards_land: PASS")
