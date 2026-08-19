# -*- coding: utf-8 -*-
"""P1 runtime hardening (Paseo adoption, phase 1) - pin the invariants that make
"no restart/timeout ever destroys a turn again" true:

1. sweep_idle is MULTI-GUARDED: past-TTL alone never evicts a session whose card
   is flagged running, that has a pending control request, that is protected, or
   whose turn lock/state is live. Only a genuinely idle session is reaped.
2. cancel() is COOPERATIVE: interrupt ack + terminal result -> clean cancel with
   the process left ALIVE (resumable). No ack -> hard tree-kill. Ack but no
   result within grace -> waiter released, process kept, and the turn's late
   result frame is SUPPRESSED so it can't falsely complete the next turn.
3. _spawn DEGRADES a stale resume: session transcript gone -> fresh session
   (no --resume) + a visible note in the card feed, not a hard spawn failure.
4. read_transcript renders '[Request interrupted by user...]' as a typed
   turn-lifecycle item, not as a prose bubble attributed to the owner.

Self-sandboxing: fake procs, patched _tree_kill/_record_pid/_running_cards and a
temp ~/.claude/projects - nothing spawns, kills or touches the real board.

Run: py -3.12 daemon/test_p1_runtime.py
"""
import json, os, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _subpaths; _subpaths.ensure_cell_paths()
import drivers
import claude_sessions
from drivers import _ClaudeSession

FAILS = []


def check(name, cond):
    print(("  ok  " if cond else "  FAIL") + " " + name)
    if not cond:
        FAILS.append(name)


# --- fakes -------------------------------------------------------------------

class FakeStdin:
    def __init__(self):
        self.lines = []
    def write(self, s):
        self.lines.append(s)
    def flush(self):
        pass


class FakeProc:
    def __init__(self, pid=4242):
        self.pid = pid
        self.stdin = FakeStdin()
        self.stdout = []
        self.stderr = []
        self._dead = False
    def poll(self):
        return 0 if self._dead else None
    def wait(self, timeout=None):
        return 0


killed = []
drivers._tree_kill = lambda proc, grace=2.0: killed.append(getattr(proc, "pid", None))
drivers._record_pid = lambda pid, spawn_time=None: None
drivers._forget_pid = lambda pid: None


def make_session(tid="card-1"):
    """A live-shaped session with NO process behind it.

    Built by running the REAL __init__ with only _spawn() stubbed out, rather
    than hand-listing attributes onto object.__new__. The hand-listed version
    rotted silently: __init__ later gained _bg_candidates, _bg_open,
    _spawn_resumed, _resume_echo and _first_turn_after_spawn, this fake kept its
    original attribute set, and the file died on AttributeError partway through
    - so every check after the cancel tests simply stopped running, and nothing
    said so because no gate ran this file. Deriving the state from the
    constructor means the fake cannot drift from the class again.

    _spawn() is the only thing stubbed, because it is the only part that touches
    the world (Popen, the pid registry, the background-task reconcile)."""
    real_spawn = _ClaudeSession._spawn
    _ClaudeSession._spawn = lambda self: None
    try:
        s = _ClaudeSession({}, {"id": tid, "worktree": ".", "session_id": "sess-live"})
    finally:
        _ClaudeSession._spawn = real_spawn
    s.brief = ""
    s.sig = ("acceptEdits", "", ())
    s.proc = FakeProc()
    s._alive = True
    s.last_used = time.time()
    s.spawn_time = time.time()
    return s


def new_cur():
    return {"parts": [], "result": None, "session_id": "sess-live",
            "done": threading.Event(), "live_path": os.devnull,
            "sid_path": os.devnull, "last_flush": 0.0}


def sent_req_id(s):
    body = json.loads(s.proc.stdin.lines[-1])
    return body["request_id"]


def ack(s, req_id, ok=True):
    s._on_event({"type": "control_response", "response": {
        "request_id": req_id, "subtype": "success" if ok else "error"}})


# --- 1. idle sweeper multi-guard --------------------------------------------
print("sweep_idle multi-guard:")
drivers._running_cards = lambda: {"card-running"}

idle = make_session("card-idle");     idle.last_used = 0
busy = make_session("card-running"); busy.last_used = 0
ctrl = make_session("card-ctrl");    ctrl.last_used = 0
ctrl._ctrl["sd-x"] = {"ev": threading.Event(), "resp": None}
prot = make_session("card-prot");    prot.last_used = 0
prot.cfg = {"protect_idle": True}
mid = make_session("card-midturn");  mid.last_used = 0
mid._turn_lock.acquire()
fresh = make_session("card-fresh")   # last_used = now

drivers._sessions.clear()
for s in (idle, busy, ctrl, prot, mid, fresh):
    drivers._sessions[s.tid] = s
gone = drivers.sweep_idle(ttl=60)
check("evicts only the genuinely idle session", gone == ["card-idle"])
check("evicted session was killed", not idle._alive)
check("running-flagged card survives", "card-running" in drivers._sessions)
check("pending control request survives", "card-ctrl" in drivers._sessions)
check("protected session survives", "card-prot" in drivers._sessions)
check("mid-turn (locked) session survives", "card-midturn" in drivers._sessions)
check("fresh session survives", "card-fresh" in drivers._sessions)
mid._turn_lock.release()
drivers._sessions.clear()

