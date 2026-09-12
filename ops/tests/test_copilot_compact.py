# -*- coding: utf-8 -*-
"""copilot._maybe_compact - the board chat's counterpart of sessions._maybe_compact
(card parity, re-enabled 2026-08-14 alongside the card version). Before this,
the board/PM chat had a context meter but NO compaction and NO rotation safety
net at all - worse off than cards ever were, since even the pre-fix card bug
("silent resume-detach loses the chat") had nothing catching it here. Pinned:
  - below the high-water mark / no session -> no-op, no subprocess spawned
  - a real compaction (context shrinks >=25%) updates ctx_tokens, bills the
    compact turn's cost WITHOUT incrementing the turn counter, and returns a
    note for the chat log
  - a CLI that doesn't honor /compact is learned once (no per-turn spawn after)
  - a session rotation during compaction chains the old id, never drops it"""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from cells.copilot.chat import copilot as c

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


tmp = tempfile.mkdtemp(prefix="copilot_compact_")
# chat, stats and session pointers are db rows (state-into-db phases D/E):
# sandbox the store
from spine.storage import db
db.DBPATH = os.path.join(tmp, "test.db")
db.init()


class _FakeStdout:
    def __init__(self, lines):
        self._lines = lines

    def __iter__(self):
        return iter(self._lines)


class _FakePopen:
    """Stands in for subprocess.Popen(...) - stdin is a no-op sink, stdout
    replays canned stream-json lines, matching the real CLI's line shape."""
    def __init__(self, lines):
        self.stdin = self
        self.stdout = _FakeStdout(lines)

    def write(self, _):
        pass

    def close(self):
        pass

    def wait(self, timeout=None):
        pass


def _lines(new_sid, after_ctx, cost=0.02, honored=True):
    out = [json.dumps({"type": "system", "session_id": new_sid, "subtype": "init"})]
    if honored:
        out.append(json.dumps({"type": "assistant",
                                "message": {"usage": {"input_tokens": after_ctx}}}))
    out.append(json.dumps({"type": "result", "session_id": new_sid,
                           "usage": {"input_tokens": after_ctx if honored else 0},
                           "modelUsage": {"claude-sonnet-5": {}}, "total_cost_usd": cost}))
    return out


# 1) below threshold -> no-op, nothing spawned
c._autocompact_supported = None
spawned = {"n": 0}
import subprocess as _sp
_orig_popen = _sp.Popen
_sp.Popen = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not spawn"))
c._save_sessions({"owner": "sess-a"})
c._save_stats({"owner": {"ctx_tokens": 50000}})
note = c._maybe_compact("owner")
check(note is None, "below high-water mark: no-op")
_sp.Popen = _orig_popen

# 2) no session id -> no-op
c._autocompact_supported = None
c._save_sessions({})
c._save_stats({"owner": {"ctx_tokens": 180000}})
note = c._maybe_compact("owner")
check(note is None, "no session id: no-op")

# 3) real compaction: context shrinks, note returned, turns NOT incremented
c._autocompact_supported = None
c._save_sessions({"owner": "sess-a"})
c._save_stats({"owner": {"ctx_tokens": 180000, "turns": 5, "cost": 1.0}})
_sp.Popen = lambda *a, **k: _FakePopen(_lines("sess-a", 30000, cost=0.03))
note = c._maybe_compact("owner")
check(note is not None and "AUTO-COMPACT" in note, "real shrink -> note returned")
st = c._stats()["owner"]
check(st["ctx_tokens"] == 30000, "ctx_tokens updated to the post-compact reading")
check(st["turns"] == 5, "turn counter NOT incremented by the compact call (card parity)")
check(round(st["cost"], 2) == 1.03, "compact turn's cost still billed")
check(c._autocompact_supported is True, "support learned True")
_sp.Popen = _orig_popen

# 4) CLI doesn't honor /compact: context doesn't shrink -> learned False, silent
c._autocompact_supported = None
c._save_sessions({"owner": "sess-b"})
c._save_stats({"owner": {"ctx_tokens": 180000, "turns": 1, "cost": 0.0}})
_sp.Popen = lambda *a, **k: _FakePopen(_lines("sess-b", 175000, cost=0.01))
note = c._maybe_compact("owner")
check(note is None, "unhonored /compact: no note (no per-turn chat pollution)")
check(c._autocompact_supported is False, "support learned False")
spawn_count = {"n": 0}
def _count_spawn(*a, **k):
    spawn_count["n"] += 1
    return _FakePopen(_lines("sess-b", 175000))
_sp.Popen = _count_spawn
c._save_stats({"owner": {"ctx_tokens": 190000, "turns": 1, "cost": 0.0}})
c._maybe_compact("owner")
check(spawn_count["n"] == 0, "learned-unsupported CLI costs nothing on the next call")
_sp.Popen = _orig_popen

# 5) compaction rotates the session id -> old id chained, pointer follows new
c._autocompact_supported = None
c._save_sessions({"owner": "sess-old"})
c._save_stats({"owner": {"ctx_tokens": 180000, "turns": 2, "cost": 0.0}})
_sp.Popen = lambda *a, **k: _FakePopen(_lines("sess-new", 20000))
c._maybe_compact("owner")
check(c._sessions()["owner"] == "sess-new", "pointer follows the rotated session")
check("sess-old" in (c._stats()["owner"].get("session_chain") or []),
      "old session kept in the chain, not dropped")
_sp.Popen = _orig_popen

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("copilot-compact: all pinned - PASS")
