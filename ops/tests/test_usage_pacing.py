# -*- coding: utf-8 -*-
"""Headless unit test: spine.ops.usage.pacing()'s reset_risk field.

pm.py's consumers (test_notice_routing.py) mock usage.weekly_pacing_flag()/
snapshot() wholesale - they prove pm.py READS reset_risk correctly, never
that pacing() COMPUTES it correctly. This tests the real math, pure
(used_pct, resets_at, now) in, dict out - no daemon, no network, no disk.

Two false-positive shapes were measured live and both are pinned here as
regressions, not just examples:

  1. 2026-09-13, 86% used with 2.8h left to a reset, projection UNDER 100% -
     `flag` fires (usedPct >= 85 alone), reset_risk must not.
  2. 2026-09-14 07:58, 6% into a FRESH window (reset 12h earlier), projection
     100.7% on pure noise - exhaust_before_reset fires (it has no buffer),
     reset_risk must not (needs projected_pct >= 105% too).

And the genuine case must still fire: a real overrun trend, well past the
noise buffer, well before the reset."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

from spine.ops import usage

_fails = []


def check(name, cond):
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        _fails.append(name)


WEEK = 7 * 86400

print("\n1. false positive #1 (2026-09-13): high usedPct, projection under 100%")
# resets in 2.8h, 86% used, window started (reset - WEEK) -> now is ~98.3% elapsed
reset_ts_str = "2026-09-13T20:00:00Z"
from datetime import datetime, timezone
reset_ts = datetime.fromisoformat(reset_ts_str.replace("Z", "+00:00")).timestamp()
now = reset_ts - 2.8 * 3600
p = usage.pacing(86.0, reset_ts_str, WEEK, now=now)
check("flag fires on usedPct >= 85 alone", p["flag"] is True)
check("reset_risk does NOT fire (projection was under 100%)", p["reset_risk"] is False)
check("projected_pct is under 105 (the buffer)", (p["projected_pct"] or 0) < 105)

print("\n2. false positive #2 (2026-09-14): noise 6% into a fresh window")
reset_ts_str2 = "2026-09-20T20:00:00Z"
reset_ts2 = datetime.fromisoformat(reset_ts_str2.replace("Z", "+00:00")).timestamp()
now2 = reset_ts2 - WEEK + 0.06 * WEEK          # 6% elapsed
# used_pct fractionally ahead of elapsed% (6.05 vs 6.0), same shape as the
# live 2026-09-14 reading (6% used, proj 100.7%) - exactly-even pace (used ==
# elapsed) projects to precisely 100%, which is not what was observed live.
p2 = usage.pacing(6.05, reset_ts_str2, WEEK, now=now2)
check("exhaust_before_reset fires (it has no noise buffer)", p2["exhaust_before_reset"] is True)
check("flag does NOT fire (proj under 105, used under 85)", p2["flag"] is False)
check("reset_risk does NOT fire either", p2["reset_risk"] is False)

print("\n3. a genuine overrun still fires reset_risk")
reset_ts_str3 = "2026-08-30T22:00:00Z"
reset_ts3 = datetime.fromisoformat(reset_ts_str3.replace("Z", "+00:00")).timestamp()
now3 = reset_ts3 - 0.4 * WEEK                  # 60% elapsed
p3 = usage.pacing(90.0, reset_ts_str3, WEEK, now=now3)
check("projected_pct clears the 105% buffer", (p3["projected_pct"] or 0) >= 105)
check("exhaust_before_reset is True", p3["exhaust_before_reset"] is True)
check("reset_risk fires - this IS a real run-out", p3["reset_risk"] is True)
check("flag fires too", p3["flag"] is True)

print()
if _fails:
    print("FAIL (%d failure(s)): %s" % (len(_fails), _fails))
    sys.exit(1)
print("PASS (0 failure(s))")
