# -*- coding: utf-8 -*-
"""The pre-rules global keys, adopted onto their declared paths.

henry_policy and henry_permission_mode were read straight off settings.json at
their bare names, with no row in any table. spine/registry/behavior.py now
declares both; spine/storage/legacypolicy.py is the adoption of what an existing
installation had already set. One test per property that migration claims:

  1. a legacy value lands on the DECLARED path, and the reader then resolves it
     through the chain instead of through the legacy key
  2. it lands on the WORKSPACE layer, never on a project row - a global value
     folded into one repo would silently un-set every other repo
  3. running it twice changes nothing (idempotent by observation, no flag)
  4. an already-set rule WINS: the legacy key is not allowed to overwrite it
  5. a legacy value the rule's own validator rejects is REFUSED and REPORTED,
     never written and never silently dropped
  6. the legacy key survives the migration (readable one release), and the
     reader's floor still applies to a value that was refused
  7. byte identity at defaults: an installation that set nothing gets exactly
     today's mandate, to the character

SANDBOXED: repoints daemon.paths at a temp dir BEFORE importing anything that
resolves a path, and refuses to run if that did not take. Same preamble as
test_boards.py, for the same reason - these tests write.

Run:  py -3.12 ops/tests/test_legacy_policy.py
"""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

_SANDBOX = tempfile.mkdtemp(prefix="hd-legacypol-")
import daemon.paths
daemon.paths.DAEMON_ROOT = _SANDBOX

from spine.registry import behavior                           # noqa: E402
from spine.storage import db, events, legacypolicy, projectconfig   # noqa: E402

assert db.DBPATH.startswith(_SANDBOX), \
    "REFUSING TO RUN: db points at %s, not the sandbox" % db.DBPATH
assert events.SET.startswith(_SANDBOX), \
    "REFUSING TO RUN: settings point at %s, not the sandbox" % events.SET

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def workspace(**settings):
    """Replace the workspace store wholesale (db-backed since config-
    consolidation phase 2). events.settings() reads the db on every call and
    caches nothing, so this is the whole reset."""
    db.workspace_config_replace(settings)


def stored():
    return events.settings()


POLICY_PATH = "rule.report.judgement_policy.all"
PMODE_PATH = "rule.hands.permission_mode.all"

db.init()


# --- 1 + 2: a legacy value lands on the DECLARED path, at the WORKSPACE layer
print("\n1+2. adoption lands on the declared path, workspace layer")
workspace(henry_policy="Sei knapp und lande Arbeit.",
          henry_permission_mode="plan")
r = legacypolicy.adopt(actor="test")
check(sorted(m["path"] for m in r["moved"]) == sorted([POLICY_PATH, PMODE_PATH]),
      "both legacy keys were adopted (%s)" % [m["path"] for m in r["moved"]])
check(not r["refused"], "nothing was refused: %s" % r["refused"])

got = projectconfig.resolve(POLICY_PATH, "")
check(got["value"] == "Sei knapp und lande Arbeit.",
      "the mandate resolves to the legacy value (%r)" % got["value"])
check(got["layer"] == "workspace",
      "it resolves from the WORKSPACE layer, not default/project (%s)" % got["layer"])
check(projectconfig.resolve(PMODE_PATH, "")["value"] == "plan",
      "the permission mode resolves to the legacy value")

# The project table stays empty: a GLOBAL value has no business becoming one
# repo's override, because that would un-set it for every other repo.
check(db.project_config_projects() == [] or all(
        not db.project_config_get(p) for p in db.project_config_projects()),
      "NO project row was written - a global value stays global")

# And the READER now goes through the chain rather than the legacy key.
from cells.copilot import copilot, henry_broker                # noqa: E402
check(copilot.henry_pmode("") == "plan",
      "copilot.henry_pmode reads the adopted rule (%s)" % copilot.henry_pmode(""))
check(henry_broker._judgement_policy(None) == "Sei knapp und lande Arbeit.",
      "henry_broker resolves the mandate through the rule")


# --- 3: idempotent, by observation rather than by a stored flag
print("\n3. running it twice changes nothing")
check(legacypolicy.pending() == [],
      "pending() is empty once the values are where they belong")
again = legacypolicy.adopt(actor="test")
check(again == {"moved": [], "refused": []},
      "a second adopt() is a no-op (%s)" % again)
check(projectconfig.resolve(POLICY_PATH, "")["value"] == "Sei knapp und lande Arbeit.",
      "and the value is unchanged after the second run")


# --- 4: an already-set rule WINS over the legacy key
print("\n4. a rule that is already set is not overwritten")
workspace(henry_permission_mode="plan",
          rule={"hands": {"permission_mode": {"all": "acceptEdits"}}})
check([p["key"] for p in legacypolicy.pending()] == [],
      "a set rule makes the legacy key nothing to migrate")
check(copilot.henry_pmode("") == "acceptEdits",
      "and the RULE wins over the legacy key at read time (%s)" % copilot.henry_pmode(""))


# --- 5 + 6: an illegal legacy value is refused, reported, and left in place
print("\n5+6. an invalid legacy value is refused, never silently dropped")
workspace(henry_permission_mode="yolo")          # not in the rule's options
p = legacypolicy.pending()
check(len(p) == 1 and p[0]["key"] == "henry_permission_mode",
      "the bad value is still pending (%s)" % p)
check(bool(p[0]["refuse"]), "pending() carries the REASON it cannot move (%s)"
      % p[0]["refuse"])
r = legacypolicy.adopt(actor="test")
check(r["moved"] == [], "nothing was moved")
check(len(r["refused"]) == 1 and r["refused"][0]["key"] == "henry_permission_mode",
      "the refusal is REPORTED, not swallowed (%s)" % r["refused"])
_, present = projectconfig._dig(stored(), PMODE_PATH)
check(not present, "and no illegal value was written onto the declared path")
check(stored().get("henry_permission_mode") == "yolo",
      "the legacy key SURVIVES - deleting it would lose the owner's value")

# The floor still applies to a refused value, so behaviour does not change
# because a migration declined to run.
check(copilot.henry_pmode("") == "yolo",
      "the legacy floor still applies to the refused value (%s)" % copilot.henry_pmode(""))


# --- 7: byte identity at defaults
print("\n7. an installation that set nothing gets today's mandate exactly")
workspace()
check(legacypolicy.pending() == [], "nothing to migrate on a fresh install")
check(behavior.value("report.judgement_policy", "all") == "",
      "the declared default is empty - the mandate itself stays in the code")
check(henry_broker._judgement_policy(None) == henry_broker.DEFAULT_POLICY,
      "and the broker opens with DEFAULT_POLICY, byte for byte")
check(copilot.henry_pmode("") == "acceptEdits",
      "and the permission mode falls back to the declared default")


print("\n%d checks failed" % len(_fails))
for m in _fails:
    print("  FAIL " + m)
sys.exit(1 if _fails else 0)
