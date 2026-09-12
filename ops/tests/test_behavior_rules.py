# -*- coding: utf-8 -*-
"""THE TWO CONTRACTS of spine/registry/behavior.py (harness-config-ui phase 2).

Same shape as ops/tests/test_harness_layer.py: a standalone script with a
hand-rolled check(), self-sandboxing (no daemon, no git, no network, no LLM),
exit 1 on any failure.

1. SLOT EQUALITY. Every `slot`-wired rule has exactly one slot in the brief of
   each surface it declares, and every slot in a brief has exactly one rule. A
   rule with no slot changes nothing and CLAIMS to - which is the entire class
   of bug the renderer exists to prevent, so it is the first thing checked.

2. BYTE IDENTITY AT DEFAULTS. With every value on its default, each rendered
   brief must equal the text that shipped before the slots were cut in. That is
   the acceptance keeping "structured" from meaning "quietly changed": these
   briefs grew over months, every line has a date and a cause, and this commit
   is allowed to be markers-for-text and nothing else.

   HOW THE "BEFORE" IS PINNED. A test may not shell out to git, so the expected
   text is pinned as a SHA-256 per surface, captured from the pre-slot files.
   That is deliberately annoying in the right way: a future brief edit fails
   here until its author updates the hash, which makes changing Henry's
   behaviour an explicit act rather than a side effect. Regenerate with
   `py -3.12 ops/tests/test_behavior_rules.py --hashes` and put the new value
   in the same commit as the prose change.
"""
import hashlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE)) if os.path.basename(
    os.path.dirname(HERE)) == "ops" else os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spine.registry import behavior          # noqa: E402
