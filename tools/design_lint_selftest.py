# -*- coding: utf-8 -*-
"""Self-sandboxing test for design_lint against the Expo app (app/) target:
the R4 `lint:hex-ok` / `design-lint-allow` markers, the generated-tokens
exemption, and the R5 zIndex rule.

Writes its own fixture under app/src/ui/, lints it, deletes it - no repo
state is left behind either way (fixture dirs are created on demand and
removed again if this test created them). Run: python tools/design_lint_selftest.py
Exit 0 on pass, 1 on fail."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_lint

p = "app/src/ui/__lint_selftest__.tsx"
full = os.path.join(design_lint.ROOT, p)
fixture_dir = os.path.dirname(full)
made_dirs = not os.path.isdir(fixture_dir)
os.makedirs(fixture_dir, exist_ok=True)

CASES = [
    # (name, source line, expect_violations)
    ("block marker", "const qr = {fg: '#000000', bg: '#ffffff'} /* lint:hex-ok */\n", 0),
    ("trailing //",  '<QR fg="#000000" bg="#ffffff" /> // lint:hex-ok\n', 0),
    ("allow-reason", "// design-lint-allow: QR modules must stay absolute\nconst qr = '#000000'\n", 0),
    ("unmarked",     "const qr = {fg: '#000000'}\n", 1),
    ("other line unmarked", "const a = '#123456' // lint:hex-ok\nconst b = '#654321'\n", 1),
    ("zIndex literal", "const s = {overlay: {zIndex: 9999}}\n", 1),
    ("zIndex semantic", "const s = {overlay: {zIndex: 30}}\n", 0),
]

failures = []
try:
    for name, src, want in CASES:
        with open(full, "w", encoding="utf-8") as f:
            f.write(src)
        got = design_lint.lint([p])
        if len(got) != want:
            failures.append("%s: want %d violation(s), got %r" % (name, want, got))
finally:
    if os.path.exists(full):
        os.remove(full)
    if made_dirs:
        # remove only what we created: the fixture dir, then its parent if empty
        for d in (fixture_dir, os.path.dirname(fixture_dir)):
            try:
                os.rmdir(d)
            except OSError:
                break

# the generated token map is hex by design - it must never be linted
got = design_lint.lint(["app/src/theme/tokens.ts"])
if got:
    failures.append("generated tokens.ts exemption: want 0 violations, got %r" % got)

if failures:
    print("design-lint selftest: FAIL")
    for x in failures:
        print("  -", x)
    sys.exit(1)
print("design-lint selftest: PASS (%d cases)" % (len(CASES) + 1))
