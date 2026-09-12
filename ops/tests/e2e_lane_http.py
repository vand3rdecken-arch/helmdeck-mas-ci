# -*- coding: utf-8 -*-
"""LIVE end-to-end check of the lane-move HTTP path (the seam the unit test in
test_lane_visibility.py cannot reach, because it calls sessions.move_lane
directly and mocks the chat writer).

Boots the REAL daemon HTTP server on a spare port against a throwaway sandbox
(its own users.json / settings.json / helmdeck.db / chat log - never the
owner's), logs in as a real owner, and drags a card to Done while the gate is
made artificially slow.

Proves the three claims that only the live path can prove:
  1. POST /tracks/<id>/lane returns IMMEDIATELY with {started, gating:true}
     instead of blocking for the length of the gate (the old behaviour)
  2. GET /tracks shows status "gating" WHILE the gate is still running, so the
     board has something to render
  3. when it finishes, the card is accepted AND the real copilot.say() (not a
     mock) has written the outcome into the owner's chat, readable through
     GET /chat/history exactly as the app reads it

Named e2e_* so ops/tools/run_gate.py skips it: it binds a port and boots a server.

STATUS 2026-08-30: RUNS AGAIN, STILL RED - and the red is THIS FILE, not the
product. Do not read the failures below as a regression.

It was dead (ModuleNotFoundError at import) from the day the tree became
spine/cells/surfaces/ops. The imports are fixed and it executes, which is how
the remaining problem became visible at all: its STUBS point at seams that no
longer exist. It patches sessions._gate / _autocommit / _merge_to_main, but that
machinery moved into cells/engineer/lanemachine.py in the same split, so the
patches bind nothing and the real git path runs against a fixture that was never
a git repo. Finishing it means re-pointing every stub at the lanemachine seam and
re-proving all three claims - a card's worth of work, tracked as
`e2e-harnesses-stale-after-split` in spine/registry/debt.py.

What it already proves by running: the reclaim guard (lanemachine.py:179) and
the dirty-tree check now fire BEFORE the gate, which is newer behaviour than
this file knew about.
Run directly:  py -3.12 ops/tests/e2e_lane_http.py
"""
import json, os, sys, tempfile, threading, time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
# REPO ROOT. This pointed at "<repo>/daemon" and did `import auth, db, events` -
# dead since the tree became spine/cells/surfaces/ops, and silently so, because
# an unrunnable check compiles exactly like a passing one.
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

SANDBOX = tempfile.mkdtemp(prefix="helmdeck-e2e-")

# -- redirect EVERY store to the sandbox BEFORE anything reads them -----------
from spine.auth import auth
from spine.storage import db, events

auth.USERS = os.path.join(SANDBOX, "users.json")
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
db._LEGACY_DB = os.path.join(SANDBOX, "legacy.db")
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")

from cells.copilot.chat import copilot
from cells.engineer.cards import sessions
from spine.http import server

# role="tool": this process owns no driver sessions, so it must never be allowed
# to devalue persisted lifecycle state (db.init's own docstring).
db.init(role="tool")

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


# -- the slow seams: a gate that takes GATE_SECS, no real git/merge/hook ------
GATE_SECS = 6.0
gate_started = threading.Event()

_real_move = sessions.move_lane


def slow_gate(t):
    gate_started.set()
    time.sleep(GATE_SECS)
    return True, []


sessions._gate = slow_gate
sessions._autocommit = lambda t: True
sessions._repo_hook = lambda t, kind: True
sessions._merge_to_main = lambda t: (True, "merged", "1 commit nach main gemergt")

# -- a real owner + a real card ----------------------------------------------
auth.create_user("owner1", "test-pw-12345", "owner")

RUN = os.path.join(SANDBOX, "run")
WT = os.path.join(SANDBOX, "wt")
os.makedirs(RUN, exist_ok=True)
os.makedirs(WT, exist_ok=True)
# The .git marker is the fixture keeping up with the PRODUCT, not a workaround:
# lanemachine.py:179 refuses to gate a worktree that has no .git, because a
# RECLAIMED tree leaves the directory behind and the gate would otherwise run in
# an empty dir and report a punch list that reads like catastrophic code failure.
# That guard was added while this file sat dead, so the fixture never learned
# about it - the card here has always meant "a card with a live worktree", and
# this is what that now looks like. (The gate itself is stubbed below, so no
# real git repo is needed - only the marker the guard reads.)
os.makedirs(os.path.join(WT, ".git"), exist_ok=True)

