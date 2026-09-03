# -*- coding: utf-8 -*-
"""Headless test for LANE-MOVE VISIBILITY - the "it works in the background and
tells me nothing" bug class.

Moving a card to Review/Done runs the gate (a subprocess), then the merge, then
the deploy hook. All of that reported into the flight recorder, the event log
and a push - but NEVER into the board chat the owner actually reads, and the
card feed's long-poll was keyed on AGENT OUTPUT, which a lane move does not
produce. So an accept or a bounce looked like nothing happened.

Under test (all three seams):
  1. every terminal lane outcome speaks in the owner's chat (sessions._say_card)
  2. a landing pushes too (notify.card_event(t, "done") - was bounce-only)
  3. the card is published as status "gating" BEFORE the slow work, and the
     feed's change token counts the flight recorder, so lifecycle notes wake
     the long-poll with no agent running

Self-sandboxing: an in-memory board, the gate/merge/commit seams monkeypatched,
chat + push captured - no daemon, no git, no network, no LLM."""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp()

from spine.agent import claude_sessions
from cells.copilot.chat import copilot
from spine.comms import notify
from cells.engineer.cards import sessions
from cells.engineer.cards import lanemachine
from spine.storage import trackstore

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


# -- in-memory board + captured channels --------------------------------------
store = {}          # tid -> track dict (THE board)
chat = []           # copilot.say() -> what the owner would read
pushed = []         # notify.card_event() transitions

# MUST stay at least as WIDE as copilot.say's real signature. It did not: `card`
# was added to say() and not here, and _say_card's best-effort
# `except Exception: pass` swallowed the resulting TypeError - so all six chat
# assertions below silently tested nothing while this file still reported PASS.
# A stub narrower than the function it stands in for does not weaken a test, it
# DELETES it, and does so invisibly.
# `**kw` rather than a copied parameter list, because copying is what failed:
# the capture here only ever cares about `text`, so every other argument is
# noise this stub should absorb instead of re-declare.
copilot.say = lambda text, cls="pm", card=None, **kw: chat.append(text)
notify.card_event = lambda t, status: pushed.append(status)
notify.push_fcm = lambda *a, **k: None


class FakeDB:
    """Backs the SAME `store` dict, so trackstore._load/_find/_mutate/
    _save_track (called directly by lanemachine, not through sessions) see
    and mutate exactly what `store[tid]` reads/writes below."""
    def tracks_all(self):
        return list(store.values())
    def track_put(self, t):
        store[t["id"]] = t
    def track_get(self, tid):
        return store.get(tid)
    def track_delete(self, tid):
        store.pop(tid, None)


trackstore._db = FakeDB()

RUN = os.path.join(SANDBOX, "run")
WT = os.path.join(SANDBOX, "wt")
os.makedirs(RUN, exist_ok=True)
os.makedirs(WT, exist_ok=True)


class FakeEvents:
    """events.emit/read_events/_completion_mode without the append-only store."""
    @staticmethod
    def emit(*a, **k):
        pass

    @staticmethod
    def read_events():
        return []

    @staticmethod
    def _completion_mode(te, turns):
        return "auto"


sys.modules["spine.storage.events"] = FakeEvents


def card(tid, **kw):
    t = {"id": tid, "task": "Karte " + tid, "branch": "b-" + tid, "status": "submitted",
         "lane": "review", "repo": SANDBOX, "worktree": WT, "run_dir": RUN,
         "mode": "auto", "turns": 3, "ai_cost": 0.5, "value": 100}
    t.update(kw)
    store[tid] = t
    return t


def reset():
    store.clear(); chat[:] = []; pushed[:] = []


# The slow/dangerous seams: never run a real gate, merge or hook in a test.
lanemachine._autocommit = lambda t: True
lanemachine._repo_hook = lambda t, kind: True

print("lane-move visibility")

# -- 1. a GREEN landing speaks and pushes -------------------------------------
reset()
card("c-ok")
lanemachine._gate = lambda t: (True, [])
lanemachine._merge_to_main = lambda t: (True, "merged", "2 commits nach main gemergt")
out = sessions.move_lane("c-ok", "done", actor="owner")

