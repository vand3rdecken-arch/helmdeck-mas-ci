# -*- coding: utf-8 -*-
"""Deterministic design lint - the enforceable subset of the design skill.

A skill is advisory: the model can read it and still ship slop, or skip it
entirely (as happened). Taste can't be forced. But the MECHANICAL rules a
good skill encodes ARE checkable, and every rule below is a real bug that
slipped past visual review in this repo. Wired into the loop's EXECUTE state,
these gate the commit: the loop stays red until they pass, regardless of
whether the skill was read. That converts 'please use the skill' (hope) into
'the output must satisfy these' (code).

Never crashes (returns [] on error) - it's a checker, not a gate itself."""
import os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
GLOBALS = os.path.join(WEB, "app", "globals.css")


def _read(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def lint(touched):
    """Return list of violation strings for the touched web files."""
    problems = []
    web_touched = [p for p in touched if p.startswith("web/") and
                   (p.endswith(".tsx") or p.endswith(".css"))]
    if not web_touched:
        return []
    css = _read(GLOBALS)

    # R1: dark theme exists but color-scheme never declared AT ROOT -> native
    #     popups (selects, date pickers) render in the wrong scheme. Must be on
    #     :root/html/body/[data-theme], not just any element. (the dropdown bug)
    root_scheme = re.search(
        r'(:root|html|body|\[data-theme[^\]]*\])[^{]*\{[^}]*color-scheme', css)
    if '[data-theme="dark"]' in css and not root_scheme:
        problems.append("globals.css: dark theme without a ROOT `color-scheme` "
                        "declaration - native select/date popups render light. (native-popup bug)")

    # R3: <select> used anywhere but its popup options are unstyled
    uses_select = any("<select" in _read(os.path.join(ROOT, p))
                      for p in web_touched if p.endswith(".tsx"))
    if uses_select and "select option" not in css and \
       "[data-theme=\"dark\"]" in css:
        problems.append("a <select> is used but globals.css has no `select option` "
                        "styling - the open list won't follow the theme.")

    for p in web_touched:
        if not p.endswith(".tsx"):
            continue
        src = _read(os.path.join(ROOT, p))

        # R2: inline width/height on a themed control collapses it. (checkbox +
        #     peek bugs - twice). Flag style={{...width/height...}} on inputs.
        for m in re.finditer(r'<(input|select|textarea)\b[^>]*style=\{\{([^}]*)\}\}', src):
            style = m.group(2)
            if re.search(r'\b(width|height)\s*:', style) and "auto" in style:
                problems.append("%s: inline width/height:auto on <%s> defeats the "
                                "custom-control CSS (collapses)." % (p, m.group(1)))

        # R4: hardcoded colors in component code (tokens exist for a reason).
        #     Allow in globals.css (the token definitions live there). A line
        #     may opt out with a `lint:hex-ok` marker for literals that MUST
        #     stay device-absolute (e.g. QR fg/bg black/white to scan).
        for m in re.finditer(r'#[0-9a-fA-F]{6}\b', src):
            line_start = src.rfind("\n", 0, m.start()) + 1
            line_end = src.find("\n", m.end())
            full_line = src[line_start:line_end if line_end != -1 else len(src)]
            if "lint:hex-ok" in full_line:
                continue
            # skip if inside a comment line
            line = src[line_start:m.start()]
            if "//" in line or "/*" in line:
                continue
            # Auditable escape hatch: a literal that is NOT a themeable UI color
            # (e.g. a QR code's black/white modules, a canvas pixel) may opt out
            # with `design-lint-allow: <reason>` on the same or preceding line.
            # The reason is required so the exception stays honest and greppable.
            # (`lint:hex-ok` above is the terse variant for the same intent.)
            prev_start = src.rfind("\n", 0, max(line_start - 1, 0)) + 1
            window = src[prev_start:(line_end if line_end != -1 else len(src))]
            if re.search(r'design-lint-allow:\s*\S', window):
                continue
            problems.append("%s: hardcoded color %s - use a design token "
                            "(var(--...)), not a literal hex (intentional "
                            "literals: annotate the line with `lint:hex-ok`)."
                            % (p, m.group(0)))
            break   # one flag per file is enough signal

        # R5: arbitrary high z-index literal (no semantic scale).
        for m in re.finditer(r'zIndex:\s*(\d+)', src):
            if int(m.group(1)) > 100:
                problems.append("%s: arbitrary zIndex %s - use the semantic "
                                "z-scale, not 999/9999-style literals." % (p, m.group(1)))
                break

    # de-dup, cap
    seen, out = set(), []
    for x in problems:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out[:8]


if __name__ == "__main__":
    import subprocess
    r = subprocess.run(["git", "-C", ROOT, "status", "--porcelain"],
                       capture_output=True, text=True)
    touched = [l[3:].strip().strip('"') for l in r.stdout.splitlines() if len(l) > 3]
    v = lint(touched)
    if not v:
        print("design-lint: clean")
    else:
        print("design-lint: %d issue(s)" % len(v))
        for x in v:
            print("  -", x)
