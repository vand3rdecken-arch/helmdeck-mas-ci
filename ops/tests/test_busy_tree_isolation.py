# -*- coding: utf-8 -*-
"""Pins BUSY-TREE ISOLATION (owner 2026-09-25: "Henry macht nicht selbstaendig
einen neuen Worktree auf, vor allem wenn ein Kartenagent bereits arbeitet").

A live-tree (direct) card dispatched while ANOTHER card is building in the
same repo's live tree must get its own worktree at dispatch - decided by code
(dispatch.tree_occupant), not by queueing 960s on the per-tree turn lock and
bouncing. Runs the REAL dispatch path: new_direct_task(dispatch=True) ->
move_lane -> _start -> _start_inner -> worktree -> _turn, with only the
driver subprocess stubbed.

Pins:
  1. free tree: the card stays on the live tree (direct, cwd == repo);
  2. busy tree: the card is re-shaped into a worktree card (direct=False,
     real `git worktree` checkout, isolated_from = the occupant) and its turn
     RUNS in that worktree, not the live tree;
  3. a direct card that is NOT in lane working (backlog, done) does not occupy.

Run: py -3.12 ops/tests/test_busy_tree_isolation.py
"""
import os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SANDBOX = tempfile.mkdtemp(prefix="hd-busytree-sb-")
from spine.storage import db as _db
_db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
_db.init()
from spine.ops import runs as _runs
_runs.REC = os.path.join(SANDBOX, "runs"); os.makedirs(_runs.REC, exist_ok=True)
from cells.engineer.cards import sessions, dispatch
sessions.REC = dispatch.REC = _runs.REC
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


SETTINGS = dict(events.settings())
SETTINGS.update({"policy": {}, "desktop_lock_wait_s": 5, "value_per_card": 0})
events.settings = lambda: SETTINGS
emitted = []
events.emit = lambda *a, **k: emitted.append((a, k))
trackstore._db = FakeDB()
from spine.comms import notify
notify.card_event = lambda *a, **k: None

ran_in = {}
def fake_run(cfg, t, prompt, by=None):
    ran_in[t["id"]] = t.get("worktree")
    return ("sid-" + t["id"], "done", {})
drivers.run = fake_run

tmp = tempfile.mkdtemp(prefix="hd-busytree-")
repo = os.path.join(tmp, "repo")
os.makedirs(repo)
for cmd in (["git", "init", "-q", repo],
            ["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-q", "--allow-empty", "-m", "base"]):
    subprocess.run(cmd, check=True)
norm = lambda p: os.path.normcase(os.path.abspath(p or ""))

# --- 1) free tree: stays direct ---------------------------------------------
a = sessions.new_direct_task(repo, "first card", dispatch=True)
a = trackstore._db.track_get(a["id"])
check("free tree: card stays on the live tree", a.get("direct") is True)
check("free tree: its turn ran in the repo root", norm(ran_in[a["id"]]) == norm(repo))
check("free tree: no isolation marker", not a.get("isolated_from"))

# --- 2) busy tree: own worktree ---------------------------------------------
def _hold(tt):
    tt["lane"] = "working"
trackstore._mutate(a["id"], _hold)          # A is building in the live tree
check("occupant detected", (dispatch.tree_occupant(repo) or {}).get("id") == a["id"])
b = sessions.new_direct_task(repo, "second card while first builds", dispatch=True)
b = trackstore._db.track_get(b["id"])
check("busy tree: card re-shaped to a worktree card", b.get("direct") is False
      and b.get("machine") is False)
check("busy tree: isolated_from names the occupant", b.get("isolated_from") == a["id"])
check("busy tree: real branch, not the (direct) marker",
      b.get("branch") not in (dispatch.DIRECT_BRANCH, "") and "iso-" in b["branch"])
check("busy tree: worktree exists and is NOT the live tree",
      os.path.isdir(b.get("worktree") or "") and norm(b["worktree"]) != norm(repo))
check("busy tree: its turn ran IN the worktree", norm(ran_in[b["id"]]) == norm(b["worktree"]))
wts = subprocess.run(["git", "-C", repo, "worktree", "list"], capture_output=True,
                     text=True).stdout
check("git knows the worktree", b["branch"] in wts)
check("isolated event emitted", any(x[0][0] == "isolated" for x in emitted))

# --- 3) non-working direct cards do not occupy ------------------------------
def _park(tt):
    tt["lane"] = "done"
trackstore._mutate(a["id"], _park)
check("a done direct card does not occupy", dispatch.tree_occupant(repo) is None)

subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", b["worktree"]])
print("PASS test_busy_tree_isolation")
