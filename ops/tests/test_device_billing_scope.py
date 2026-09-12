# -*- coding: utf-8 -*-
"""Self-sandboxing test: a remote device's own Claude usage/cost must land
on ITS card (visible, per-card) but NEVER corrupt the shared plan
calibration (ops/docs/backlog/remote-device-execution PLAN-hardening.md
Phase D). events.plan_calibration divides tokens burned in the weekly
window by THIS ACCOUNT's own usage percentage (from the Anthropic usage
API) - an "external" device's tokens never drew on that quota, so folding
them in would inflate tokens_per_pct for every card sharing the real
account. Measured 2026-08-25: without spine.turn.econ._record_econ's
external=True tag (and plan_calibration's matching exclusion), this
corruption is silent, not an error.

Run: py -3.12 ops/tests/test_device_billing_scope.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-billingscope-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.SET = os.path.join(tmp, "settings.json")
    db.init()

    from spine.turn.econ import _record_econ

    # -- 1: _record_econ tags the emitted turn event -------------------------
    print("\n_record_econ: external tag on the emitted turn event")
    meta = {"usage": {"input_tokens": 1000, "output_tokens": 500}, "cost_usd": 0.05,
           "models": ["claude-sonnet-5"]}
    t_local = {"id": "local-card", "ai_cost": 0.0}
    _record_econ(t_local, meta)   # normal local-card call, external defaults False
    t_ext = {"id": "device-card-ext", "ai_cost": 0.0}
    _record_econ(t_ext, meta, external=True)
    t_shared = {"id": "device-card-shared", "ai_cost": 0.0}
    _record_econ(t_shared, meta, external=False)

    ev = events.read_events()
    turns = {e["track"]: e for e in ev if e.get("kind") == "turn"}
    ok("local-card" in turns and not turns["local-card"].get("external"),
       "a normal local-card turn carries no external tag")
    ok(turns.get("device-card-ext", {}).get("external") is True,
       "an external-scoped device turn is tagged external=True")
    ok(not turns.get("device-card-shared", {}).get("external"),
       "a shared-scoped device turn (billing_scope='shared') carries NO external tag - "
       "it's real spend on the daemon's own account, same as a local card")

    ok(t_local["ai_cost"] > 0 and t_ext["ai_cost"] > 0 and t_shared["ai_cost"] > 0,
       "ai_cost is folded onto the CARD regardless of external - per-card visibility "
       "is not what billing_scope restricts")

    # -- 2: plan_calibration excludes external turns from its window sum -----
    print("\nplan_calibration: external turns excluded from the calibration window")
    from spine.ops import usage as _usage
    _usage.cached = lambda refresh=True: {
        "status": "ok",
        "windows": [{"id": "weekly", "usedPct": 10.0, "resetsAt": "2099-01-01T00:00:00Z"}],
    }
    calib_with_external = events.plan_calibration(ev)
    only_local = [e for e in ev if not e.get("external")]
    calib_local_only = events.plan_calibration(only_local)
    ok(calib_with_external is not None and calib_local_only is not None,
       "calibration computes in both cases (sanity)")
    ok(calib_with_external["observed_tokens"] == calib_local_only["observed_tokens"],
       "including vs excluding the external-tagged events yields the SAME "
       "observed_tokens - proves the external turn was already excluded, not "
       "just coincidentally absent")
    # 1000 in + 500 out from the local-card turn; the shared-scope device
    # turn ALSO counts (real account spend) - external-scope does not.
    expected_tok = 1500 * 2   # local-card + device-card-shared, NOT device-card-ext
    ok(calib_with_external["observed_tokens"] == expected_tok,
       "observed_tokens = local-card + shared-scope device turn only (got %d, want %d)"
       % (calib_with_external["observed_tokens"], expected_tok))

    print("\n%d failure(s)" % len(_fails))
    if _fails:
        sys.exit(1)
    print("all green - %s" % tmp)


if __name__ == "__main__":
    main()