from spine.registry import harness           # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _read(path):
    """Newline-NORMALISED read. The repo holds some briefs CRLF and some LF
    (harness._nl_style preserves whichever a file already had), and the line
    ending is not what this test is about - the words are."""
    with io.open(os.path.join(ROOT, path), encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Which file carries each surface's brief. The `pm` entry is board-copilot.md
# via harness.SURFACES; the overlay surfaces got files of their own in this
# phase (they were Python string constants before).
SURFACE_FILES = {
    "pm": "cells/copilot/harness/agents/board-copilot.md",
    "voice": "cells/copilot/harness/agents/voice-style.md",
    "wear": "cells/copilot/harness/agents/wear-brief.md",
    "glass": "cells/copilot/harness/agents/glass-brief.md",
}

# SHA-256 of each surface's brief rendered with every value on its default.
#
# EACH ONE WAS VERIFIED AGAINST THE PRE-SLOT TEXT, not merely captured from the
# post-edit files: `pm` was diffed against board-copilot.md at commit 883c72f,
# and voice/wear/glass against the VOICE_STYLE / WEAR_BRIEF / GLASS_BRIEF
# constants they were lifted out of (copilot.py, routes_wear.py,
# routes_glance.py at the same commit). A hash captured from the new files
# without that step would pin whatever drift the edit introduced and call it
# the baseline - which is the exact failure this check exists to catch.
#
# See the module docstring before changing one of these.
#
# `pm` MOVED ONCE, deliberately, on owner decision 2026-09-02: `jira` was in the
# enforced ALLOWED_CONFIG but missing from the brief's configure paragraph, and
# the owner chose to tell Henry about it rather than to withdraw the capability.
# That is a real change to Henry's brief, so the pin had to move with it - and
# it moved only after the diff against 883c72f was shown to be EXACTLY one added
# line (the jira line) and nothing else. The check going red is what forced that
# proof; a pin updated without it would have been a rubber stamp.
# ALL FOUR moved on owner decision 2026-09-04 (harness-reorg-under-cells):
# briefs now live at cells/<id>/harness/agents/ instead of ops/harness/agents/
# - SURFACE_FILES below points at the new paths. render() hashes the RAW file
# _read() returns, frontmatter included, so two real changes moved the pins:
# (1) `pm` (board-copilot.md) gained the GRILLEN section - a genuine,
# intentional change to Henry's brief (goal-setting / big-or-fuzzy builds now
# trigger a rounds-based interview instead of a guess). (2) all four briefs'
# `$schema:` frontmatter line was repointed from the now-dangling
# `../schema/agent.schema.json` (correct from the old ops/harness/agents/
# location, broken from cells/<id>/harness/agents/) to the working relative
# path - confirmed via `git diff` to be the ONLY byte change for voice/wear/
# glass (pm/board-copilot carries both changes). Neither is a rubber stamp:
# the diff was read before the pin moved, same discipline as the jira note
# above.
# `pm` moved again 2026-09-04 (same day, later): the GRILLEN section gained
# one bullet - on the GOAL trigger, round 1 always pins the owner's expected
# TIMELINE / SCOPE boundary / BUDGET share (owner instruction "make sure to
# always clarify timeline, scope and budget expected by owner"). `git diff`
# read before the move: exactly that one 7-line bullet, nothing else.
# `pm` moved 2026-09-05: the estimate bullet gained the ZWEI-UHREN law - agent
# work is quoted in minutes/hours, pipeline waits (owner acceptance, Apple/Play,
# budget gates) SEPARATELY, never one merged "Tage" number (owner report: "seine
# AI-Entwicklung ist schneller, aber er schaut auf den Gesamtprozess" - Henry
# quoted days for the watch app when the agent share is hours). `git diff` read
# before the move: exactly that one 7-line passage, nothing else.
# `pm` moved 2026-09-11 (henry-memory-db-authority): the memory paragraph was
# rewritten to teach the <memory-save>/<memory-delete> sentinel protocol
# instead of implying a direct file write, and HOW TO REPLY gained one numbered
# step pointing at it. A genuine, intentional change to Henry's brief (he no
# longer has a reason to reach for the Write tool for memory at all) - `git
# diff` read before the move: exactly those two passages, nothing else.
EXPECTED = {
    "pm": "7d38d20c724493837397b8de7170c42c8255944dbd94178c75329365ae8d635a",
    "voice": "0b0e859a96711ab6c0733a92dc2cf6993008dc4b141df43ae97ad2eb9f8f51f9",
    "wear": "dbc084339e0a88466a924a1ea74d5e10ba6ed3f3eb42c0ba9a5bb2f9cb5989f2",
    "glass": "6c8aced6297bfc068b2b293ab857cc07ec15941780daa98cef8a9c77686f2fff",
}


def test_slot_equality():
    print("\n[slot equality]")
    declared = {}
    for r in behavior.BEHAVIOR_RULES:
        check(r["wire"] in behavior.WIRINGS,
              "%s has a known wiring (%s)" % (r["key"], r["wire"]))
        if r["wire"] != "slot":
            continue
        for s in behavior.surfaces_of(r):
            declared.setdefault(s, []).append(r["key"])

    for surface, keys in sorted(declared.items()):
        path = SURFACE_FILES.get(surface)
        check(bool(path), "surface %s names a brief file" % surface)
        if not path:
            continue
        found = behavior.slots_in(_read(path))
        for k in keys:
            check(found.count(k) == 1,
                  "%s: rule %s has exactly one slot (found %d)"
                  % (surface, k, found.count(k)))
        for k in set(found):
            rule = behavior.by_key(k)
            check(rule is not None, "%s: slot %s names a real rule" % (surface, k))
            if rule is not None:
                check(surface in behavior.surfaces_of(rule),
                      "%s: rule %s declares this surface" % (surface, k))


def test_byte_identity():
    print("\n[byte identity at defaults]")
    for surface, path in sorted(SURFACE_FILES.items()):
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            check(False, "%s: brief file exists (%s)" % (surface, path))
            continue
        got = _digest(behavior.render(_read(path), surface))
        want = EXPECTED.get(surface) or ""
        if not want:
            check(False, "%s: no pinned hash yet (got %s)" % (surface, got))
            continue
        check(got == want,
              "%s: renders byte-identically to the pinned brief" % surface)


def test_no_marker_survives():
    print("\n[no machinery leaks into a prompt]")
    for surface, path in sorted(SURFACE_FILES.items()):
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            continue
        out = behavior.render(_read(path), surface)
        check("{{rule:" not in out,
              "%s: no unrendered slot marker survives" % surface)
    # And the same through the real loader, which is what a spawn actually gets.
    henry = harness.brief("board-copilot")
    check("{{rule:" not in henry, "harness.brief(board-copilot) renders every slot")
    check(len(henry) > 10000 and "degraded mode" not in henry,
          "harness.brief(board-copilot) is still the real brief")


def test_table_hygiene():
    print("\n[rule table hygiene]")
    seen = set()
    blocks = {b["key"] for b in behavior.BLOCKS}
    for r in behavior.BEHAVIOR_RULES:
        check(r["key"] not in seen, "%s appears once" % r["key"])
        seen.add(r["key"])
        check(r["block"] in blocks, "%s sits in a declared block" % r["key"])
        check(r["kind"] in ("policy", "fixed"), "%s has a known kind" % r["key"])
        check(r.get("scope") in ("workspace", "project"),
              "%s has a known scope" % r["key"])
        check(bool(r.get("why")), "%s carries its why (a lock without a reason "
                                  "reads as arbitrary)" % r["key"])
        check(bool(r.get("source")), "%s names where it lives today" % r["key"])
        check(bool(r.get("labelKey")) and bool(r.get("descKey")),
              "%s has label + one-line description" % r["key"])
        check(bool(r.get("surfaces")), "%s declares at least one surface" % r["key"])
        if r["wire"] == "code":
            check(bool(r.get("reads")),
                  "%s names the code that reads it" % r["key"])
        if r["wire"] == "readonly":
            check(r["kind"] == "fixed",
                  "%s is read-only, so it must be kind fixed" % r["key"])
        for s, spec in (r.get("surfaces") or {}).items():
            ren = spec.get("renders")
            if isinstance(ren, dict):
                check(spec.get("default") in ren,
                      "%s/%s: the default has a rendering" % (r["key"], s))
                if r.get("options"):
                    for o in r["options"]:
                        check(o in ren, "%s/%s: option %s has a rendering"
                              % (r["key"], s, o))


def _dict_src():
    """Every i18n dict file, concatenated. test_harness_layer.py reads them the
    same way for the settings knobs; a rule row is rendered by the same screen
    machinery and had no such check, which is how a rule could ship a labelKey
    that renders as the raw key."""
    d = os.path.join(ROOT, "surfaces", "app", "src", "i18n", "dict")
    if not os.path.isdir(d):
        return ""
    out = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".ts"):
            with io.open(os.path.join(d, f), encoding="utf-8") as fh:
                out.append(fh.read())
    return "\n".join(out)


