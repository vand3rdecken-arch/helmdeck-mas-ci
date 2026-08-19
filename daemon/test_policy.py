# -*- coding: utf-8 -*-
"""Self-sandboxing tests for the policy control plane. Uses a temp LIVE file and
a stub `events` module so it never touches policy_live.json or events.jsonl.

Run: py -3.12 test_policy.py   (exits non-zero on first failure)
"""
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from daemon.spine import policy

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)

def raises(exc, fn, msg):
    try:
        fn()
        ok(False, msg + " (did not raise)")
    except exc:
        ok(True, msg)

# --- sandbox: temp LIVE + capture the append-only sink -----------------------
_tmp = tempfile.mkdtemp()
policy.LIVE = os.path.join(_tmp, "policy_live.json")

_emitted = []
_fake = types.ModuleType("daemon.spine.events")
_fake.emit = lambda kind, track, **fields: _emitted.append((kind, fields)) or {"kind": kind}
_fake.settings = lambda: {}   # policy.load()'s first-run wipLimit seed reads this
sys.modules["daemon.spine.events"] = _fake

print("policy control-plane self-test")

# 1. seeds from SEED, live created, defaults intact.
pols = policy.get_policies()
ok(pols.get("wipLimit") == 3, "seeded wipLimit=3")
ok(pols.get("gateBeforeReview") is True, "seeded gateBeforeReview=true")
ok(pols.get("agentMaySwap") is False, "seeded agentMaySwap=false")
ok(os.path.exists(policy.LIVE), "live file materialized from seed")

# 2. user swap updates value, returns previous, mirrors ONE tracked event.
_emitted.clear()
before = policy.swap("policies", {"wipLimit": 5}, actor="user", note="raise WIP")
ok(policy.get_policies()["wipLimit"] == 5, "user swap applied (wipLimit=5)")
ok(before["wipLimit"] == 3, "swap returned previous value (=3)")
ok(len(_emitted) == 1 and _emitted[0][0] == "reconfig", "swap mirrored exactly one reconfig event")
ok(_emitted[0][1]["actor"] == "user" and _emitted[0][1]["op"] == "swap", "event carries actor+op")
ok(_emitted[0][1]["before"]["wipLimit"] == 3 and _emitted[0][1]["after"]["wipLimit"] == 5, "event carries before/after")

# 3. version bumps on every swap.
v_before = policy.load()["version"]
policy.swap("policies", {"wipLimit": 6}, actor="user")
ok(policy.load()["version"] == v_before + 1, "version bumps per swap")

# 4. agent swap refused while agentMaySwap=false — and refusal is NOT a silent
#    mutation (nothing changed, no event).
_emitted.clear()
raises(policy.PolicyDenied, lambda: policy.swap("policies", {"wipLimit": 9}, actor="agent"),
       "agent swap denied while agentMaySwap=false")
ok(policy.get_policies()["wipLimit"] == 6, "denied agent swap did not mutate")
ok(len(_emitted) == 0, "denied swap emitted nothing (no untracked change)")

# 5. seed agentMaySwap=true → agent swap now allowed + tracked.
policy.swap("policies", {"agentMaySwap": True}, actor="user")
_emitted.clear()
policy.swap("policies", {"wipLimit": 9}, actor="agent", note="agent autoscaled WIP")
ok(policy.get_policies()["wipLimit"] == 9, "agent swap applied once agentMaySwap=true")
ok(_emitted[0][1]["actor"] == "agent", "agent swap attributed to actor=agent")

# 6. capability sandbox is human-only even with agentMaySwap=true.
raises(policy.PolicyDenied,
       lambda: policy.swap("capability_charter", {"capabilitySwapRequiresHuman": False}, actor="agent"),
       "capability_charter swap refused for agent (sandbox is human-only)")
policy.swap("capability_charter", {"note": "human tightened"}, actor="user")
ok(True, "capability_charter swap allowed for user")

# 7. revert is itself a tracked swap that restores the prior value.
b = policy.swap("charter", {"laws": ["only one law now"]}, actor="user")
ok(policy.get_charter()["laws"] == ["only one law now"], "charter swapped")
policy.revert("charter", b, actor="user")
ok(len(policy.get_charter()["laws"]) == 5, "revert restored the 5 seeded laws")

print(("\n%d FAILURE(S)" % len(_fails)) if _fails else "\nALL PASS")
sys.exit(1 if _fails else 0)
