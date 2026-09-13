# -*- coding: utf-8 -*-
"""A /compact turn ends when the CLI says so - not when a watchdog gives up.

Regression for card 20260913-215533 (2026-09-13 22:55-23:07, actions seq
8449-8453): the owner typed /compact on a 193k session. The CLI resumed the
session fresh, compacted it in 244s (its own compact_metadata.duration_ms),
wrote the summary at 22:59:19 - and the harness sat on the open process until
the owner's waiting steer cut it at 23:07:30 with "Verdichtung haengt". Eight
minutes of waiting on a compaction that was already done, then a false
"interrupted, will retry" verdict on top.

Why: measured against the real CLI (stream-json in/out, probe in the fix
commit), `/compact` ends with the frame sequence
    system/status {compacting} -> system/status {null} -> system/init
    -> system/compact_boundary {compact_metadata: pre/post_tokens, duration_ms}
    -> user (summary) -> result {result: "", usage: all zeros}
and that terminal result - empty text, zero usage - is EXACTLY the shape the
driver's null-result guard drops as a "dead leftover" on the first turn after
a --resume spawn. So the pump never released the waiter.

Paseo (packages/server/src/server/agent/providers/claude/agent.ts) keys on
the same frames: `status: compacting` sets this.compacting, `compact_boundary`
is the completed compaction item + buildCompactionUsageEvent(postTokens).
Pinned here, on the REAL dispatch path (drivers._on_event, econ._record_econ,
sessions._maybe_compact):
  - the compaction's terminal result frame completes the turn on a resumed
    first turn (the null-result guard yields to the boundary evidence)
  - meta carries the boundary facts; the context meter resets to post_tokens
  - _maybe_compact takes the boundary as proof: no re-queue, no "haengt",
    even when a steerer had flagged the turn as cut
  - a genuinely dead resume (empty result, NO boundary) is still dropped
"""
import os, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


# --- the measured frame sequence (probe 2026-09-13 23:22, haiku, 4 turns) ----
BOUNDARY = {"type": "system", "subtype": "compact_boundary", "session_id": "sess-live",
            "compact_metadata": {"trigger": "manual", "pre_tokens": 29313,
                                 "post_tokens": 2171, "cumulative_dropped_tokens": 27142,
                                 "duration_ms": 17785}}
NULL_RESULT = {"type": "result", "subtype": "success", "is_error": False, "result": "",
               "usage": {"input_tokens": 0, "cache_creation_input_tokens": 0,
                         "cache_read_input_tokens": 0, "output_tokens": 0}}


def frames():
    return [{"type": "system", "subtype": "status", "status": "compacting"},
            {"type": "system", "subtype": "status", "status": None},
            {"type": "system", "subtype": "init", "session_id": "sess-live"},
            BOUNDARY,
            {"type": "user", "message": {"role": "user", "content": "summary"}},
            NULL_RESULT]


# --- 1. driver: the pump completes the turn off the boundary + result --------
from spine.agent import drivers                      # noqa: E402
from spine.agent import timeline_store               # noqa: E402
_ClaudeSession = drivers._ClaudeSession

drivers._record_pid = lambda pid, spawn_time=None: None
drivers._forget_pid = lambda pid: None
appended = []
timeline_store.append = lambda run_dir, sid, step: appended.append(step)


def make_session():
    real_spawn = _ClaudeSession._spawn
    _ClaudeSession._spawn = lambda self: None
    try:
        s = _ClaudeSession({}, {"id": "t1", "worktree": ".", "session_id": "sess-live"})
    finally:
        _ClaudeSession._spawn = real_spawn
    s.brief = ""
    s._alive = True
    # the card's shape: /compact was the FIRST turn after a --resume spawn
    s._spawn_resumed = "sess-live"
    s._first_turn_after_spawn = True
    return s


def new_cur():
    return {"parts": [], "result": None, "session_id": "sess-live",
            "done": threading.Event(), "live_key": "k", "last_flush": 0.0,
            "last_event": time.time()}


print("driver - compaction frames on a resumed first turn:")
s = make_session()
cur = new_cur(); s._cur = cur
for ev in frames():
    s._on_event(ev)
check(cur["done"].is_set(), "terminal (empty, zero-usage) result COMPLETES the compact turn")
check(cur.get("compaction", {}).get("post_tokens") == 2171,
      "compact_boundary folded at event time (post_tokens)")