CARD = {"id": "e2e-card", "repo": SANDBOX, "branch": "b-e2e", "worktree": WT,
        "task": "E2E Testkarte", "description": "", "client": "", "session_id": None,
        "perm": "acceptEdits", "lane": "review", "status": "submitted", "turns": 2,
        "run_dir": RUN, "last_reply": "", "value": 100.0, "driver": "claude",
        "priority": "medium", "due": "", "rank": None, "model": "", "attachments": [],
        "project_id": None, "billing": "fixed", "rate": None, "ai_cost": 0.25,
        "tokens_in": 10, "tokens_out": 20, "models": [], "mode": "auto",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
sessions._save_track(CARD)

# -- boot the REAL server -----------------------------------------------------
PORT = 8199
threading.Thread(target=lambda: server.serve(PORT), daemon=True).start()
BASE = "http://127.0.0.1:%d" % PORT


def req(method, path, body=None, sid=None, want_cookie=False):
    """The daemon authenticates with an sd_session COOKIE (see server._sid)."""
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if sid:
        r.add_header("Cookie", "sd_session=" + sid)
    with urllib.request.urlopen(r, timeout=30) as f:
        out = json.loads(f.read().decode() or "{}")
        if want_cookie:
            raw = f.headers.get("Set-Cookie") or ""
            return out, raw.split("sd_session=")[1].split(";")[0] if "sd_session=" in raw else None
        return out


for _ in range(60):                       # wait for the port to answer
    try:
        urllib.request.urlopen(BASE + "/health", timeout=1).read()
        break
    except urllib.error.HTTPError:
        break                             # answering (401/404) = it is up
    except Exception:
        time.sleep(0.25)

print("lane-move HTTP end-to-end (real server on :%d)" % PORT)

_out, tok = req("POST", "/auth/login", {"name": "owner1", "password": "test-pw-12345"}, want_cookie=True)
check(bool(tok), "owner can log in against the live server")

# -- 1. the move must NOT block for the gate ---------------------------------
t0 = time.time()
res = req("POST", "/tracks/e2e-card/lane", {"lane": "done"}, tok)
elapsed = time.time() - t0

check(elapsed < GATE_SECS / 2,
      "POST /lane returns in %.2fs, well under the %.0fs gate (was: blocked for it)"
      % (elapsed, GATE_SECS))
check(res.get("gating") is True and res.get("started") == "e2e-card",
      "the reply is {started, gating:true}, not a finished Track: %s" % res)

# -- 2. the board can SEE it working -----------------------------------------
check(gate_started.wait(timeout=10), "the gate actually started on a background thread")
mid = [t for t in req("GET", "/tracks", None, tok) if t["id"] == "e2e-card"]
check(bool(mid) and mid[0].get("status") == "gating",
      "GET /tracks shows status 'gating' WHILE the gate runs (board renders it)")

# -- 3. the outcome lands on the card AND in the chat ------------------------
def await_terminal(tid, timeout=GATE_SECS + 30):
    """Poll until the card reaches a TERMINAL status. Deliberately not
    'anything but gating': a card starts as 'submitted', so that check races
    the background thread and reads the pre-move value."""
    end = time.time() + timeout
    cur = {}
    while time.time() < end:
        cur = ([t for t in req("GET", "/tracks", None, tok) if t["id"] == tid] or [{}])[0]
        if cur.get("status") in ("accepted", "bounced"):
            return cur
        time.sleep(0.4)
    return cur


final = await_terminal("e2e-card")

check(final.get("status") == "accepted" and final.get("lane") == "done",
      "the card finishes accepted + in Done (status=%s lane=%s)"
      % (final.get("status"), final.get("lane")))

msgs = (req("GET", "/chat/history", None, tok) or {}).get("messages", [])
texts = [m.get("text", "") for m in msgs]
check(any("E2E Testkarte" in x for x in texts),
      "the REAL copilot.say wrote the outcome into the owner's chat")
check(any("gemergt" in x or "abgenommen" in x for x in texts),
      "the chat message states what happened: %s" % (texts[-1][:80] if texts else "(none)"))
check(any(m.get("cls") == "pm" for m in msgs),
      "it is tagged cls='pm' so the app renders it as a board-agent message")

# -- 4. THE BOUNCE: a red gate must not be silent -----------------------------
# This is the reported symptom: drag to Done, work happens, the card bounces,
# and nothing says so. The card must stay on Review and the chat must carry the
# actual gate output (not just "it failed").
CARD2 = dict(CARD, id="e2e-bounce", branch="b-bounce", task="E2E Bounce-Karte")
sessions._save_track(CARD2)
sessions._gate = lambda t: (False, [
    "gate command failed (py -3.12 ops/tools/run_gate.py):\nFAIL test_thing.py\nAssertionError: lane != done"])

res2 = req("POST", "/tracks/e2e-bounce/lane", {"lane": "done"}, tok)
check(res2.get("gating") is True, "a doomed move is backgrounded too, not blocked")

b = await_terminal("e2e-bounce")

check(b.get("status") == "bounced" and b.get("lane") == "review",
      "the bounced card STAYS on Review (status=%s lane=%s)" % (b.get("status"), b.get("lane")))
check(bool(b.get("gate_report")), "the card carries the gate_report for the board to show")

msgs2 = (req("GET", "/chat/history", None, tok) or {}).get("messages", [])
texts2 = [m.get("text", "") for m in msgs2]
bounce_msgs = [x for x in texts2 if "Bounce-Karte" in x]
check(bool(bounce_msgs), "THE BOUNCE IS ANNOUNCED IN CHAT (the reported bug)")
check(any("test_thing.py" in x for x in bounce_msgs),
      "the chat message carries the REAL gate output, not just 'failed'")
check(any("Review" in x for x in bounce_msgs),
      "the chat message says where the card now is")

print()
for x in texts2:
    print("  chat> " + x[:120])

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("all live lane-move checks passed")
