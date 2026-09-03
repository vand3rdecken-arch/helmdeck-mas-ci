# -*- coding: utf-8 -*-
"""Pins the DIRECT build card (Paseo semantics, added 2026-08-17).

new_direct_task files a card whose workplace is the repo's LIVE working tree:
no worktree, no branch, no merge, no gate (registered: debt direct-build-no-gate).
It rides the machine path (machine=True) but keeps the PLAIN coding driver -
a direct build must NOT take the single desktop lock while it compiles.

Pins:
  1. filing: machine=True + direct=True, worktree = the repo root itself,
     branch '(direct)', driver stays 'claude' (machine_task forces
     claude-desktop; direct must not);
  2. a non-repo folder is refused (direct builds edit a repo's tree);
  3. policy.machine.enabled=false switches it off;
  4. two direct turns on the SAME tree serialize (second queues, then runs);
     a direct turn on a DIFFERENT tree is not blocked.

Self-sandboxing: fake DB, patched settings/emit, stubbed drivers.run, temp
git repos - nothing touches the real board or spawns anything.

Run: py -3.12 ops/tests/test_direct_task.py
"""
import os, subprocess, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.storage import events
from cells.engineer.cards import sessions
from spine.agent import drivers
from spine.storage import trackstore


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


SETTINGS = {"drivers": {"claude": {"type": "claude"}},
            "policy": {}, "desktop_lock_wait_s": 5, "value_per_card": 0}
events.settings = lambda: SETTINGS
events.emit = lambda *a, **k: None
trackstore._db = FakeDB()

tmp = tempfile.mkdtemp(prefix="hd-direct-")
repo = os.path.join(tmp, "repo")
os.makedirs(repo)
subprocess.run(["git", "init", "-q", repo], check=True)
plain = os.path.join(tmp, "plain")
os.makedirs(plain)

# --- 1) filing semantics ---------------------------------------------------
t = sessions.new_direct_task(repo, "build the thing", dispatch=False)
check("machine=True (rides the no-worktree path)", t.get("machine") is True)
check("direct=True (serialized per tree)", t.get("direct") is True)
check("workplace IS the live repo tree", t.get("worktree") == os.path.abspath(repo))
check("branch is the '(direct)' marker", t.get("branch") == sessions.DIRECT_BRANCH)
check("driver stays plain claude (no desktop lock)", t.get("driver") == "claude")
check("filed un-started (dispatch=False)", t.get("lane") == "backlog")

# --- 2) refuses a non-repo folder ------------------------------------------
try:
    sessions.new_direct_task(plain, "x", dispatch=False)
    check("non-repo folder refused", False)
except RuntimeError as e:
    check("non-repo folder refused", "not a git repo" in str(e))

# --- 3) policy switch ------------------------------------------------------
SETTINGS["policy"] = {"machine": {"enabled": False}}
try:
    sessions.new_direct_task(repo, "x", dispatch=False)
    check("policy.machine.enabled=false refuses", False)
except RuntimeError as e:
    check("policy.machine.enabled=false refuses", "switched off" in str(e))
SETTINGS["policy"] = {}

# --- 4) per-tree serialization through the real _turn ----------------------
_release = threading.Event()

def fake_run(cfg, t, prompt, by=None):
    if t["id"] == "holder":
        _release.wait(timeout=30)
    return ("sid-" + t["id"], "ok", {})

drivers.run = fake_run

def dtrack(tid, tree):
    d = tempfile.mkdtemp(prefix="hd-direct-run-")
    return {"id": tid, "driver": "claude", "model": "opus", "machine": True,
            "direct": True, "worktree": tree, "repo": tree, "run_dir": d}

out = {}
def turn_in_thread(t):
    def _go():
        try:
            out[t["id"]] = sessions._turn(t, "go")
        except Exception as e:
            out[t["id"]] = e
    th = threading.Thread(target=_go, daemon=True)
    th.start()
    return th

other = os.path.join(tmp, "other")
os.makedirs(other)

th1 = turn_in_thread(dtrack("holder", repo))
time.sleep(0.5)
th3 = turn_in_thread(dtrack("elsewhere", other))   # different tree: free to run
th3.join(10)
check("a direct turn on a DIFFERENT tree is not blocked",
      isinstance(out.get("elsewhere"), tuple))
th2 = turn_in_thread(dtrack("second", repo))       # same tree: must queue
time.sleep(0.5)
check("second direct card on the same tree queued (no bounce)",
      "second" not in out)
_release.set()
th1.join(10); th2.join(10)
check("holder completed", isinstance(out.get("holder"), tuple))
check("queued card RAN after the tree freed", isinstance(out.get("second"), tuple))
check("tree lock free at the end",
      not sessions._direct_lock_for(repo).locked())

print("PASS test_direct_task")
