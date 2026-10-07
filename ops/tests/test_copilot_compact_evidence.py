# -*- coding: utf-8 -*-
"""copilot._maybe_compact - WHAT COUNTS AS PROOF THAT A COMPACTION RAN, and the
fact that one unproven attempt must not switch compaction off for the daemon's
whole life.

THE INCIDENT (2026-10-06/07, owner board session b085da2d). The daemon came up
at 13:18:22. At 13:26:08 it compacted the owner's session - the summary is in
the transcript, timestamped 11:26:05.846Z. It then never compacted again: 23
hours, 72 board turns, context at 953,876 of 1,000,000, ~1.4M input tokens per
chat turn and ~2.2M per judge turn, roughly 85% of the day's whole spend.

The cause was the shrink check reading a number that cannot exist. drivers.py
documents the measured frame sequence of a `/compact` turn - status{compacting}
-> status{null} -> init -> compact_boundary{pre_tokens, post_tokens,
duration_ms} -> user(summary) -> result "" with ZERO usage. So a /compact turn
carries NO assistant call and no usage; copilot's `after = <usage> or ctx` then
fell back to the PRE-compaction figure, `after <= ctx * 0.75` read False, and
the module-global `_autocompact_supported` latched False for the process.
sessions._maybe_compact had been fixed for exactly this (compact_boundary
first, transcript marks as fallback); this copy had not, and drifted.

Pinned here, all four of which FAIL on the pre-fix code:
  - a boundary frame with no usage anywhere -> compaction is PROVEN, ctx_tokens
    takes the CLI's own post_tokens, a note goes to the chat
  - no boundary frame and no usage, but a new compaction summary in the
    transcript -> still proven (the post-mortem fallback)
  - a genuinely unproven attempt disables NOTHING permanently: once the backoff
    has passed the next crossing probes again, per session, not per process
  - judge() (the broker's escalation turn, which runs on the SAME board
    session) schedules compaction like a chat turn does
"""
import json, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

tmp = tempfile.mkdtemp(prefix="copilot_compact_ev_")
# chat, stats and session pointers are db rows (state-into-db phases D/E):
# sandbox the store BEFORE the first conn() - db.py refuses the live db from a
# test, but only if we never ask for it.
from spine.storage import db
db.DBPATH = os.path.join(tmp, "test.db")
db.init()

from cells.copilot.chat import copilot as c
from cells.engineer.cards import sessions

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class _FakeStdout:
    def __init__(self, lines):
        self._lines = lines

    def __iter__(self):
        return iter(self._lines)


class _FakePopen:
    """Stands in for subprocess.Popen - stdin is a sink, stdout replays canned
    stream-json lines in the real CLI's line shape."""
    def __init__(self, lines):
        self.stdin = self
        self.stdout = _FakeStdout(lines)

    def write(self, _):
        pass

    def close(self):
        pass

    def wait(self, timeout=None):
        pass


def _compact_turn(sid, post_tokens=None, boundary=True):
    """The measured frame sequence of a real `/compact` turn: a boundary frame
    carrying the post-compaction size, a summary the stream does not repeat,
    and a result with ZERO usage and no assistant message at all."""
    out = [json.dumps({"type": "system", "subtype": "init", "session_id": sid})]
    if boundary:
        md = {"trigger": "manual", "duration_ms": 41000}
        if post_tokens is not None:
            md["post_tokens"] = post_tokens
            md["pre_tokens"] = 180000
        out.append(json.dumps({"type": "system", "subtype": "compact_boundary",
                               "session_id": sid, "compact_metadata": md}))
    out.append(json.dumps({"type": "result", "session_id": sid, "result": "",
                           "usage": {"input_tokens": 0, "output_tokens": 0,
                                     "cache_read_input_tokens": 0},
                           "modelUsage": {"claude-sonnet-5": {}},
                           "total_cost_usd": 0.0}))
    return out


import subprocess as _sp
_orig_popen = _sp.Popen
_orig_marks = sessions._compact_marks
# no real transcripts in a sandbox: marks come from this dial unless a case
# overrides it
MARKS = [0]
sessions._compact_marks = lambda sid: MARKS[0]


def _strikes(user):
    """How many unproven attempts this session has on record, or None if this
    build has no per-session strike register at all. Deliberately tolerant of
    the PRE-FIX module (which had a single `_autocompact_supported` global
    instead): the point of this file is that the old code fails these checks on
    BEHAVIOUR - a compaction it cannot see and never retries - not merely on a
    missing attribute."""
    reg = getattr(c, "_compact_strikes", None)
    if reg is None:
        return None
    return (reg.get(user) or (0, 0))[0]


def _reset(ctx=180000, turns=5):
    if getattr(c, "_compact_strikes", None) is not None:
        c._compact_strikes.clear()
    if hasattr(c, "_autocompact_supported"):
        c._autocompact_supported = None       # pre-fix build: start unprobed
    c._save_sessions({"owner": "sess-a"})
    c._save_stats({"owner": {"ctx_tokens": ctx, "ctx_window": 200000,
                             "turns": turns, "cost": 0.0}})


# 1) THE INCIDENT ITSELF: a compaction whose only evidence is the boundary frame.
#    Pre-fix this returned None and latched the process global False.
_reset()
MARKS[0] = 0
_sp.Popen = lambda *a, **k: _FakePopen(_compact_turn("sess-a", post_tokens=62000))
note = c._maybe_compact("owner")
_sp.Popen = _orig_popen
check(note is not None and "AUTO-COMPACT" in note,
      "boundary frame + zero usage -> compaction PROVEN, note returned")
