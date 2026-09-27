# -*- coding: utf-8 -*-
"""Pins: a card that was FILED and STARTED, then whose first turn died, is
reported to Henry as exactly that - with its id - never as "didn't run".

2026-09-26: a direct_task worker died 8 minutes in ("claude stream ended with
no result"); the action result was just that message, with no card id, under
a report header saying "ein Fehler heisst: die Aktion ist NICHT gelaufen".
Henry told the owner the build never started and filed a twin beside the dead
card. Runs the REAL path copilot_actions._run_action -> new_direct_task ->
move_lane -> _start -> _start_inner, with only the driver subprocess stubbed
(to die the way the real one did). Fails on the old code: the result carried
no card id.

Run: py -3.12 ops/tests/test_start_failed_names_card.py
"""
import os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SANDBOX = tempfile.mkdtemp(prefix="hd-startfail-sb-")
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


tmp = tempfile.mkdtemp(prefix="hd-startfail-")
repo = os.path.join(tmp, "repo")
os.makedirs(repo)
for cmd in (["git", "init", "-q", repo],
            ["git", "-C", repo, "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "-q", "--allow-empty", "-m", "base"]):
    subprocess.run(cmd, check=True)

SETTINGS = dict(events.settings())
SETTINGS.update({"policy": {}, "desktop_lock_wait_s": 5, "value_per_card": 0,
                 "default_repo": repo})
events.settings = lambda: SETTINGS
events.emit = lambda *a, **k: None
trackstore._db = FakeDB()
from spine.comms import notify
notify.card_event = lambda *a, **k: None


def dying_run(cfg, t, prompt, by=None):
    raise RuntimeError("claude stream ended with no result: ")
drivers.run = dying_run

from cells.copilot.chat import copilot_actions

print("direct_task whose first turn dies:")
out = copilot_actions._run_action(
    {"type": "direct_task", "task": "fix the hero", "repo": repo}, "owner", role="owner")
print("  result:", out)
cards = [t for t in sessions.list_tracks() if t.get("task") == "fix the hero"]
check("the card exists", len(cards) == 1)
check("the result names that card", cards[0]["id"] in out)
check("the result says it was started", "gestartet" in out)
check("the card is bounced", cards[0].get("status") == "bounced")

print("direct_task refused before any card exists:")
out = copilot_actions._run_action(
    {"type": "direct_task", "task": "x", "repo": os.path.join(tmp, "nope")}, "owner", role="owner")
print("  result:", out)
check("no card id claimed", "Karte" not in out)
print("PASS")
