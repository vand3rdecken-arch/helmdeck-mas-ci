# -*- coding: utf-8 -*-
"""Pins FAST-TRACK on the no-worktree Paseo path (owner-decreed 2026-08-20,
debt fast-track-no-gate): worktree isolation kept a fast-track card exposed
to base drift for its entire open lifetime (a gate could red on code the
card never touched - debt gate-base-lag, hit live on card proc-20260816-s2).
The owner chose to drop isolation for this card class rather than build the
sync-loop fix: a fast_track card now dispatches onto the SAME no-worktree
rails as new_direct_task (dispatch._start_inner) - no branch, no
gate-before-review, no merge. sessions._maybe_fast_track_ship_direct ships
every finished turn via autocommit + deploy only.

Pins:
  1. dispatch: a fast_track (non-machine) card gets machine=True, direct=True,
     worktree = the repo root - and NO git worktree is ever created on disk;
  2. a NON-fast_track card is unaffected - still dispatches through the
     normal worktree-isolated path (regression guard);
  3. ship: a dirty tree after a finished turn autocommits and calls the
     deploy hook - and NEVER calls _gate or _merge_to_main;
  4. open conflict markers still block deploy (data hygiene, not a gate);
  5. a chat-only turn (clean tree) ships nothing.

Self-sandboxing: fake DB, patched settings/emit/notify, stubbed drivers.run,
a temp git repo - nothing touches the real board or spawns anything.

Run: py -3.12 daemon/test_fast_track_direct.py
"""
import os, subprocess, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from daemon.spine.storage import events
from daemon.cells.engineer import sessions
from daemon.cells.engineer import lanemachine
from daemon.cells.engineer import dispatch
from daemon.spine.agent import drivers
from daemon.spine.storage import trackstore
from daemon.spine.comms import notify


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


SETTINGS = {"drivers": {"claude": {"type": "claude"}},
            "policy": {}, "desktop_lock_wait_s": 5, "value_per_card": 0}
events.settings = lambda: SETTINGS
events.emit = lambda *a, **k: None
events.read_events = lambda: []
notify.card_event = lambda *a, **k: None
notify.push_fcm = lambda *a, **k: None
trackstore._db = FakeDB()

tmp = tempfile.mkdtemp(prefix="hd-fasttrack-direct-")
repo = os.path.join(tmp, "repo")
os.makedirs(repo)
git(repo, "init", "-q")
git(repo, "config", "user.email", "t@t.t")
git(repo, "config", "user.name", "t")
with open(os.path.join(repo, "base.txt"), "w", encoding="utf-8") as f:
    f.write("base\n")
git(repo, "add", "-A")
git(repo, "commit", "-q", "-m", "init")

gate_calls = []
merge_calls = []
deploy_calls = []
lanemachine._gate = lambda t: (gate_calls.append(t["id"]), (True, []))[1]
lanemachine._merge_to_main = lambda t: (merge_calls.append(t["id"]),
                                        (True, "merged", "ok"))[1]
lanemachine._repo_hook = lambda t, kind: (deploy_calls.append((t["id"], kind)), True)[1]
sessions._repo_hook = lanemachine._repo_hook


# -- 1) dispatch: fast_track card rides the no-worktree path -----------------
def fake_turn_edit(t, prompt, model=None, perm=None):
    with open(os.path.join(t["worktree"], "new_file.txt"), "w", encoding="utf-8") as f:
        f.write("edited by the agent\n")
    return ("sid-1", "DELIVERED: done.", {"usage": {}, "models": [], "cost_usd": 0.0})


dispatch._turn = sessions._turn = fake_turn_edit
t = sessions.new_track(repo, "my-feature-branch", "ship something fast", lane="backlog")
sessions._mutate(t["id"], lambda tt: tt.__setitem__("fast_track", True))
t = sessions._start(t["id"])

check("machine=True (rides the no-worktree path)", t.get("machine") is True)
check("direct=True (serialized per tree)", t.get("direct") is True)
check("workplace IS the live repo tree", os.path.normcase(t.get("worktree"))
      == os.path.normcase(os.path.abspath(repo)))
check("original branch name preserved (never checked out)",
      t.get("branch") == "my-feature-branch")
wt_dir = os.path.join(repo, ".git", "worktrees")
check("NO git worktree was ever created",
      not os.path.isdir(wt_dir) or not os.listdir(wt_dir))
check("the edit landed on the live tree", os.path.exists(os.path.join(repo, "new_file.txt")))

# -- 3) ship: autocommit + deploy, never gate or merge ------------------------
# fast-track's ship check fires from steer() (every turn AFTER the first, per
# the existing pre-change design - the dispatch turn itself never ships), so
# exercise a follow-up turn, not just the initial dispatch.
t = sessions.steer(t["id"], "one more thing")
time.sleep(2)   # _ship runs on a background thread
check("autocommit landed the edit", git(repo, "log", "--oneline", "-1")[1] != "")
check("deploy hook WAS called", (t["id"], "deploy") in deploy_calls)
check("_gate was NEVER called", not gate_calls)
check("_merge_to_main was NEVER called", not merge_calls)
check("card status untouched (still working, no lane change)",
      trackstore._db.track_get(t["id"])["lane"] == "working")