# --- 2a. cooperative cancel: ack + result -> process stays alive -------------
print("cancel - soft path (ack + result):")
killed.clear(); drivers._cancelled.clear()
s = make_session("card-soft")
cur = new_cur(); s._cur = cur
s.cancel(ack_timeout=1.0, grace=2.0)
req = sent_req_id(s)
check("interrupt control_request sent", '"interrupt"' in s.proc.stdin.lines[-1])
ack(s, req)
s._on_event({"type": "result", "subtype": "success", "result": "partial"})
check("waiter released by the terminal result", cur["done"].wait(2.0))
time.sleep(0.3)   # let the escort thread finish
check("result was consumed by the interrupted turn", cur["result"] is not None)
check("process NOT killed (session stays resumable)", s._alive and not killed)
check("no stale suppression armed", s._drop_results == 0)

# --- 2b. cooperative cancel: no ack -> hard kill -----------------------------
print("cancel - hung stream (no ack):")
killed.clear(); drivers._cancelled.clear()
s = make_session("card-hung")
cur = new_cur(); s._cur = cur
s.cancel(ack_timeout=0.2, grace=0.5)
check("waiter released", cur["done"].wait(3.0))
time.sleep(0.3)
check("tree-killed after missing ack", killed == [s.proc.pid])

# --- 2c. ack but result drags -> stale-result suppression --------------------
print("cancel - stale-result suppression:")
killed.clear(); drivers._cancelled.clear()
s = make_session("card-stale")
cur = new_cur(); s._cur = cur
s.cancel(ack_timeout=1.0, grace=0.3)
ack(s, sent_req_id(s))
check("waiter released after grace despite no result", cur["done"].wait(3.0))
time.sleep(0.3)
check("process kept alive", s._alive and not killed)
check("suppression armed", s._drop_results == 1)
s._cur = None                       # run_turn returned; next turn not started yet
s._on_event({"type": "result", "subtype": "success", "result": "STALE"})
check("late result frame swallowed", s._drop_results == 0)
cur2 = new_cur(); s._cur = cur2     # next turn's real result still lands
s._on_event({"type": "result", "subtype": "success", "result": "REAL"})
check("next turn's result completes normally",
      cur2["done"].is_set() and (cur2["result"] or {}).get("result") == "REAL")

# --- 3. stale-resume degradation ---------------------------------------------
print("_spawn stale-resume degradation:")
spawned = {}

class FakePopen:
    def __init__(self, argv, **kw):
        spawned["argv"] = argv
        self.pid = 777
        self.stdin = FakeStdin()
        self.stdout = []
        self.stderr = []
    def poll(self):
        return None

_popen, _find = drivers.subprocess.Popen, claude_sessions._find_transcript
drivers.subprocess.Popen = FakePopen
claude_sessions._find_transcript = lambda sid: None
tmp = tempfile.mkdtemp(prefix="hd-p1-")
try:
    t = {"id": "card-lost", "worktree": ".", "session_id": "deadbeefcafe",
         "run_dir": tmp}
    s = _ClaudeSession({}, t)
    time.sleep(0.2)   # fake pump/drain threads exit on their empty iterables
    check("session id dropped (fresh session)", s.session_id is None)
    check("no --resume in the spawn argv", "--resume" not in spawned["argv"])
    try:
        with open(os.path.join(tmp, "actions.jsonl"), encoding="utf-8") as f:
            notes = f.read()
    except OSError:
        notes = ""
    check("visible note in the card feed", "frische Session" in notes)
finally:
    drivers.subprocess.Popen = _popen
    claude_sessions._find_transcript = _find

# --- 4. interrupt marker in the transcript -----------------------------------
print("read_transcript interrupt marker:")
proj = tempfile.mkdtemp(prefix="hd-p1-proj-")
_projects = claude_sessions.PROJECTS
claude_sessions.PROJECTS = proj
try:
    os.makedirs(os.path.join(proj, "p1"))
    sid = "11111111-2222-3333-4444-555555555555"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "mach was"},
         "timestamp": "2026-08-06T10:00:00Z"},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": "[Request interrupted by user for tool use]"}]},
         "timestamp": "2026-08-06T10:01:00Z"},
    ]
    with open(os.path.join(proj, "p1", sid + ".jsonl"), "w", encoding="utf-8") as f:
        for d in lines:
            f.write(json.dumps(d) + "\n")
    steps = claude_sessions.read_transcript(sid)
    # The RENDERING changed in Phase 3.2 and this expectation had not: an
    # interrupt used to be a kind="system" step whose German text contained
    # "unterbrochen", and is now a TYPED turn-lifecycle item
    # ({"kind":"turn","event":"canceled"}, claude_sessions.py:701-702) so the app
    # can style it as lifecycle rather than as prose. Nothing caught the drift
    # because no gate ran this file and it was already dying earlier on an
    # AttributeError. Both are fixed; this now pins the CURRENT contract.
    marks = [st for st in steps
             if st.get("kind") == "turn" and st.get("event") == "canceled"]
    prose = [st for st in steps if st.get("kind") == "text"
             and "[Request interrupted" in st.get("text", "")]
    check("rendered as one typed turn-canceled item", len(marks) == 1)
    check("not rendered as an owner prose bubble", not prose)
    check("and the owner's real message is still there",
          any(st.get("kind") == "text" and st.get("text") == "mach was" for st in steps))
finally:
    claude_sessions.PROJECTS = _projects

print()
if FAILS:
    print("FAILED: %d check(s): %s" % (len(FAILS), "; ".join(FAILS)))
    sys.exit(1)
print("ALL P1 RUNTIME CHECKS PASSED")
