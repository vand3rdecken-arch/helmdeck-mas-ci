# -*- coding: utf-8 -*-
"""Henry's brief is split into an always-loaded CORE and on-demand sections
(card chat-henry-kontext-pruning part 2, 2026-09-15; the memory pattern:
index always, full text on request). Measured with ops/tools/henry_base_probe.py:
fixed base 58,763 -> 55,840 tokens, rendered brief 36.8k -> 28.4k chars.

What must not drift: every section the core's AUF ABRUF index names exists
as a file the tool can serve; no section carries a {{rule:...}} slot (the
tool prints raw text, only harness.brief renders slots); the core still
carries every slot-bearing law that was deliberately kept.

    py -3.12 ops/tests/test_brief_sections.py
"""
import os
import re
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
CORE = os.path.join(ROOT, "cells", "copilot", "harness", "agents", "board-copilot.md")
SECTIONS = os.path.join(ROOT, "cells", "copilot", "harness", "agents", "board-copilot.d")
TOOL = os.path.join(ROOT, "ops", "tools", "henry_brief_get.py")
fails = []


def ok(cond, what):
    print(("  ok    " if cond else "  FAIL  ") + what)
    if not cond:
        fails.append(what)


print("brief sections")
core = open(CORE, encoding="utf-8").read()
idx = re.search(r"AUF ABRUF.*?\n\n", core, re.S).group(0)
named = re.findall(r"^  ([a-z]+) +- ", idx, re.M)
ok(set(named) == {"actions", "pipeline", "grillen", "planning", "ops"},
   "the core's index names exactly the five sections: %s" % named)
files = {fn[:-3] for fn in os.listdir(SECTIONS) if fn.endswith(".md")}
ok(files == set(named), "every indexed section is a file and every file is indexed (%s)" % sorted(files))
for n in sorted(files):
    txt = open(os.path.join(SECTIONS, n + ".md"), encoding="utf-8").read()
    ok("{{rule:" not in txt, "%s carries no {{rule:}} slot (the tool prints raw text)" % n)
    r = subprocess.run([sys.executable, TOOL, "get", n], capture_output=True, text=True, encoding="utf-8")
    ok(r.returncode == 0 and r.stdout.strip() == txt.strip(), "henry_brief_get.py get %s serves the file verbatim" % n)
r = subprocess.run([sys.executable, TOOL, "get", "../board-copilot"], capture_output=True, text=True, encoding="utf-8")
ok(r.returncode != 0, "a path-shaped name is refused (no traversal)")
for slot in ("report.followup_interval", "initiative.repo_default", "hands.configure_allowlist",
             "hands.protected_files", "initiative.stale_check", "tone.house_rules", "memory.enabled"):
    ok("{{rule:%s}}" % slot in core, "core still carries the slot-bearing law %s" % slot)
ok("henry_brief_get.py get <name>" in core, "core tells Henry the exact pre-approved command form")
ok(len(core) < 30_000, "core brief stays under 30k chars (was 34.8k before the split; now %d)" % len(core))

print("\n" + ("FAIL (%d)" % len(fails) if fails else "brief-sections: all pinned - PASS"))
sys.exit(1 if fails else 0)
