# -*- coding: utf-8 -*-
"""THE PRE-RULES GLOBAL KEYS, adopted once onto their declared paths.

Two of Henry's most behaviour-defining values predate the rule table and were
read straight off `settings.json` at their bare top-level names:

    henry_policy            -> rule.report.judgement_policy.all
    henry_permission_mode   -> rule.hands.permission_mode.all

Both are now declared in spine/registry/behavior.py, which is what gives them a
scope, a validator, a size bound, a provenance badge and a row on the harness
screen. This module is the other half of that move: the ADOPTION of whatever an
existing installation had already set, so declaring the rule does not silently
reset a machine that had configured Henry by hand.

FOUR PROPERTIES, EACH OF THEM LOAD-BEARING
------------------------------------------
1. IT LANDS ON THE WORKSPACE LAYER, NOT ON A PROJECT ROW. Both rules are scoped
   `project`, and the project layer is per-repo. The legacy keys were GLOBAL -
   they applied to every repo and to the repo-less turns too. Folding a global
   value into one project's row would therefore be a behaviour CHANGE dressed as
   a migration: that repo would keep the setting and every other repo would
   silently fall back to the default. The workspace layer is where a global
   value's meaning is preserved exactly, and the per-project DB overlay stays
   available on top of it - which is the whole point of the chain.

2. IT ONLY EVER FILLS AN EMPTY SLOT. A legacy key is adopted only when the
   declared path is ABSENT. If someone has already set the rule, the rule wins
   and the legacy key is left alone - the resolution order the readers already
   implement (copilot.henry_pmode, henry_broker._judgement_policy both treat the
   legacy key as the FLOOR), stated once more here so the migration cannot
   contradict it.

3. IT VALIDATES BEFORE IT ADOPTS, AND REPORTS WHAT IT REFUSED. A legacy key is
   free text on disk; `henry_permission_mode` could hold anything. A value the
   rule's own check_value rejects is NOT written and NOT dropped in silence - it
   is returned in `refused` and printed at boot, because a migration that
   quietly discards a value the owner set is exactly the data loss this module
   exists to prevent. The reader's floor still applies to it, so behaviour does
   not change either way.

4. THE LEGACY KEY IS NOT DELETED. It stays readable for one release, as the
   PRD's own pattern for policy.lane_labels does. Deleting it would make a
   rollback to the previous daemon lose the value, and this migration has no
   business being one-way while the code that reads the floor still ships.

IDEMPOTENT BY CONSTRUCTION, not by a stored "migrated" flag: `pending()`
re-derives the answer from the two stores every time it is asked, so a second
call after a successful run finds nothing to do. That is the no-monkey-patches
law applied to a migration - the state is observed, never remembered.
"""

# (legacy settings.json key, declared rule path). The rule half is not restated
# prose: behavior.split_path resolves it back to the real row below, so a path
# that stops existing fails LOUDLY in adopt() rather than migrating into
# nothing.
LEGACY_KEYS = (
    ("henry_policy", "rule.report.judgement_policy.all"),
    ("henry_permission_mode", "rule.hands.permission_mode.all"),
)

# The same bound projectconfig.write puts on a project row, applied to the
# workspace half too. write_workspace does not validate (it is the raw settings
# writer), so an 80 KB legacy mandate would otherwise land unbounded on a path
# whose per-project twin refuses it - two layers of one knob with two different
# limits is a trap, not a policy.
MAX_VALUE_BYTES = 8192


def _present(doc, path):
    """(value, present) for a dotted path - projectconfig._dig's contract,
    reached through projectconfig itself so there is one implementation."""
    from spine.storage import projectconfig
    return projectconfig._dig(doc, path)


def _reject(path, val):
    """Why this legacy value may not be adopted onto `path`, else None."""
    import json

    from spine.registry import behavior
    rule, surface, err = behavior.writable(path)
    if err:
        return err
    err = behavior.check_value(rule, surface, val)
    if err:
        return err
    try:
        enc = json.dumps(val)
    except (TypeError, ValueError):
        return "value is not JSON"
    if len(enc.encode("utf-8")) > MAX_VALUE_BYTES:
        return "value exceeds %d bytes" % MAX_VALUE_BYTES
    return None


def pending():
    """[{key, path, value, refuse}] for every legacy key that still has
    somewhere to go. DERIVED from the two stores on every call, which is what
    makes running this twice a no-op without a flag to trust.

    `refuse` is None for the ones that will be adopted and carries the reason
    for the ones that will not - the review view renders both, so a value the
    daemon declined to move is visible rather than merely absent."""
    from spine.storage import events
    s = events.settings()
    out = []
    for key, path in LEGACY_KEYS:
        raw = s.get(key)
        if isinstance(raw, str):
            raw = raw.strip()
        if not raw:
            continue                       # never set, or cleared: nothing to move
        _, already = _present(s, path)
        if already:
            continue                       # the rule is set; the rule wins
        out.append({"key": key, "path": path, "value": raw,
                    "refuse": _reject(path, raw)})
    return out


def adopt(actor="system"):
    """Move every adoptable legacy key onto its declared path. Returns
    {moved: [...], refused: [{key, path, why}]}.

    Goes through projectconfig.write_workspace - the tracked writer - rather
    than touching settings.json, so this migration lands in the same audit
    history as any other rule edit instead of appearing as an unexplained value
    that was simply always there."""
    todo = pending()
    moved, refused = [], []
    patch = {}
    for row in todo:
        if row["refuse"]:
            refused.append({"key": row["key"], "path": row["path"],
                            "why": row["refuse"]})
            continue
        patch[row["path"]] = row["value"]
        moved.append({"key": row["key"], "path": row["path"]})
    if patch:
        from spine.storage import events, projectconfig
        _, err = projectconfig.write_workspace(patch, actor=actor)
        if err:
            return {"moved": [], "refused": refused + [
                {"key": m["key"], "path": m["path"], "why": err} for m in moved]}
        try:
            events.emit("reconfig", "-", op="legacy_policy_adopted", actor=actor,
                        adopted=sorted(p for p in patch),
                        keys=sorted(m["key"] for m in moved),
                        refused=sorted(r["key"] for r in refused))
        except Exception:                                    # noqa: BLE001
            pass              # a sink hiccup never unwrites a migration that landed
    return {"moved": moved, "refused": refused}


def run_at_boot():
    """Best-effort boot hook. Prints what it did and what it refused; never
    raises. A settings file that will not parse must not stop the daemon from
    serving, and the readers' legacy floor means an unmigrated install keeps
    behaving exactly as it did."""
    try:
        r = adopt()
    except Exception as e:                                   # noqa: BLE001
        print("LEGACY POLICY: not adopted: %s" % e)
        return {"moved": [], "refused": []}
    for m in r["moved"]:
        print("LEGACY POLICY: %s adopted onto %s (workspace layer)"
              % (m["key"], m["path"]))
    for x in r["refused"]:
        print("LEGACY POLICY: %s NOT adopted (%s) - the legacy key still applies "
              "as the floor" % (x["key"], x["why"]))
    return r


__all__ = ["LEGACY_KEYS", "MAX_VALUE_BYTES", "pending", "adopt", "run_at_boot"]