check(cur.get("compaction", {}).get("pre_tokens") == 29313, "pre_tokens folded")
check(cur.get("compaction", {}).get("duration_ms") == 17785, "duration_ms folded")
check(cur.get("compaction", {}).get("trigger") == "manual", "trigger folded")
check(cur.get("compacting") is False, "compacting cleared by the boundary")
check(not cur.get("null_results"), "the frame was NOT counted as a null result")
check(any(st.get("kind") == "compaction" and st.get("event") == "completed" for st in appended),
      "feed gets a compaction/completed step (Paseo timeline item)")

print("driver - the null-result guard still holds without a boundary:")
s = make_session()
cur = new_cur(); s._cur = cur
s._on_event({"type": "system", "subtype": "init", "session_id": "sess-live"})
s._on_event(dict(NULL_RESULT))
check(not cur["done"].is_set(), "empty zero-usage result with NO boundary is still dropped")
check(cur.get("null_results") == 1, "...and counted as a null result")

print("driver - camelCase spelling (transcript record shape) is read too:")
cm = drivers._compact_metadata({"compactMetadata": {"trigger": "auto", "preTokens": 10,
                                                    "postTokens": 3, "durationMs": 7}})
check(cm == {"trigger": "auto", "pre_tokens": 10, "post_tokens": 3, "duration_ms": 7},
      "compactMetadata/preTokens/postTokens/durationMs normalised")

# --- 2. econ: the meter resets to post_tokens --------------------------------
from spine.storage import events                     # noqa: E402
events.emit = lambda *a, **k: None                   # never the live db from a test
events.price_turn = lambda *a, **k: 0.0
from spine.turn import econ                          # noqa: E402

print("econ - context meter after a compaction:")
t = {"id": "t1", "ctx_tokens": 193189, "ctx_window": 200000}
econ._record_econ(t, {"usage": {}, "models": [], "ctx_usage": {},
                      "compaction": {"trigger": "manual", "pre_tokens": 197408,
                                     "post_tokens": 14000, "duration_ms": 244111}})
check(t["ctx_tokens"] == 14000, "ctx_tokens = post_tokens (no assistant call to read)")
t = {"id": "t1", "ctx_tokens": 193189, "ctx_window": 200000}
econ._record_econ(t, {"usage": {}, "models": [], "ctx_usage": {}})
check(t["ctx_tokens"] == 193189, "no compaction, no reading -> meter untouched")

# --- 3. _maybe_compact: the boundary is the verdict -------------------------
from cells.engineer.cards import sessions as S       # noqa: E402


class _Log:
    def __init__(self):
        self.notes = []

    def log(self, kind, detail, **kw):
        self.notes.append("%s:%s" % (kind, detail))

    def saw(self, frag):
        return any(frag in n for n in self.notes)


CARD = {}


def _fake_mutate(tid, fn):
    fn(CARD)
    return dict(CARD)


S._mutate = _fake_mutate
S._compact_marks = lambda sid: 0                     # transcript says nothing - stream must
S._record_econ = econ._record_econ                   # the real fold


def _track():
    CARD.clear()
    CARD.update({"id": "t1", "run_dir": ".", "ctx_tokens": 193189,
                 "ctx_window": 200000, "session_id": "sess-live"})
    return dict(CARD)


def _turn_with_boundary(t, prompt, **kw):
    # the driver returns the CLI's empty terminal result plus the folded facts
    return "sess-live", "", {"usage": {}, "models": [], "ctx_usage": {},
                             "compaction": {"trigger": "manual", "pre_tokens": 197408,
                                            "post_tokens": 14000, "duration_ms": 244111}}


print("_maybe_compact - boundary evidence:")
S._autocompact_supported = None
S._turn = _turn_with_boundary
t = _track()
lg = _Log()
S._maybe_compact(t, lg)
check(S._autocompact_supported is True, "boundary teaches True")
check(not CARD.get("compact_pending"), "no re-queue")
check(CARD.get("ctx_tokens") == 14000, "card meter reset to post_tokens")
check(lg.saw("AUTO-COMPACT ok"), "log says ok")
check(not lg.saw("unterbrochen") and not lg.saw("nachgeholt"), "no 'interrupted / retry' verdict")

print("_maybe_compact - boundary wins over a steerer's cut flag (the 23:07 case):")
S._autocompact_supported = None
t = _track()
S._compact_interrupted.add("t1")                     # await_compaction gave up on it
lg = _Log()
S._maybe_compact(t, lg)
check(S._autocompact_supported is True, "still learns True")
check(not CARD.get("compact_pending"), "still no re-queue - the work is done")
check("t1" not in S._compact_interrupted, "cut flag consumed")

print()
if _fails:
    print("FAILED: %d" % len(_fails))
    sys.exit(1)
print("all ok")