check((c._stats()["owner"] or {}).get("ctx_tokens") == 62000,
      "ctx_tokens takes the CLI's own post_tokens (62k), not the stale 180k")
check(_strikes("owner") in (0, None), "a proven compaction leaves no strike")

# 2) the boundary frame arrived but carries no figure: still proven, and the
#    meter is left to its one owner (_fold_stats) rather than written wrong.
_reset()
MARKS[0] = 0
_sp.Popen = lambda *a, **k: _FakePopen(_compact_turn("sess-a"))
note = c._maybe_compact("owner")
_sp.Popen = _orig_popen
check(note is not None and "naechsten Turn" in note,
      "boundary without post_tokens -> proven, note says the meter lags")
check((c._stats()["owner"] or {}).get("ctx_tokens") == 180000,
      "no reading -> ctx_tokens untouched (never set to a guessed number)")

# 3) POST-MORTEM FALLBACK: no frames at all (process died before they arrived),
#    but the CLI did write a compaction summary into the transcript.
_reset()
MARKS[0] = 12
_sp.Popen = lambda *a, **k: _FakePopen(_compact_turn("sess-a", boundary=False))


_reads = {"n": 0}


def _marks_grow(sid):
    """First read is the baseline taken before the run; by the second one the
    CLI has appended its summary, exactly as the real transcript does."""
    _reads["n"] += 1
    return 12 if _reads["n"] == 1 else 13


sessions._compact_marks = _marks_grow
note = c._maybe_compact("owner")
sessions._compact_marks = lambda sid: MARKS[0]
_sp.Popen = _orig_popen
check(note is not None, "a new compaction summary in the transcript also proves it")

# 4) NOTHING PROVEN -> A BACKOFF, NOT A SWITCH. This is the half that cost 23
#    hours: the old flag was process-global and never re-probed.
_reset()
MARKS[0] = 5
_sp.Popen = lambda *a, **k: _FakePopen(_compact_turn("sess-a", boundary=False))
note = c._maybe_compact("owner")
check(note is None, "unproven attempt stays silent in the chat")
check(_strikes("owner") == 1, "...and records ONE strike")

spawns = {"n": 0}


def _count(*a, **k):
    spawns["n"] += 1
    return _FakePopen(_compact_turn("sess-a", post_tokens=60000))


_sp.Popen = _count
c._save_stats({"owner": {"ctx_tokens": 190000, "ctx_window": 200000,
                         "turns": 6, "cost": 0.0}})
c._maybe_compact("owner")
check(spawns["n"] == 0, "inside the backoff the next crossing costs nothing")

# THE BACKOFF EXPIRES - this is the whole point, and the half that cost 23
# hours. Let the clock run out (the pre-fix global has no clock to run out, so
# it simply never spawns again and this check is where it fails).
if getattr(c, "_compact_strikes", None) is not None:
    c._compact_strikes["owner"] = (1, time.time() - 1)
c._save_stats({"owner": {"ctx_tokens": 190000, "ctx_window": 200000,
                         "turns": 7, "cost": 0.0}})
note = c._maybe_compact("owner")
_sp.Popen = _orig_popen
# >0, not ==1: one _maybe_compact spawns the memory-save turn AND the /compact
# turn. What matters is that it spawned at all, having spawned nothing before.
check(spawns["n"] > 0, "once the backoff passed, compaction is RETRIED")
check(note is not None and "AUTO-COMPACT" in note, "...and the retry compacts for real")
check(_strikes("owner") in (0, None), "a proven retry clears the strikes")

# the verdict is PER SESSION, never one flag for the process
if getattr(c, "_compact_strikes", None) is not None:
    c._compact_strikes.clear()
    c._compact_verdict("owner", False)
    check(not c._compact_allowed("owner") and c._compact_allowed("owner\x00card:x"),
          "a strike on the board session leaves other sessions alone")
else:
    check(False, "a strike on the board session leaves other sessions alone "
                 "(this build has no per-session verdict at all)")

# 5) THE JUDGE PATH. An escalation turn resumes the SAME board session, so it
#    owes that session the same maintenance a chat turn does. Pre-fix only
#    chat() ever scheduled a compaction.
sched = {"n": 0}
_orig_sched, _orig_owner = c._schedule_compact, c.owner_name
c._schedule_compact = lambda u: sched.__setitem__("n", sched["n"] + 1)
c.owner_name = lambda: "owner"
c._save_sessions({"owner": "sess-a"})


class _FakeJudge:
    def __init__(self):
        self.stdin = None

    def communicate(self, input=None, timeout=None):
        return (json.dumps({"session_id": "sess-a", "result": "{}",
                            "usage": {"input_tokens": 10},
                            "modelUsage": {"claude-sonnet-5": {}},
                            "total_cost_usd": 0.01}), "")

    def kill(self):
        pass


_sp.Popen = lambda *a, **k: _FakeJudge()
c._last_turn_at.pop("owner", None)
raw = c.judge("prompt", os.getcwd())
_sp.Popen = _orig_popen
check(raw.get("session_id") == "sess-a", "judge still returns the raw verdict")
check(sched["n"] == 1, "a judge turn SCHEDULES compaction on the board session")
check(c._last_turn_at.get("owner", 0) > 0,
      "...and stamps the turn clock, so the lull is measured off it")
c._schedule_compact, c.owner_name = _orig_sched, _orig_owner
sessions._compact_marks = _orig_marks

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("copilot-compact-evidence: all pinned - PASS")
