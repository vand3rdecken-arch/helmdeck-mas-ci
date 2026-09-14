# -*- coding: utf-8 -*-
"""Pins the SHIP CARD mechanism (owner decree 2026-09-09, 18:04 correction:
"mehr als Process" means ship runs as its own visible board card - lane,
timeline, steerable, self-correcting like any other card - not an internal
multi-stage agent flow and not an invisible deploy-hook subprocess).

Pins:
  1. dispatch.new_ship_task files a direct-build card (no worktree, no
     branch, live repo root, bypassPermissions) carrying `ship_kind`, and
     drivers._agent_for resolves THAT card to the ship-worker brief, not
     machine-worker's - the whole reason ship_kind is checked first there.
  2. A card's FIRST turn dispatches through dispatch._start_machine, a
     completion path entirely separate from sessions.py's steer path (same
     split test_fast_track_direct.py already pins for fast-track's own
     hooks) - so the close-on-verdict hook must fire from BOTH, and this
     proves the dispatch-turn side specifically.
  3. A literal 'SHIP: OK' verdict line in the turn's reply self-closes the
     card to Done - no external accept, no owner click.
  4. A 'SHIP: FAILED' verdict (or a turn that produced no verdict line at
     all, e.g. a crash) leaves the card exactly where an ordinary
     unfinished turn parks it: visible, needs_you, lane unchanged.
  5. Accepting a ship card does NOT re-trigger request_ship_decision - the
     recursion _accept_machine's guard exists to prevent (card -> escalation
     -> Henry -> another card -> forever).
  6. board_hidden (2026-09-14): a decide card filed this way still runs the
     same DECIDE->EXECUTE->VERIFY card mechanics, but its verdict lands on
     the ORIGIN card's ActionLog (no board row of its own to read it on),
     and a stuck one escalates to Henry - dedup'd, not once per retry.

Self-sandboxing: fake DB, patched settings/emit/notify, stubbed turn driver,
a temp git repo - nothing touches the real board or spawns a real agent
(the underlying ops/deploy scripts + ship_verify.py are proven separately,
live, against the real repo - this file pins the WIRING around them).

Run: py -3.12 ops/tests/test_ship_card.py
"""
import os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import tempfile as _tf
SANDBOX = _tf.mkdtemp(prefix="hd-ship-card-db-")
from spine.storage import db as _db
_db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
_db.init()
from spine.ops import runs as _runs
_runs.REC = os.path.join(SANDBOX, "runs"); os.makedirs(_runs.REC, exist_ok=True)
from cells.engineer.cards import sessions
sessions.REC = _runs.REC
from cells.engineer.cards import lanemachine
from cells.engineer.cards import dispatch
from spine.agent import drivers
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


SETTINGS = {"drivers": {"claude": {"type": "claude"}},
            "policy": {}, "desktop_lock_wait_s": 5, "value_per_card": 0}
events.settings = lambda: SETTINGS
events.emit = lambda *a, **k: None
events.read_events = lambda: []
notify.card_event = lambda *a, **k: None
notify.push_fcm = lambda *a, **k: None
trackstore._db = FakeDB()

tmp = tempfile.mkdtemp(prefix="hd-ship-card-")
repo = os.path.join(tmp, "repo")
os.makedirs(repo)
git(repo, "init", "-q")
git(repo, "config", "user.email", "t@t.t")
git(repo, "config", "user.name", "t")
with open(os.path.join(repo, "base.txt"), "w", encoding="utf-8") as f:
    f.write("base\n")
git(repo, "add", "-A")
git(repo, "commit", "-q", "-m", "init")

ship_decision_calls = []
lanemachine.request_ship_decision = lambda t, origin: ship_decision_calls.append((t["id"], origin))

# -- 1) new_ship_task files a direct-build card carrying ship_kind, and the --
# -- FIRST turn (dispatch, not steer) already sees the right brief ----------
seen_agent = {}
def fake_turn_ok(t, prompt, model=None, perm=None):
    seen_agent["agent"] = drivers._agent_for(t)
    return ("sid-ok", "Diagnose ok. Execute ok. Verify ok.\nSHIP: OK",
            {"usage": {}, "models": [], "cost_usd": 0.0})


dispatch._turn = sessions._turn = fake_turn_ok
t = dispatch.new_ship_task(repo, "ota", actor="henry")

check("machine=True (rides the no-worktree path)", t.get("machine") is True)
check("direct=True (serialized per tree)", t.get("direct") is True)
check("ship_kind carried on the card", t.get("ship_kind") == "ota")
check("workplace IS the live repo tree", os.path.normcase(t.get("worktree"))
      == os.path.normcase(os.path.abspath(repo)))
check("drivers._agent_for resolves the SHIP brief on the DISPATCH turn "
      "(not machine-worker's)", seen_agent.get("agent") == drivers.SHIP_AGENT == "ship-worker")

# -- 2) a 'SHIP: OK' verdict self-closes the card to Done, from the ---------
# -- dispatch-turn completion path (dispatch._start_machine) ---------------
check("SHIP: OK on the FIRST turn self-closed the card to Done", t.get("lane") == "done")
check("accepting itself did NOT re-trigger request_ship_decision (no recursion)",
      not ship_decision_calls)

# -- 3) a 'SHIP: FAILED' verdict leaves the card exactly where an unfinished -
# -- turn parks it - visible, unchanged lane, no self-close -----------------
def fake_turn_failed(t, prompt, model=None, perm=None):
    return ("sid-fail", "Diagnose ok. Execute: build_apk.sh BUILD FAILED.\nSHIP: FAILED",
            {"usage": {}, "models": [], "cost_usd": 0.0})


