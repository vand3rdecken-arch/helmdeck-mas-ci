# -*- coding: utf-8 -*-
"""Session rotation (owner 2026-10-15). Henry's board session was ONE transcript
for 61 days: 374 MB after 228 in-place compactions, and everything touching it
paid for the size (the old prune loaded it whole: +614 MB peak, eight times a
day, 10 KB saved). Pinned, each against the real function:

  1. claude_sessions.last_compact_summary reads the NEWEST compaction summary
     from the TAIL of a transcript - never the whole file;
  2. _rotate_if_big: under the mark nothing happens; over it the pointer is
     dropped, the old id heads session_chain, the snapshot memory is cleared;
     a pointer that moved under us is left alone;
  3. _maybe_compact end to end: a PROVEN compaction of a big session rotates, a
     proven one of a small session does not, an UNPROVEN one never rotates;
  4. _rotation_report: the first turn of a fresh BOARD session carries the old
     session's summary as harness text; a live session, a card chat and an
     empty chain get nothing; an oversize summary is clipped.

Run: py -3.12 ops/tests/test_session_rotate.py
"""
import json
import os
import subprocess as _sp
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

tmp = tempfile.mkdtemp(prefix="session_rotate_")
from spine.storage import db
db.DBPATH = os.path.join(tmp, "test.db")          # never the live db
db.init()
from spine.agent import claude_sessions
from cells.copilot.chat import copilot as c

PROJ = os.path.join(tmp, "projects")
os.makedirs(os.path.join(PROJ, "p"))
claude_sessions.PROJECTS = PROJ

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def transcript(sid, pad_kb, summary=None, early_summary=None):
    """A session file: an old summary near the head, filler, the newest summary
    near the tail (the shape a fresh compaction leaves)."""
    path = os.path.join(PROJ, "p", sid + ".jsonl")

    def rec(text, flag):
        d = {"type": "user", "message": {"role": "user", "content": text}}
        if flag:
            d["isCompactSummary"] = True
        return json.dumps(d)
    with open(path, "w", encoding="utf-8") as f:
        if early_summary:
            f.write(rec(early_summary, True) + "\n")
        for i in range(pad_kb):
            f.write(rec("filler %d " % i + "x" * 1000, False) + "\n")
        if summary:
            f.write(rec(summary, True) + "\n")
            f.write(rec("one more turn after the compaction", False) + "\n")
    return path


class _FakeStdout:
    def __init__(self, lines):
        self._lines = lines

    def __iter__(self):
        return iter(self._lines)


class _FakePopen:
    def __init__(self, lines):
        self.stdin = self
        self.stdout = _FakeStdout(lines)

    def write(self, _):
        pass

    def close(self):
        pass

    def wait(self, timeout=None):
        pass


def _lines(new_sid, after_ctx):
    return [json.dumps({"type": "system", "session_id": new_sid, "subtype": "init"}),
            json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": after_ctx}}}),
            json.dumps({"type": "result", "session_id": new_sid,
                        "usage": {"input_tokens": after_ctx},
                        "modelUsage": {"claude-sonnet-5": {}}, "total_cost_usd": 0.01})]