# -- 4) conflict markers still block deploy (data hygiene, not a gate) -------
deploy_calls.clear()


def fake_turn_conflict(t, prompt, model=None, perm=None):
    with open(os.path.join(t["worktree"], "new_file.txt"), "a", encoding="utf-8") as f:
        f.write("<<<<<<< HEAD\nmine\n=======\ntheirs\n>>>>>>> branch\n")
    return ("sid-2", "DELIVERED: done.", {"usage": {}, "models": [], "cost_usd": 0.0})


dispatch._turn = sessions._turn = fake_turn_conflict
t2 = sessions.new_track(repo, "conflict-branch", "second fast turn", lane="backlog")
sessions._mutate(t2["id"], lambda tt: tt.__setitem__("fast_track", True))
t2 = sessions._start(t2["id"])
t2 = sessions.steer(t2["id"], "one more thing")
time.sleep(2)
check("open conflict markers block deploy even with no gate",
      (t2["id"], "deploy") not in deploy_calls)
# clean the markers back out - later sections need a healthy shared tree
# (autocommit STAGED them before refusing, so restore from HEAD, not the index)
git(repo, "reset", "--hard", "HEAD")
check("test hygiene: tree clean again after the marker scenario",
      git(repo, "status", "--porcelain")[1] == "")


# -- 5) a chat-only turn (clean tree) ships nothing ---------------------------
deploy_calls.clear()
dispatch._turn = sessions._turn = lambda t, prompt, model=None, perm=None: (
    "sid-3", "DELIVERED: just talked, nothing changed.", {"usage": {}, "models": [], "cost_usd": 0.0})
t3 = sessions.new_track(repo, "chat-only-branch", "just a question", lane="backlog")
sessions._mutate(t3["id"], lambda tt: tt.__setitem__("fast_track", True))
t3 = sessions._start(t3["id"])
t3 = sessions.steer(t3["id"], "one more thing")
time.sleep(2)
check("chat-only turn (clean tree) ships nothing", not deploy_calls)


# -- 2) a NON-fast_track card is unaffected (regression guard) ---------------
dispatch._turn = sessions._turn = lambda t, prompt, model=None, perm=None: (
    "sid-4", "ok", {"usage": {}, "models": [], "cost_usd": 0.0})
plain = sessions.new_track(repo, "regular-card-branch", "normal card")
plain = sessions._start(plain["id"])
check("a non-fast_track card is NOT marked machine/direct",
      not plain.get("machine") and not plain.get("direct"))
check("a non-fast_track card gets a REAL worktree",
      plain.get("worktree") != os.path.abspath(repo)
      and os.path.isdir(plain.get("worktree") or ""))

# -- 6) toggle edge cases: promote to fast-track and back ---------------------
# 6a) toggle OFF on a live-tree (direct) card: deploys stop, but dirty state
#     lands NOW (nothing may sit uncommitted in the shared tree), and the card
#     STAYS direct - there is no worktree to go back to.
deploy_calls.clear()
with open(os.path.join(repo, "leftover.txt"), "w", encoding="utf-8") as f:
    f.write("uncommitted when fast-track was switched off\n")
t = sessions.update_track(t["id"], {"fast_track": False})
check("toggle OFF: card stays on the live-tree rails (direct kept)",
      t.get("direct") is True and t.get("machine") is True)
check("toggle OFF: dirty state was committed, not left invisible",
      git(repo, "status", "--porcelain")[1] == "")
check("toggle OFF: no deploy fired", not deploy_calls)

# 6b) toggle back ON: the immediate-ship hook must use the DIRECT ship (the
#     worktree ship would silently no-op on a machine-flagged card).
with open(os.path.join(repo, "again.txt"), "w", encoding="utf-8") as f:
    f.write("dirty again before re-enabling\n")
t = sessions.update_track(t["id"], {"fast_track": True})
time.sleep(2)
check("toggle back ON: direct ship fires immediately (autocommit + deploy)",
      (t["id"], "deploy") in deploy_calls and git(repo, "status", "--porcelain")[1] == "")
check("toggle round-trip: still no gate and no merge", not gate_calls and not merge_calls)

# 6c) toggle ON for a card that already STARTED worktree-isolated: it stays
#     isolated (session+branch hang off the worktree) - never converted.
plain = sessions.update_track(plain["id"], {"fast_track": True})
check("worktree card promoted to fast-track stays worktree-isolated",
      not plain.get("direct") and not plain.get("machine")
      and plain.get("worktree") != os.path.abspath(repo))

print("PASS test_fast_track_direct")