dispatch._turn = sessions._turn = fake_turn_failed
t2 = dispatch.new_ship_task(repo, "native", actor="henry", origin_card="c-origin")
check("ship_origin carried through for traceability", t2.get("ship_origin") == "c-origin")
check("SHIP: FAILED does NOT self-close - card stays on working", t2.get("lane") == "working")
check("a failed ship card is needs_you like any other stuck card",
      t2.get("status") == "needs_you")

# -- 4) a turn with NO verdict line at all (e.g. a crash) also stays put ----
def fake_turn_crash(t, prompt, model=None, perm=None):
    return ("sid-crash", "started the build, then got interrupted.",
            {"usage": {}, "models": [], "cost_usd": 0.0})


dispatch._turn = sessions._turn = fake_turn_crash
t3 = dispatch.new_ship_task(repo, "ota", actor="henry")
check("no verdict line at all -> stays on working, not Done", t3.get("lane") == "working")

# -- 4b) a DECIDE card that finds nothing to ship closes itself on SHIP: NONE --
dispatch._turn = sessions._turn = lambda t, p, model=None, perm=None: (
    "sid-none", "DECISION: none" + chr(10) + "WHY: docs only, desktop-mac run green." + chr(10) + "SHIP: NONE",
    {"usage": {}, "models": [], "cost_usd": 0.0})
t4 = dispatch.new_ship_task(repo, "decide", actor="harness", origin_card="c-land")
check("decide card carries ship_kind=decide", t4.get("ship_kind") == "decide")
check("decide card speaks the SHIP brief too", drivers._agent_for(t4) == drivers.SHIP_AGENT)
check("SHIP: NONE self-closed the decide card to Done", t4.get("lane") == "done")
t5 = dispatch.new_ship_task(repo, "decide", actor="harness", dispatch=False)
check("dispatch=False files without starting a turn", t5.get("lane") != "done" and not t5.get("session_id"))

# -- 4b-2) board_hidden (owner decree 2026-09-14, third iteration): the ------
# -- decide-card mechanics above are UNCHANGED - what stops is the board ----
# -- row. lanemachine.request_ship_decision now files this way; the outcome -
# -- must land on the ORIGIN card's own ActionLog instead -------------------
from spine.ops.actionlog import ActionLog, read_timeline
from spine.registry import escalations
from spine.turn.blockers import blocker

origin_rd = os.path.join(tmp, "origin-run"); os.makedirs(origin_rd, exist_ok=True)
trackstore._db.track_put({"id": "c-hidden-origin", "repo": repo, "run_dir": origin_rd,
                          "task": "landing", "lane": "working", "status": "needs_you"})

dispatch._turn = sessions._turn = lambda t, p, model=None, perm=None: (
    "sid-hidden-none", "DECISION: none\nWHY: docs only.\nSHIP: NONE",
    {"usage": {}, "models": [], "cost_usd": 0.0})
t8 = dispatch.new_ship_task(repo, "decide", actor="harness", origin_card="c-hidden-origin",
                            board_hidden=True)
check("board_hidden decide card still self-closes on SHIP: NONE", t8.get("lane") == "done")
origin_notes = [r.get("detail") or "" for r in read_timeline(origin_rd)]
check("the verdict lands on the ORIGIN card's ActionLog (no board row of its own)",
     any("SHIP: NONE" in n for n in origin_notes))

def _ship_decision_opens():
    return [e for e in escalations.list_open()
            if e.get("kind") == "ship-decision" and e.get("card") == "c-hidden-origin"]

dispatch._turn = sessions._turn = lambda t, p, model=None, perm=None: (
    "sid-hidden-failed", "Execute: build failed.\nSHIP: FAILED",
    {"usage": {}, "models": [], "cost_usd": 0.0})
before = len(_ship_decision_opens())
t9 = dispatch.new_ship_task(repo, "decide", actor="harness", origin_card="c-hidden-origin",
                            board_hidden=True)
check("board_hidden + no OK/NONE verdict stays put, same as a visible card would",
     t9.get("lane") == "working" and t9.get("status") == "needs_you")
check("a stuck board_hidden ship escalates to Henry, targeted at the ORIGIN card, "
     "exactly once", len(_ship_decision_opens()) == before + 1)
check("blocker() never surfaces a board_hidden card as needs_you on any surface "
     "(glance/watch/board all read this one derivation)", blocker(t9) is None)

# a retry with the same still-failing outcome must not page Henry a second time
dispatch._maybe_ship_card_close(t9, ActionLog(t9["run_dir"]))
check("dedup: re-closing the same stuck card does not escalate twice",
     len(_ship_decision_opens()) == before + 1)

# -- 4c) the project's ship process rides in the task text (config, not brief) --
from spine.storage import projectconfig as _pc
_real_resolve = _pc.resolve
_pc.resolve = lambda path, project="": ({"value": "OTA: bash deploy/ota.sh", "layer": "project", "inherited": False}
                                        if path == "rule.ship.process.all" else _real_resolve(path, project))
try:
    t6 = dispatch.new_ship_task(repo, "decide", actor="harness", dispatch=False)
    check("ship.process row lands verbatim in the card's task", "OTA: bash deploy/ota.sh" in t6["task"])
    _pc.resolve = lambda path, project="": {"value": "", "layer": "default", "inherited": True}
    t7 = dispatch.new_ship_task(repo, "decide", actor="harness", dispatch=False)
    check("no process configured -> the task says so and points at DEPLOY.md", "DEPLOY.md" in t7["task"])
finally:
    _pc.resolve = _real_resolve

# -- 5) kind is validated - dispatch never guesses --------------------------
try:
    dispatch.new_ship_task(repo, "banana", actor="henry")
    check("bad kind refused", False)
except ValueError as e:
    check("bad kind refused", "none of the two" not in str(e) and "ota" in str(e))

print("PASS test_ship_card")
