# -*- coding: utf-8 -*-
"""The board chat's PM-session economics (card parity) must stay truthful:
copilot._fold_stats is the ONE owner of copilot_stats.json, folded at event
time from the runtime's own result + assistant events. Pinned here:
  - the context meter reads the LAST assistant call's usage (input+cache =
    real window fill), NEVER the result event's summed usage (a long
    multi-call turn would read as millions of "context" tokens);
  - a missing ctx reading means NO update, never a wrong one;
  - cost/turns/tokens ACCUMULATE across turns, ctx is REPLACED;
  - the window is derived from model evidence ("[1m]" -> 1M) with the
    successful call's context as a lower bound, not hardcoded;
  - /chat/history serves the stats (plan_pct None when not calibratable).
Load-bearing: chat.tsx renders the meter + usage line straight off this."""
import os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from cells.copilot import copilot as c
from cells.copilot import copilot_stats

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


tmp = tempfile.mkdtemp(prefix="copilot_stats_")
copilot_stats.STATS = os.path.join(tmp, "copilot_stats.json")
c.SESS = os.path.join(tmp, "copilot_sessions.json")
c.CHATLOG = os.path.join(tmp, "copilot_log.json")

# 1) first turn: summed result usage feeds the cumulative counters, the LAST
#    assistant call's usage feeds the meter - they differ on purpose.
result = {"usage": {"input_tokens": 900000, "cache_read_input_tokens": 100000,
                    "cache_creation_input_tokens": 0, "output_tokens": 8000},
          "modelUsage": {"claude-opus-4-8": {}}, "total_cost_usd": 0.25}
m = c._fold_stats("owner", result, {"input_tokens": 4000, "cache_read_input_tokens": 56000,
                                    "cache_creation_input_tokens": 2000, "output_tokens": 900})
check(m["turns"] == 1 and m["cost"] == 0.25, "turn 1: turns/cost folded")
check(m["tokens_in"] == 1000000 and m["tokens_out"] == 8000, "turn 1: cumulative tokens from result usage")
check(m["ctx_tokens"] == 62000, "meter reads the LAST call's usage (62k), not the summed 1M")
check(m["ctx_window"] == 200000, "no [1m] evidence -> 200k window")

# 2) second turn accumulates spend, REPLACES ctx; empty ctx reading = no update
m = c._fold_stats("owner", {"usage": {"input_tokens": 50000, "output_tokens": 2000},
                            "modelUsage": {"claude-opus-4-8": {}}, "total_cost_usd": 0.05}, {})
check(m["turns"] == 2 and m["cost"] == 0.30, "turn 2: cost accumulates")
check(m["ctx_tokens"] == 62000, "missing ctx reading -> meter unchanged, never wrong")
m = c._fold_stats("owner", {"usage": {}, "modelUsage": {}, "total_cost_usd": 0.0},
                  {"input_tokens": 3000, "cache_read_input_tokens": 70000})
check(m["ctx_tokens"] == 73000, "fresh ctx reading REPLACES (not sums) the fill")

# 3) window from model evidence: a [1m] model widens to 1M and never shrinks
m = c._fold_stats("owner", {"usage": {}, "modelUsage": {"claude-sonnet-5[1m]": {}},
                            "total_cost_usd": 0.0}, {})
check(m["ctx_window"] == 1000000, "[1m] model id -> 1M window")

# 4) a successful call BEYOND the standard window proves the 1M tier - the old
#    bare lower-bound (window == ctx) pinned the meter at a permanent red 100%
#    (seen live 2026-08-14: 478k of "478k" while the CLI sat at ~48% of its
#    real 1M window and rightly refused to compact).
m2 = c._fold_stats("other", {"usage": {}, "modelUsage": {}, "total_cost_usd": 0.0},
                   {"input_tokens": 260000})
check(m2["ctx_window"] == 1000000, "proof beyond 200k -> 1M-tier window, not a pinned 100%")

# 5) history() serves the stats; plan_pct is None when not calibratable
copilot_stats._calib.update({"t": time.time(), "flat": False, "v": None})
h = c.history("owner")
st = h.get("stats") or {}
check(st.get("turns") == 4 and st.get("ctx_tokens") == 73000, "history exposes the folded stats")
check(st.get("plan_pct") is None, "not calibratable -> plan_pct None (UI falls back to tokens)")

# 6) calibrated flat plan: cost basis wins (cache reads must not over-weight)
copilot_stats._calib.update({"t": time.time(), "flat": True, "v": {"cost_per_pct": 0.5, "tokens_per_pct": 1e6}})
st2 = (c.history("owner").get("stats") or {})
check(st2.get("plan_pct") == round(st2["cost"] / 0.5, 4), "flat plan: plan share = cost / cost_per_pct")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("copilot-stats: all pinned - PASS")