def test_rules_are_labelled():
    """Every rule's labelKey and descKey exist, IN BOTH LANGUAGES.

    test_table_hygiene above already refuses a rule with no key. This is the
    other half: a key that names no dict entry renders as the raw dotted string
    on the harness screen, and a key with only `de:` renders German at an
    English account - the exact two failures _check_i18n was written for on the
    settings side, arriving here instead because the rule table had no equivalent
    guard. A rule is a knob; it is held to the knobs' contract."""
    print("\n[every rule is labelled, in both languages]")
    src = _dict_src()
    check(bool(src), "the i18n dict files are readable")
    if not src:
        return
    for r in behavior.BEHAVIOR_RULES:
        for kind, key in (("label", r.get("labelKey")), ("description", r.get("descKey"))):
            i = src.find('"%s"' % key)
            check(i >= 0, "%s: %s %s has an i18n entry" % (r["key"], kind, key))
            if i < 0:
                continue
            entry = src[i:i + 400]
            check("de:" in entry and "en:" in entry,
                  "%s: %s %s carries BOTH languages" % (r["key"], kind, key))


def test_allowlist_is_measured():
    """The configure allowlist: what the brief PROMISES and what the server
    ENFORCES must name the same keys.

    This was red by design until 2026-09-02 - `jira` was enforced and unstated -
    and it is now a live guard rather than a report: the two lists agree, so any
    future edit to either one that does not touch the other fails here. Which is
    the property the design doc's 5.5 was really after; generating the paragraph
    from the schema is one way to get it, holding the two equal is another, and
    only the second one keeps the prose descriptions Henry actually reads."""
    print("\n[configure allowlist]")
    keys = behavior.allowlist_keys()
    check(bool(keys), "the allowlist paragraph parses into keys")
    drift = behavior.allowlist_drift()
    check(not drift, "brief allowlist == enforced ALLOWED_CONFIG (%s)"
          % ("; ".join(drift) if drift else "equal"))


def test_cell_references_resolve():
    """Every rule pointing into cells/<id>/ resolves to a REGISTERED cell.

    The rule table's `reads`/`source` entries are string references - the one
    place the cells<->settings seam could rot silently: rename a cell folder and
    every screen grouping rules by cell_of() would quietly file those rules
    under "belongs to no cell". This holds the strings to the registry, so the
    rot becomes a red test instead. And the copilot cell must actually claim
    rules: it is the cell the whole table was written around, so it resolving
    to zero rules means the derivation broke, not the world changed."""
    print("\n[cell references resolve against the registry]")
    from spine.registry import cells
    ids = {c.id for c in cells.CELLS}
    owned = 0
    for r in behavior.BEHAVIOR_RULES:
        cell = behavior.cell_of(r)
        if cell is not None:
            owned += 1
            check(cell in ids, "%s: cell_of names a registered cell (%s)"
                  % (r["key"], cell))
        for ref in (r.get("reads") or "", r.get("source") or ""):
            path = ref.split("::")[0].split(":")[0].strip()
            if not path.startswith("cells/"):
                continue
            cid = path.split("/")[1] if len(path.split("/")) > 1 else ""
            check(cid in ids,
                  "%s: reference %s names a registered cell folder" % (r["key"], ref))
            check(cell == cid,
                  "%s: cell_of agrees with the reference (%s)" % (r["key"], ref))
    check(any(behavior.cell_of(r) == "copilot" for r in behavior.BEHAVIOR_RULES),
          "the copilot cell owns at least one rule (the derivation is alive)")
    print("  (%d of %d rules resolve to a cell)" % (owned, len(behavior.BEHAVIOR_RULES)))


def _print_hashes():
    for surface, path in sorted(SURFACE_FILES.items()):
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            print('    "%s": "",   # MISSING %s' % (surface, path))
            continue
        print('    "%s": "%s",' % (surface, _digest(behavior.render(_read(path), surface))))


if __name__ == "__main__":
    if "--hashes" in sys.argv:
        _print_hashes()
        sys.exit(0)
    test_table_hygiene()
    test_rules_are_labelled()
    test_slot_equality()
    test_no_marker_survives()
    test_byte_identity()
    test_allowlist_is_measured()
    test_cell_references_resolve()
    print("\n%d failure(s)" % len(_fails))
    sys.exit(1 if _fails else 0)
