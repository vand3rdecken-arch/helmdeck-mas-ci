# -*- coding: utf-8 -*-
"""Pre-commit guard: nothing from the owner's private life enters the HelmDeck repo.

Measured 2026-10-18: the owner's real holdings and depot size, family members as account names and a
first name sat in test fixtures, and a private side project (landing page, ad plan, worker code)
was committed under ops/docs/ and ops/deploy/ - agents that know the owner's notes wrote them into the
product repo. The publish filter only redacted them on the way to the public mirror; nothing stopped them
from being written in the first place. This does.

The rules are the owner's own private list, ~/.helmdeck/publish_private.txt - the SAME file the mirror
filter reads, so one list governs both (it lives outside the repo: what is private is itself private):
  path:<repo path>   no staged file may live under it
  <regex>            no ADDED line may match it (case-insensitive)

Wired through the global hooks dir (core.hooksPath = ~/.githooks/pre-commit), which runs this only in a
checkout that has it - the HelmDeck repo and its card worktrees, never the owner's other projects (a
portfolio repo is exactly where holdings belong).

    python ops/tools/private_guard.py            # what the hook runs: checks the staged diff
    python ops/tools/private_guard.py --install  # writes the delegating ~/.githooks/pre-commit

There is no bypass flag on purpose: an agent must not be able to talk its way past it. The owner changes
the list, or moves the content to the project it belongs to.
"""
import os
import re
import subprocess
import sys

PRIVATE_LIST = os.path.join(os.path.expanduser("~"), ".helmdeck", "publish_private.txt")
HOOK = os.path.join(os.path.expanduser("~"), ".githooks", "pre-commit")


def load_rules(path=PRIVATE_LIST):
    paths, terms = [], []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("path:"):
                    paths.append(line[5:].strip().replace("\\", "/").rstrip("/"))
                else:
                    terms.append(re.compile(line, re.I))
    except OSError:
        pass
    return paths, terms


def check(diff_text, staged_files, rules):
    """Violations as (file, line_no, what) for a unified diff (-U0) and the staged file list."""
    paths, terms = rules
    out = []
    for f in staged_files:
        f2 = f.replace("\\", "/")
        for p in paths:
            if f2 == p or f2.startswith(p + "/"):
                out.append((f, 0, "path is on the private list (%s)" % p))
    cur, line_no = None, 0
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            cur = line[6:] if line.startswith("+++ b/") else None
            continue
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", line)
        if m:
            line_no = int(m.group(1))
            continue
        if cur and line.startswith("+"):
            for rx in terms:
                if rx.search(line[1:]):
                    out.append((cur, line_no, "matches a private term (%s)" % rx.pattern))
            line_no += 1
    return out


def install():
    os.makedirs(os.path.dirname(HOOK), exist_ok=True)
    if os.path.exists(HOOK) and "private_guard.py" not in open(HOOK, encoding="utf-8", errors="replace").read():
        sys.exit("%s exists and is not ours - add the delegation by hand" % HOOK)
    with open(HOOK, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/sh\n"
                "# Global pre-commit: delegates to a repo's own private guard if it has one (HelmDeck).\n"
                "top=\"$(git rev-parse --show-toplevel)\"\n"
                "[ -f \"$top/ops/tools/private_guard.py\" ] || exit 0\n"
                "for py in python python3 py; do\n"
                "  command -v \"$py\" >/dev/null 2>&1 && exec \"$py\" \"$top/ops/tools/private_guard.py\"\n"
                "done\n"
                "echo 'private_guard: no python found - refusing to commit unchecked' >&2; exit 1\n")
    print("installed", HOOK)


def main():
    if "--install" in sys.argv:
        return install()
    rules = load_rules()
    if not (rules[0] or rules[1]):
        return 0
    diff = subprocess.run(["git", "diff", "--cached", "-U0", "--no-color", "--text"], capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout
    files = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace").stdout.split("\n")
    bad = check(diff, [f for f in files if f], rules)
    if bad:
        sys.stderr.write("COMMIT REFUSED - private content in the HelmDeck repo (ops/tools/private_guard.py):\n")
        for f, n, why in bad[:30]:
            sys.stderr.write("  %s%s: %s\n" % (f, (":%d" % n) if n else "", why))
        sys.stderr.write("Private data belongs in the db (notes) or in its own project folder, not in this repo.\n"
                         "Test data: use made-up values. The rules: %s\n" % PRIVATE_LIST)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
