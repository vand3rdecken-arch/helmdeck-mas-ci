# -*- coding: utf-8 -*-
"""Self-sandboxing test for the PROJECT LAYER of the harness config
(ops/docs/backlog/harness-config-ui phase 1, wired up in phase 3).

WHY THIS FILE EXISTS AT ALL. Phase 1 shipped the chain, the tracked writer and
the whitelist, and phase 2 shipped the rules that ride on them - with no test
between them. The result was a layer that was inert END TO END and said nothing:
overridable() registered a rule's bare namespace (`rule.tone.length`) while
every reader names a surface (`rule.tone.length.pm`), so validate() refused the
only shape anyone writes and stored() filtered out the only shape anyone reads.
Both halves were internally consistent, which is exactly why reading them did
not reveal it. So the first assertion here is the one nobody made: a value
written for a project MUST come back changed.

What this pins down:
  1. a project value round-trips: write -> resolve says layer "project" and
     inherited False, and behavior.value() (the path Henry's brief reads) sees it
  2. the workspace is UNAFFECTED by a project write - two projects, two answers
  3. clearing INHERITS again rather than storing a null, and revert() restores
     inheritance rather than freezing the old effective value
  4. a workspace write does not eat its siblings (events.save_settings merges
     ONE level deep, so the whole top-level key has to be rebuilt)
  5. the four values of the length law stay four - the `default` layer reports
     the SURFACE's default, not the first declared surface's
  6. the refusals: readonly, fixed, an option outside the vocabulary, a wrong
     type, a shortened additive list, and a project rule with no project
  7. the fingerprint - Henry's warm-process cache key - moves when a value moves

Run: py -3.12 ops/tests/test_project_config.py
"""
import json
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
    tmp = tempfile.mkdtemp(prefix="helmdeck-project-config-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.EV = os.path.join(tmp, "events.jsonl")
    events.SET = os.path.join(tmp, "settings.json")
    db.init()

    from spine.registry import behavior as bh
    from spine.storage import projectconfig as pc

    A, B = "c:/proj/alpha", "c:/proj/beta"

    # -- 1. the assertion nobody made ------------------------------------
    print("\n[a project value round-trips]")
    ok(bh.value("initiative.estimate", "pm", A) is True, "starts at the declared default")
    before, err = pc.write_scoped({"rule.initiative.estimate.pm": False}, project=A, actor="owner")
    ok(err is None, "write_scoped accepts the per-surface path (err=%r)" % err)
    ok(bh.value("initiative.estimate", "pm", A) is False,
       "behavior.value - the path Henry's brief reads - sees the project value")
    got = pc.resolve("rule.initiative.estimate.pm", A)
    ok(got["layer"] == "project" and got["inherited"] is False,
       "resolve badges it 'project' / not inherited (got %r)" % got)

    every = pc.overridable()
    ok(all(bh.split_path(p)[0] is not None for p in every),
       "every whitelisted path names a real rule AND surface")
    ok("rule.initiative.estimate.pm" in every,
       "the whitelist names the path that is actually stored")

    # -- 2. projects do not bleed ----------------------------------------
    print("\n[one project's value is not another's]")
    ok(bh.value("initiative.estimate", "pm", B) is True, "project B still inherits")
    ok(bh.value("initiative.estimate", "pm", "") is True, "the workspace is untouched")
    ok(pc.resolve("rule.initiative.estimate.pm", B)["inherited"] is True,
       "project B is badged as inheriting")

    # -- 3. absent means inherited ---------------------------------------
    print("\n[clearing restores inheritance, it does not store a null]")
    pc.revert(A, before, actor="owner")
    ok(bh.value("initiative.estimate", "pm", A) is True, "revert() puts the inherited value back")
    ok(pc.resolve("rule.initiative.estimate.pm", A)["inherited"] is True,
       "and the badge says inherited again")
    ok("rule.initiative.estimate.pm" not in db.project_config_get(A),
       "the ROW is gone - absent is a property of the table, not a sentinel")

    # revert must restore INHERITANCE, not freeze the old effective value:
    # write over a workspace value, then undo, and the workspace must win again.
    pc.write_scoped({"rule.hands.own_hands.pm": False}, project=A, actor="owner")
    b2, _ = pc.write_scoped({"rule.hands.own_hands.pm": True}, project=A, actor="owner")
    pc.revert(A, b2, actor="owner")
    ok(bh.value("hands.own_hands", "pm", A) is False,
       "revert of a second write lands on the FIRST value, not on the default")

    # -- 4. a workspace write keeps its siblings -------------------------
    print("\n[a workspace write does not eat the subtree]")
    pc.write_scoped({"rule.tone.length.voice": "normal"}, actor="owner")
    pc.write_scoped({"rule.tone.address.pm": "Sie"}, actor="owner")
    ok(bh.value("tone.length", "voice") == "normal", "the first workspace value survives")
    ok(bh.value("tone.address", "pm") == "Sie", "the second landed too")
    stored = json.load(open(events.SET, encoding="utf-8")).get("rule") or {}
    ok(set(stored.get("tone") or {}) == {"length", "address"},
       "both live under one `rule` subtree (got %r)" % sorted(stored.get("tone") or {}))

    # -- 5. four values stay four ----------------------------------------
    print("\n[the length law keeps one value per surface]")
    per = {s: bh.value("tone.length", s) for s in ("pm", "voice", "wear", "glass")}
    ok(per == {"pm": "knapp", "voice": "normal", "wear": "knapp", "glass": "knapp"},
       "setting voice moved ONLY voice (got %r)" % per)
    dflt = [r for r in pc.chain("rule.tone.length.wear") if r["layer"] == "default"]
    ok(dflt and dflt[0]["present"],
       "the chain's `default` layer resolves per surface, not per rule")

    # -- 6. the refusals --------------------------------------------------
    print("\n[what may not be written, refused BY NAME]")
    cases = [
        ("rule.tone.examples.pm", "x", "shown, never set", "a readonly rule"),
        ("rule.hands.configure_allowlist.pm", "x", "is fixed", "a fixed rule"),
        ("rule.tone.length.pm", "riesig", "takes one of", "a value outside the vocabulary"),
        ("rule.tone.humor.pm", "ja", "true or false", "a wrong type"),
        ("rule.report.followup_interval.pm", -5, "cannot be negative", "a negative number"),
        ("rule.nope.nope.pm", 1, "no such rule", "a path naming no rule"),
    ]
    for path, val, needle, what in cases:
        err = pc.write_scoped({path: val}, project=A, actor="owner")[1]
        ok(err is not None and needle in err, "%s is refused (%r)" % (what, err))

    err = pc.write_scoped({"rule.hands.protected_files.pm": ["only-one.py"]}, actor="owner")[1]
    ok(err is not None and "may only be extended" in err,
       "the protected-file list may not be SHORTENED (%r)" % err)
    keep = list(bh.default_of(bh.by_key("hands.protected_files"), "pm")) + ["ops/deploy/ship.sh"]
    err = pc.write_scoped({"rule.hands.protected_files.pm": keep}, actor="owner")[1]
    ok(err is None, "but it may be extended (err=%r)" % err)

    err = pc.write_scoped({"rule.initiative.estimate.pm": False}, project="", actor="owner")[1]
    ok(err is not None and "no project" in err,
       "a per-project rule with no repo says so instead of writing the workspace")

    # A refused write must land NOTHING - not the legal half of the patch.
    v_before = bh.value("hands.own_hands", "pm", A)
    pc.write_scoped({"rule.hands.own_hands.pm": False, "rule.tone.humor.pm": "ja"},
                    project=A, actor="owner")
    ok(bh.value("hands.own_hands", "pm", A) == v_before,
       "one bad key fails the WHOLE write - no half-applied patch")

    # -- 7. the warm-process cache key -----------------------------------
    print("\n[the fingerprint observes the change]")
    fp = bh.fingerprint("")
    pc.write_scoped({"rule.tone.humor.pm": False}, actor="owner")
    ok(fp != bh.fingerprint(""), "a workspace rule edit moves the fingerprint")
    fp_a = bh.fingerprint(A)
    pc.write_scoped({"rule.initiative.progress.pm": False}, project=A, actor="owner")
    ok(fp_a != bh.fingerprint(A), "a project rule edit moves that project's fingerprint")

    # -- the whole point: the BRIEF changes -------------------------------
    # A knob that moves a stored value and leaves Henry's instructions alone
    # would pass every assertion above and still be a dummy. This is the one
    # that says the chain reaches the thing the owner complained about.
    print("\n[the value reaches Henry's brief]")
    from spine.registry import harness
    was = harness.brief("board-copilot")
    pc.write_scoped({"rule.tone.address.pm": "du"}, actor="owner")
    du = harness.brief("board-copilot")
    pc.write_scoped({"rule.tone.address.pm": "Sie"}, actor="owner")
    sie = harness.brief("board-copilot")
    ok('always "du"' in du and 'always "du"' not in sie,
       "flipping the address rule rewrites that sentence in the rendered brief")
    ok('always "Sie"' in sie, "and the new wording is the one the rule declares")
    ok("{{rule:" not in sie and len(sie) > 20000,
       "the brief is still the whole brief, with no machinery showing")
    ok(was is not None, "brief() answered before the edit too")

    # -- the write is audited, not worked around -------------------------
    print("\n[the write is in the append-only sink]")
    rows = [json.loads(x) for x in open(events.EV, encoding="utf-8") if x.strip()]
    ok(any(r.get("op") == "project_config" for r in rows),
       "the project write mirrored op/actor/before/after into events.jsonl")

    print("\n%d failure(s)" % len(_fails))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