# ---- 1. the summary, from the tail --------------------------------------------
transcript("s-sum", 40, summary="NEW SUMMARY: ziel X", early_summary="OLD SUMMARY: ziel W")
check(claude_sessions.last_compact_summary("s-sum") == "NEW SUMMARY: ziel X", "the NEWEST summary wins over an older one")
size = os.path.getsize(os.path.join(PROJ, "p", "s-sum.jsonl"))
check(claude_sessions.last_compact_summary("s-sum", max_bytes=2000) == "NEW SUMMARY: ziel X",
      "...found by reading only the last 2 KB of a %d KB file" % (size // 1024))
transcript("s-old-only", 40, early_summary="OLD ONLY")
check(claude_sessions.last_compact_summary("s-old-only", max_bytes=2000) == "",
      "a summary outside the tail window is NOT found (the file is never read whole)")
transcript("s-none", 5)
check(claude_sessions.last_compact_summary("s-none") == "", "no summary in the transcript -> empty")
check(claude_sessions.last_compact_summary("no-such-session") == "", "unknown session -> empty")
p = os.path.join(PROJ, "p", "s-blocks.jsonl")
with open(p, "w", encoding="utf-8") as f:
    f.write(json.dumps({"isCompactSummary": True, "message": {"role": "user", "content": [
        {"type": "text", "text": "block one"}, {"type": "tool_result", "x": 1}, {"type": "text", "text": "block two"}]}}) + "\n")
check(claude_sessions.last_compact_summary("s-blocks") == "block one\nblock two", "list-of-blocks content is joined")

# ---- 2. _rotate_if_big -----------------------------------------------------------
c.SESSION_ROTATE_BYTES = 30_000
transcript("s-small", 5, summary="S")
transcript("s-big", 60, summary="BIG SUMMARY")
c._save_stats({"owner": {"ctx_tokens": 1000, "session_chain": ["s-ancient"]}})
c._save_sessions({"owner": "s-small"})
c._snap_seen["owner"] = ("h", 0.0)
check(c._rotate_if_big("owner", "owner", "s-small") is False and c._sessions().get("owner") == "s-small",
      "under the mark: nothing happens, the pointer stays")
c._save_sessions({"owner": "s-big"})
check(c._rotate_if_big("owner", "owner", "s-big") is True, "over the mark: rotated")
check("owner" not in c._sessions(), "...the pointer is gone, so the next turn spawns FRESH")
check(c._stats()["owner"]["session_chain"] == ["s-ancient", "s-big"], "...the old session heads the chain, nothing dropped")
check("owner" not in c._snap_seen, "...the snapshot memory is cleared: the fresh session has seen no board")
c._save_sessions({"owner": "s-moved"})
check(c._rotate_if_big("owner", "owner", "s-big") is False and c._sessions().get("owner") == "s-moved",
      "a pointer that moved under us is left alone")
c._save_stats({"owner": {"session_chain": ["s%d" % i for i in range(6)]}})
c._save_sessions({"owner": "s-big"})
c._rotate_if_big("owner", "owner", "s-big")
chain = c._stats()["owner"]["session_chain"]
check(len(chain) == 6 and chain[-1] == "s-big" and chain[0] == "s1", "the chain stays bounded at 6")

# ---- 3. end to end through _maybe_compact ---------------------------------------------
_orig = _sp.Popen
for name, sid, after, expect_rotate in (("proven + big", "s-big", 20000, True),
                                         ("proven + small", "s-small", 20000, False),
                                         ("UNPROVEN + big", "s-big", 175000, False)):
    c._compact_strikes.clear()
    c._save_sessions({"owner": sid})
    c._save_stats({"owner": {"ctx_tokens": 180000, "turns": 3, "cost": 0.0, "session_chain": []}})
    _sp.Popen = lambda *a, _s=sid, _a=after, **k: _FakePopen(_lines(_s, _a))
    c._maybe_compact("owner")
    rotated = "owner" not in c._sessions()
    check(rotated == expect_rotate,
          "_maybe_compact %s -> %s" % (name, "rotates" if expect_rotate else "keeps the session"))
    if expect_rotate:
        check(c._stats()["owner"]["session_chain"][-1:] == [sid], "...and chains it")
_sp.Popen = _orig

# ---- 4. the first turn of the fresh session -------------------------------------------
c._save_stats({"owner": {"session_chain": ["s-big"]}})
r = c._rotation_report("owner", "owner", None)
check(r.startswith("<harness-report>") and "BIG SUMMARY" in r and "SITZUNGSWECHSEL" in r and r.endswith("</harness-report>\n\n"),
      "a fresh board session gets the old summary as harness text")
check("MASCHINENTEXT" in r, "...labelled so it cannot read as the owner speaking")
check(c._rotation_report("owner", "owner", "live-session") == "", "a LIVE session gets no seed")
check(c._rotation_report("owner", "owner:card-1", None) == "", "a card chat gets no seed")
c._save_stats({"owner": {"session_chain": []}})
check(c._rotation_report("owner", "owner", None) == "", "no chain -> nothing to carry")
c._save_stats({"owner": {"session_chain": ["s-none"]}})
check(c._rotation_report("owner", "owner", None) == "", "a predecessor without a summary -> nothing to carry")
transcript("s-huge", 5, summary="H" * (c.SEED_MAX_CHARS + 5000))
c._save_stats({"owner": {"session_chain": ["s-huge"]}})
r = c._rotation_report("owner", "owner", None)
check("gekuerzt" in r and len(r) < c.SEED_MAX_CHARS + 1200, "an oversize summary is clipped (%d chars)" % len(r))

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("session-rotate: all pinned - PASS")
