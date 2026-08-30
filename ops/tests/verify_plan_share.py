# -*- coding: utf-8 -*-
"""Proves the flat-plan cost unit: tokens -> % of the Claude subscription.

The claim under test is events.plan_calibration(): the usage endpoint publishes
a PERCENTAGE and never the absolute allowance, so the board calibrates
tokens_per_pct = (our tokens inside the live weekly window) / used_pct.
Everything here is arithmetic + guard rails, so it runs with no daemon, no
network and no Claude login - the usage module is faked in sys.modules."""
import os
import sys
import time
import types

# REPO ROOT + the real package path. This file was dead from the day the tree
# became spine/cells/surfaces/ops: it pointed at "<this dir>/../daemon" and did
# `import events`, and neither has existed since. It still COMPILED, which is
# exactly why nobody noticed - an unrunnable check looks identical to a passing
# one until someone tries to run it.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.storage import events                                 # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else " -> got %r, want %r" % (got, want)))
    if not ok:
        FAILED.append(name)


def _install_fake(mod):
    """Put a fake in the place `from spine.ops import usage` actually looks.

    Setting sys.modules["spine.ops.usage"] alone is NOT enough: `from X import Y`
    checks the parent package's ATTRIBUTE first, and spine.ops.usage is already
    bound to the real module by the time this runs - so the fake would sit in
    sys.modules being ignored, the real (cold) cache would return None, and the
    checks below would fail against a product that is fine. Bind both."""
    import spine.ops
    sys.modules["spine.ops.usage"] = mod
    spine.ops.usage = mod


def fake_usage(used_pct, status="ok"):
    m = types.ModuleType("usage")
    m.cached = lambda refresh=True: {
        "status": status,
        "windows": [{"id": "weekly", "usedPct": used_pct, "resetsAt": "2026-08-15T00:00:00Z"}],
    }
    _install_fake(m)


def turn(tokens, age_days=0.0):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - age_days * 86400))
    return {"kind": "turn", "ts": ts, "usage": {"input_tokens": tokens, "output_tokens": 0}}


def settings(plan="max", plan_tokens_week=0):
    return {"pm": {"plan": plan, "plan_tokens_week": plan_tokens_week}}


print("plan_calibration - the measured path")
fake_usage(10.0)
# 1M tokens inside the window == 10% of the weekly quota -> 1% costs 100k tokens.
c = events.plan_calibration([turn(1_000_000, age_days=1)], settings())
check("source is measured", c["source"], "measured")
check("tokens_per_pct = tokens/used_pct", c["tokens_per_pct"], 100_000.0)
check("carries the window utilization", c["used_pct"], 10.0)
# a 250k-token card is therefore 2.5% of the plan
check("a 250k card = 2.5% of plan", round(250_000 / c["tokens_per_pct"], 2), 2.5)

print("plan_calibration - the owner-configured allowance wins")
c = events.plan_calibration([turn(1_000_000)], settings(plan_tokens_week=50_000_000))
check("source is configured", c["source"], "configured")
check("1% = allowance/100", c["tokens_per_pct"], 500_000.0)

print("plan_calibration - only tokens INSIDE the rolling window calibrate")
fake_usage(10.0)
c = events.plan_calibration([turn(1_000_000, age_days=1), turn(9_000_000, age_days=30)], settings())
check("30-day-old turn excluded", c["tokens_per_pct"], 100_000.0)
check("observed tokens = in-window only", c["observed_tokens"], 1_000_000)

print("plan_calibration - cache reads count against the quota")
fake_usage(10.0)
ev = [{"kind": "turn", "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
       "usage": {"input_tokens": 10, "cache_creation_input_tokens": 90,
                 "cache_read_input_tokens": 800, "output_tokens": 100}}]
check("all four token classes summed", events.plan_calibration(ev, settings())["observed_tokens"], 1000)

print("plan_calibration - guards return None so the UI falls back to tokens")
fake_usage(0.5)
check("window barely used -> no wild extrapolation",
      events.plan_calibration([turn(1_000_000)], settings()), None)
fake_usage(10.0)
check("no recorded turns", events.plan_calibration([], settings()), None)
check("non-turn events only",
      events.plan_calibration([{"kind": "lane", "ts": time.strftime("%Y-%m-%d %H:%M:%S")}], settings()), None)
fake_usage(10.0, status="unavailable")
check("usage endpoint unavailable", events.plan_calibration([turn(1_000_000)], settings()), None)
_install_fake(types.ModuleType("usage"))                  # no cached() at all
check("usage module broken", events.plan_calibration([turn(1_000_000)], settings()), None)

print("usage.cached - never blocks, backs off on ATTEMPT")
import importlib                                                  # noqa: E402
import spine.ops                                                  # noqa: E402
sys.modules.pop("spine.ops.usage", None)
real_usage = importlib.import_module("spine.ops.usage")           # the real one back
spine.ops.usage = real_usage
calls = []
real_usage.snapshot = lambda force=False: calls.append(1)         # never fills the cache
t0 = time.time()
for _ in range(50):
    real_usage.cached()
elapsed = time.time() - t0
time.sleep(0.3)                                                   # let any threads land
check("50 polls stay non-blocking", elapsed < 1.0, True)
check("50 polls -> at most 1 network attempt", len(calls) <= 1, True)
check("cold cache returns None, not a crash", real_usage.cached(refresh=False), None)

print("")
if FAILED:
    print("FAILED: " + ", ".join(FAILED))
    sys.exit(1)
print("ALL PLAN-SHARE CHECKS PASSED")
