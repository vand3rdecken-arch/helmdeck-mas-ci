# -*- coding: utf-8 -*-
"""Self-sandboxing tests for the policy control plane. Uses a temp LIVE file and
a stub `events` module so it never touches policy_live.json or events.jsonl.

Run: py -3.12 test_policy.py   (exits non-zero on first failure)
"""
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# db FIRST: policy.load()/swap() are db-backed (config-consolidation phase
# 3) - sandbox ROOT+DBPATH together, before importing policy, or a swap()
# call below would mutate the REAL production policy_doc row (measured
# 2026-09-03: exactly this gap in a sibling test archived real settings.json).
_tmp = tempfile.mkdtemp()
# daemon.paths.DAEMON_ROOT stays REAL: policy.SEED binds to it at import time
# and must keep resolving to the real tracked policy_seed.json (read-only,
# safe) - only db.ROOT/DBPATH move, same pattern as test_audit_query.py.
from spine.storage import db
db.ROOT = _tmp
db.DBPATH = os.path.join(_tmp, "test.db")
db.init()

from spine.auth import policy
# LIVE is still read as a MIGRATION SOURCE (a pre-db install's leftover
# file) - left at its default it resolves to the REAL daemon/policy_live.json
# via daemon.paths.DAEMON_ROOT bound at policy.py's import time, and a stray
# real file there would leak real production values into this sandbox
# (caught by this test itself: wipLimit read back as 6, the machine's real
# live value, instead of the seed's 3). Point it at the empty tmp dir, same
# as every other policy-touching test already does.
policy.LIVE = os.path.join(_tmp, "policy_live.json")

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

_emitted = []
_fake = types.ModuleType("spine.storage.events")
_fake.emit = lambda kind, track, **fields: _emitted.append((kind, fields)) or {"kind": kind}
_fake.settings = lambda: {}   # policy.load()'s first-run wipLimit seed reads this
sys.modules["spine.storage.events"] = _fake

print("policy control-plane self-test")

# 1. seeds from SEED, live created, defaults intact.
pols = policy.get_policies()
ok(pols.get("wipLimit") == 3, "seeded wipLimit=3")
ok(pols.get("gateBeforeReview") is True, "seeded gateBeforeReview=true")
ok(pols.get("agentMaySwap") is False, "seeded agentMaySwap=false")
ok(db.policy_doc_get() is not None, "live doc materialized from seed (db row, not a file since phase 3)")

# 1b. new-seed-key rollout seam (found 2026-09-03: a stored doc returned
# AS-IS forever, so buildLoopEnabled/copilotEnabled/engineerEnabled/
# permissions/sod_accept - every seed key added after a workspace's first
# boot - were silently absent from every /policy response on the real live
# workspace; the app's Modules & Rules screen has no Python-side "default
# true" fallback like cells.enabled() does, so a genuinely missing key
# rendered as an unexplained OFF toggle). Simulate a doc that predates a
# seed key by deleting it straight from the stored row, then confirm the
# NEXT load() call heals it without touching anything the caller set.
doc = db.policy_doc_get()
del doc["policies"]["buildLoopEnabled"]
doc["policies"]["wipLimit"] = 42     # an explicit value load() must NOT touch
db.policy_doc_put(doc)
healed = policy.load()
ok(healed["policies"]["buildLoopEnabled"] is True,
   "a seed key missing from an existing stored doc is backfilled from SEED")
ok(healed["policies"]["wipLimit"] == 42,
   "backfill never overwrites a key that WAS present, even a non-default one")
ok("permissions" in healed["policies"] and
   "templates.manage" in (healed["policies"]["permissions"].get("owner") or []),
   "a whole missing top-level key (permissions) backfills as one unit")
db.policy_doc_put({**healed, "policies": {**healed["policies"], "wipLimit": 3}})  # reset for the tests below

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
