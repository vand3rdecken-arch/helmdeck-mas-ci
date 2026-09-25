# -*- coding: utf-8 -*-
"""events.plan_calibration counts EVERY HelmDeck consumer of the account, over
the window the percentage actually covers (owner 2026-09-26: "625 % of plan"
in Henry's chat, and the per-card watchdog runs on the same calibration).

used_pct is the WHOLE account's weekly utilization. Before the fix the
numerator held CARD turns only - Henry's chat turn left no event - so one
percent read cheaper than it is and every card's share came out inflated by
(all spend / card spend). And the sum ran over a rolling 7 days while the
percentage restarts at the reset, so last week's spend was divided by this
week's fresh percentage.

Runs the real path: Henry's turn goes through copilot._fold_stats (the ONE
owner of chat economics) into the sandboxed db, the calibration reads it back.
Fails on the old code on both counts."""
import os, sys, tempfile, time, types
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from spine.storage import db, events                              # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


db.DBPATH = os.path.join(tempfile.mkdtemp(prefix="calib_all_spend_"), "test.db")
db.init()

# the weekly window reset 2 days ago -> resets again in 5 days; 60% used
reset = datetime.now(timezone.utc) + timedelta(days=5)
fake = types.ModuleType("usage")
fake.cached = lambda refresh=True: {"status": "ok", "windows": [
    {"id": "weekly", "usedPct": 60, "resetsAt": reset.isoformat().replace("+00:00", "Z")}]}
import spine.ops                                                  # noqa: E402
sys.modules["spine.ops.usage"] = fake
spine.ops.usage = fake
S = {"pm": {}}

U = {"input_tokens": 1000, "output_tokens": 100}
# a card turn inside this window: $3
events.emit("turn", "card-1", cost=3.0, usage=U, models=["claude-sonnet-5"])
# a card turn 4 days ago: inside a rolling 7 days, but BEFORE this window began
old = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 4 * 86400))
events.emit("turn", "card-0", cost=10.0, usage=U, models=["claude-sonnet-5"], ts=old)
# Henry's chat turn: $3, through the real fold
from cells.copilot.chat import copilot                            # noqa: E402
copilot._fold_stats("owner", {"usage": U, "modelUsage": {"claude-opus-5-5": {}},
                              "total_cost_usd": 3.0}, {})

rows = [e for e in db.events_all() if e.get("kind") == "spend"]
check(len(rows) == 1 and rows[0].get("source") == "chat" and rows[0].get("cost") == 3.0,
      "Henry's chat turn lands as a 'spend' event with its measured cost")
check(not any(e.get("kind") == "turn" and e.get("track") == "-" for e in db.events_all()),
      "chat spend is NOT a 'turn' event (metrics() counts those as card turns)")

cal = events.plan_calibration(None, S)
check(cal is not None, "calibratable")
want = (3.0 + 3.0) / 60                         # card + Henry, this window only
got = (cal or {}).get("cost_per_pct")
check(got is not None and abs(got - want) < 1e-9,
      "cost per 1%% = (card + Henry in THIS window) / 60 = %.4f (got %r)" % (want, got))
card_share = 3.0 / got if got else None
check(card_share is not None and abs(card_share - 30.0) < 1e-6,
      "the $3 card reads 30%% of the week, its true half of 60%% (got %r)" % card_share)

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("plan-calibration-all-spend: PASS")
