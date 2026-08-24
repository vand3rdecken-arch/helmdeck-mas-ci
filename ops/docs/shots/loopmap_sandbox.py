# -*- coding: utf-8 -*-
"""Throwaway daemon for JUDGING the Loop-Map (CLAUDE.md: a UI change is
screenshotted and judged, never merely confirmed to render).

Same shape as ops/tests/uifix_harness.py but with no seeded board: /loop/map reads
the lane graph, the build loop, the harness surfaces and the laws out of the
CODE, so a card fixture would add nothing and only risk colliding with a live
board on a shared port.

    py -3.12 ops/docs/shots/loopmap_sandbox.py [--port 8852] [--repo-mode]

--repo-mode drops HELMDECK_WORKTREE so loop_state.machine() reports the FULL
seven-state loop (ALIGN..DONE). Without it a card worktree reports card mode and
four of the states never render - and an unrendered row is an unjudged one.

Prints TOKEN=<device token>; the Playwright driver authenticates with it.
Never touches the owner's real files (own users.json/settings.json/db).
"""
import argparse, os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "daemon"))

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8852)
ap.add_argument("--repo-mode", action="store_true")
a = ap.parse_args()

# BEFORE importing loop_state (via server): card_mode() reads the environment.
if a.repo_mode:
    os.environ.pop("HELMDECK_WORKTREE", None)

SANDBOX = os.environ.get("HELMDECK_UI_SANDBOX") or tempfile.mkdtemp(prefix="helmdeck-loopmap-")
os.makedirs(SANDBOX, exist_ok=True)

import auth, db, events

auth.USERS = os.path.join(SANDBOX, "users.json")
auth.SESS = os.path.join(SANDBOX, "sessions.json")
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
db._LEGACY_DB = os.path.join(SANDBOX, "legacy.db")
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")

import copilot, server                                    # noqa: E402

copilot.CHATLOG = os.path.join(SANDBOX, "copilot_log.json")
copilot.SESS = os.path.join(SANDBOX, "copilot_sessions.json")
db.init()

auth.create_user("owner1", "test-pw-12345", "owner")
TOKEN = auth.issue_token("owner1", "ui-judge")

# A RENAMED lane, deliberately: policy.lane_labels is the one thing on the
# pipeline the owner may change, and the screen now offers a rename affordance -
# so the shot must prove a rename actually reaches the track, not just that the
# button exists.
events.save_settings({"policy": {"lane_labels": {"done": "Geliefert"}}})

print("SANDBOX=" + SANDBOX)
print("TOKEN=" + str(TOKEN))
print("MODE=" + ("repo" if a.repo_mode else "card"))
sys.stdout.flush()

threading.Thread(target=lambda: server.serve(a.port), daemon=True).start()
while True:
    time.sleep(1)
