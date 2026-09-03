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
    "pm": "ops/harness/agents/board-copilot.md",
    "voice": "ops/harness/agents/voice-style.md",
    "wear": "ops/harness/agents/wear-brief.md",
    "glass": "ops/harness/agents/glass-brief.md",
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
EXPECTED = {
    "pm": "e329ebfc1c7694909e8b174a06809cb269a5f8a2551db063c34743dbe97f2e94",
    "voice": "5cf6585d188be12914b8e5177313669c7f360b6426d86c4994f2ed6d25b408bd",
    "wear": "c8c3090b5de4cba354c957c5772d277af317b46330087f1d27932a9342cac8c8",
    "glass": "2ae3eaa11f2e60dd55e0e78dce277eaeb344fcc34b35ffa64c595e0cd703c628",
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
    print("\n%d failure(s)" % len(_fails))
    sys.exit(1 if _fails else 0)
