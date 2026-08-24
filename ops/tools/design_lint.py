# -*- coding: utf-8 -*-
"""Deterministic design lint - the enforceable subset of the design skill.

A skill is advisory: the model can read it and still ship slop, or skip it
entirely (as happened). Taste can't be forced. But the MECHANICAL rules a
good skill encodes ARE checkable, and every rule below is a real bug that
slipped past visual review in this repo. Wired into the loop's EXECUTE state,
these gate the commit: the loop stays red until they pass, regardless of
whether the skill was read. That converts 'please use the skill' (hope) into
'the output must satisfy these' (code).

Repointed at the Expo app (app/) when web/ (Next.js) was archived: the design
system is surfaces/app/src/theme/tokens.ts consumed via useTheme(), and the only global
web CSS left is the template string in surfaces/app/src/ui/webstyles.tsx. The web-only
rules (root color-scheme, <select> option styling) now read THAT css; the
hex/zIndex token rules apply to the app's .ts/.tsx sources.

Never crashes (returns [] on error) - it's a checker, not a gate itself."""
import os, re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = os.path.join(ROOT, "app")
WEBSTYLES = os.path.join(APP, "src", "ui", "webstyles.tsx")
# generated token map - hex IS the point there (see ops/tools/gen_tokens.py)
GENERATED = ("surfaces/app/src/theme/tokens.ts",)


def _read(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def lint(touched):
    """Return list of violation strings for the touched Expo-app files."""
    problems = []
    app_touched = [p.replace("\\", "/") for p in touched]
    app_touched = [p for p in app_touched if p.startswith("app/") and
                   (p.endswith(".tsx") or p.endswith(".ts")) and
                   p not in GENERATED]
    if not app_touched:
        return []
    # webstyles.tsx is a .tsx whose file comments may NAME the rules below -
    # strip // lines so only the actual CSS template string is judged.
    css = "\n".join(l for l in _read(WEBSTYLES).splitlines()
                    if not l.strip().startswith("//"))

    # R1: the web shell paints its own canvas but never declares color-scheme
    #     -> native popups (selects, date pickers) and scrollbars render in the
    #     browser's default scheme, not ours. The archived web app carried this
    #     exact rule at :root (globals.css); the Expo web shell needs it in the
    #     injected CSS. (the native-popup bug)
    if css and "background" in css and "color-scheme" not in css:
        problems.append("webstyles.tsx: the web shell sets a themed canvas but "
                        "declares no `color-scheme` - native select/date popups "
                        "and scrollbars render in the wrong scheme. (native-popup bug)")

    # R3: a raw DOM <select> on the web build with unstyled popup options -
    #     the open list won't follow the theme. (RN pickers are fine; this
    #     only fires for react-native-web escape hatches.)
    uses_select = any("<select" in _read(os.path.join(ROOT, p))
                      for p in app_touched if p.endswith(".tsx"))
    if uses_select and "select option" not in css:
        problems.append("a raw <select> is used but webstyles.tsx has no "
                        "`select option` styling - the open list won't follow "
                        "the theme.")

    for p in app_touched:
        src = _read(os.path.join(ROOT, p))

        # R4: hardcoded colors in component code (tokens exist for a reason:
        #     surfaces/app/src/theme/tokens.ts via useTheme()). A line may opt out with
        #     a `lint:hex-ok` marker, or `design-lint-allow: <reason>` on the
        #     same or preceding line, for literals that MUST stay
        #     device-absolute (e.g. QR fg/bg black/white to scan).
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
            prev_start = src.rfind("\n", 0, max(line_start - 1, 0)) + 1
            window = src[prev_start:(line_end if line_end != -1 else len(src))]
            if re.search(r'design-lint-allow:\s*\S', window):
                continue
            problems.append("%s: hardcoded color %s - use a theme token "
                            "(useTheme() / tokens.ts), not a literal hex "
                            "(intentional literals: annotate the line with "
                            "`lint:hex-ok`)." % (p, m.group(0)))
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
