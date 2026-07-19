# -*- coding: utf-8 -*-
"""Distiller: demonstration -> playbook. Feeds the demo's action timeline to a headless
claude run and asks for an editable, agent-executable playbook. The playbook is TEXT the
owner reviews before any agent runs it — that's the safety gate of demonstrate->learn."""
import json, os, subprocess, sys
from actionlog import read_timeline
from runs import REC, load_meta

PROMPT = """You are distilling a human's recorded demonstration into a reusable playbook.

Below is the action timeline of the owner performing a task once on their Windows PC
(clicks with window titles, typed text, key presses, focus changes). Write a playbook
in markdown with EXACTLY these sections:

# Playbook: <short name>
## Goal
One sentence: what this task achieves.
## Preconditions
What must be true/open/logged-in before starting.
## Steps
Numbered steps in imperative form. Generalize: name the UI element and intent
("click the Submit order button in the checkout page"), never raw coordinates.
Mark any step where the human typed a value that would change per run as
`{input: description}`.
## Checkpoints
2-4 observable states that confirm the task is on track / done.
## Never
Anything observed that an agent must NOT do differently (e.g. don't change quantity).

Timeline:
%s
"""

def distill(run_id):
    run_dir = os.path.join(REC, run_id)
    meta = load_meta(run_dir)
    tl = read_timeline(run_dir)
    if not tl:
        raise SystemExit("no actions.jsonl in " + run_dir)
    lines = ["%6.1fs  %-8s %s%s" % (r["t"], r["kind"], r["detail"],
             (' [win: %s]' % r["window"]) if r.get("window") else "")
             for r in tl]
    prompt = PROMPT % "\n".join(lines)
    out = subprocess.run(
        ["claude", "-p", "--model", "sonnet", "--max-turns", "1"],
        input=prompt.encode("utf-8"), capture_output=True, timeout=300, shell=True)
    text = out.stdout.decode("utf-8", "replace").strip()
    if not text:
        raise SystemExit("claude produced nothing: " + out.stderr.decode("utf-8", "replace")[:400])
    path = os.path.join(run_dir, "playbook.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print("playbook written:", path)
    print("review/edit it before letting an agent run it.")
    return path

if __name__ == "__main__":
    distill(sys.argv[1])