check(out.get("lane") == "done" and out.get("status") == "accepted",
      "green Done lands the card (lane=done, status=accepted)")
check(any("gemergt" in m or "abgenommen" in m for m in chat),
      "a landing is REPORTED IN CHAT (was: silent)")
check("done" in pushed,
      "a landing PUSHES (notify.card_event 'done' - was bounce-only)")

# -- 2. a RED gate bounces, stays on Review, and says WHY ----------------------
reset()
card("c-gate")
lanemachine._gate = lambda t: (False, ["gate command failed (run_gate):\ntest_x.py exit 1"])
out = sessions.move_lane("c-gate", "done", actor="owner")

check(out.get("status") == "bounced" and out.get("lane") == "review",
      "red gate bounces and STAYS on Review")
check(any("Gate ist rot" in m for m in chat), "the bounce is REPORTED IN CHAT")
check(any("test_x.py" in m for m in chat),
      "the chat message carries the REASON, not just 'it failed'")
check("bounced" in pushed, "the bounce still pushes")

# -- 3. a merge CONFLICT on Done bounces with the resolve path -----------------
reset()
card("c-conf")
lanemachine._gate = lambda t: (True, [])
lanemachine._merge_to_main = lambda t: (False, "conflict", "kollidiert in daemon/pm.py")
lanemachine._pull_main_into_branch = lambda t: "markers:daemon/pm.py"
out = sessions.move_lane("c-conf", "done", actor="owner")

check(out.get("status") == "bounced" and out.get("lane") == "review",
      "merge conflict bounces and STAYS on Review")
check(any("konnte nicht landen" in m for m in chat),
      "the failed landing is REPORTED IN CHAT")
check(any("Konfliktmarkierungen" in m or "daemon/pm.py" in m for m in chat),
      "the chat message carries the resolve path")

# -- 4. the REVIEW preview reports its verdict --------------------------------
reset()
card("c-prev", lane="working", status="needs_you")
lanemachine._gate = lambda t: (True, [])
lanemachine._classify_merge = lambda t: ("mergeable", "sauber mergebar")
out = sessions.move_lane("c-prev", "review", actor="owner")

check(out.get("status") == "submitted" and out.get("lane") == "review",
      "a green Review rests the card on Review as submitted")
check(any("Done" in m for m in chat),
      "the Review verdict is REPORTED IN CHAT and names the next move")

# -- 5. "gating" is published BEFORE the slow work ----------------------------
# The whole point of backgrounding: a poller must see the card is busy while the
# gate subprocess runs, instead of an unchanged card for minutes.
reset()
card("c-slow")
seen = {}


def slow_gate(t):
    seen["status"] = (store.get("c-slow") or {}).get("status")
    return True, []


lanemachine._gate = slow_gate
lanemachine._merge_to_main = lambda t: (True, "merged", "ok")
sessions.move_lane("c-slow", "done", actor="owner")

check(seen.get("status") == "gating",
      "the card is published as 'gating' BEFORE the gate runs (board can show it)")
check((store["c-slow"]).get("status") == "accepted",
      "'gating' is transient - the terminal status overwrites it")

# -- 6. the feed's change token counts the FLIGHT RECORDER ---------------------
# Without this, a lane move (which writes notes but no agent output) left the
# long-poll token unchanged, so the woven lifecycle notes never reached the UI.
VRUN = os.path.join(SANDBOX, "vrun")
os.makedirs(VRUN, exist_ok=True)
claude_sessions.live_session_id = lambda t: None      # no agent session at all
track = {"id": "v", "run_dir": VRUN}

before = claude_sessions.transcript_version(track)
from spine.ops.actionlog import ActionLog
ActionLog(VRUN).log("note", "GATE FAILED - stays on Review")
after = claude_sessions.transcript_version(track)

check(after > before,
      "a lifecycle note BUMPS the transcript version with no agent running")

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("all lane-visibility checks passed")
