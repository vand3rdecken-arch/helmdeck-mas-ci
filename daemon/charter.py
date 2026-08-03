# -*- coding: utf-8 -*-
"""The capability charter - what this program may be extended to do.

Users can BUILD things (connectors, templates, policy), but only things that
fit the program's purpose. The charter is enforced three times:
  1. commission time - the copilot refuses off-charter build requests
  2. install time    - screen_source() rejects code using capabilities a
                       connector has no business having (this file)
  3. run time        - the sandbox (separate process, timeout, JSON-only)

The CORE charter is code - not configurable, not chat-editable. Owners may
ADD house rules (further restrictions) via policy.house_rules; nobody can
subtract from the core."""
import re

CHARTER = """HelmDeck workspace charter - what may be built here:

MAY BE BUILT (by anyone with build access, through card + gate + accept):
- CONNECTORS: read data from external systems and propose backlog cards.
  Read-only toward the world, create-only toward the board. Stdlib only.
- TEMPLATES: views chosen from the reviewed catalog, driven by declared data.
- POLICY: workflow configuration within the settings whitelist.

MAY NEVER BE BUILT (core, non-negotiable):
- anything that edits, deletes or accepts existing work items or history
- anything touching auth, users, roles, tokens, or the audit/event log
- anything executing shell commands, spawning processes, or loading native code
- anything writing files outside its own connector module
- anything reading local files, environment secrets, or daemon internals
- UI code (interfaces render from templates + data, never from built code)
- new drivers or changes to what drivers execute"""

# install-time screening: capabilities a connector must not use.
FORBIDDEN = [
    (r"\bsubprocess\b", "spawning processes"),
    (r"\bos\.system\b|\bos\.popen\b|\bos\.exec", "shell execution"),
    (r"\bos\.remove\b|\bos\.unlink\b|\bos\.rmdir\b|\brmtree\b", "deleting files"),
    (r"\bshutil\b", "filesystem manipulation"),
    (r"\beval\s*\(|\bexec\s*\(|__import__", "dynamic code execution"),
    (r"\bctypes\b|\bcffi\b", "native code"),
    (r"\bsocket\b", "raw sockets (use urllib for http)"),
    (r"\bopen\s*\([^)]*['\"][wa]", "writing files"),
    (r"\bimport\s+(sessions|events|auth|copilot|connectors|checkpoints|server|processes)\b",
     "reaching into daemon internals"),
    (r"os\.environ", "reading environment secrets"),
]

def screen_source(code):
    """Return list of (pattern-reason) violations; empty = charter-clean."""
    hits = []
    for pat, reason in FORBIDDEN:
        if re.search(pat, code):
            hits.append(reason)
    return hits
