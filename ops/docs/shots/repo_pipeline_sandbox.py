# -*- coding: utf-8 -*-
"""Throwaway daemon for JUDGING the repo pipeline + type picker.

CLAUDE.md: a UI change is screenshotted and JUDGED, never merely confirmed to
render. This serves the real payload out of the real code (/loop/map?repo=,
/repo/templates), so what gets judged is what the daemon actually says.

Replaces ops/docs/shots/loopmap_sandbox.py's setup, which still imported the
pre-split flat layout (`import auth, db, events`) and had been dead since the
four-folder move - the camera for this screen did not work.

Two repos are seeded ON PURPOSE, with the two different types:
  code-repo  software-dev - all five stations, deploy with a real command
  text-repo  documents    - no deploy, and a gate labelled "runs empty"
A one-repo fixture would have shown a pipeline that looks the same either way,
which is exactly the thing this screen exists to make visible.

    py -3.12 ops/docs/shots/repo_pipeline_sandbox.py [--port 8869]

Prints TOKEN=<device token>; the Playwright driver authenticates with it.
Never touches the owner's real files (own users.json/settings.json/db/events).
"""
import argparse
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))          # ops/docs/shots
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8869)
ap.add_argument("--repo-mode", action="store_true",
                help="drop HELMDECK_WORKTREE so the build loop reports all seven states")
a = ap.parse_args()

if a.repo_mode:
    os.environ.pop("HELMDECK_WORKTREE", None)

SANDBOX = os.environ.get("HELMDECK_UI_SANDBOX") or tempfile.mkdtemp(prefix="helmdeck-pipeline-")
os.makedirs(SANDBOX, exist_ok=True)

# EVERY store, redirected BEFORE anything touches disk. The traps are the ones
# test_server_routes.py paid for: events.EV and db.ROOT are independent globals,
# and a module that did `from runs import REC` holds its own bound copy.
from spine.auth import auth, policy                                # noqa: E402
from spine.storage import db, events                               # noqa: E402

auth.USERS = os.path.join(SANDBOX, "users.json")
auth.SESS = os.path.join(SANDBOX, "sessions.json")
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
db._LEGACY_DB = os.path.join(SANDBOX, "legacy.db")
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
policy.LIVE = os.path.join(SANDBOX, "policy_live.json")

from spine.ops import runs                                          # noqa: E402
REC = os.path.join(SANDBOX, "recordings")
os.makedirs(REC, exist_ok=True)
runs.REC = REC

for _p in (db.DBPATH, events.SET, events.EV, auth.USERS):
    assert os.path.dirname(os.path.abspath(_p)) == os.path.abspath(SANDBOX), \
        "sandbox failed - refusing to run against %s" % _p

db.init(role="tool")

from spine.ops import projects                                      # noqa: E402

CODE = os.path.join(SANDBOX, "code-repo")
TEXT = os.path.join(SANDBOX, "text-repo")
os.makedirs(CODE, exist_ok=True)
os.makedirs(TEXT, exist_ok=True)

projects.apply_template(CODE, "software-dev", actor="owner1")
projects.apply_template(TEXT, "documents", actor="owner1")

# A real deploy command on the code repo: without one the deploy station is
# honestly OFF, and then no shot in the set would ever show it switched ON.
_h = dict(events.settings().get("repo_hooks") or {})
_h.setdefault(projects.norm_repo(CODE), {})["deploy"] = "bash ops/deploy/push_update.sh"
events.save_settings({"repo_hooks": _h}, actor="owner1", reason="ui-judge fixture")

# A DEVIATION on the text repo, deliberately: "vom Standard abgewichen" is the
# banner the PRD asked for and an unrendered banner is an unjudged one.
events.save_settings({"policy": dict(events.settings().get("policy") or {},
                                     auto_accept_green=True)},
                     actor="owner1", reason="ui-judge fixture")
projects.set_override(TEXT, "policy.auto_accept_green", True, actor="owner1")

auth.create_user("owner1", "test-pw-12345", "owner")
TOKEN = auth.issue_token("owner1", "ui-judge")

from spine.http import server                                       # noqa: E402

httpd = server.ThreadingHTTPServer(("127.0.0.1", a.port), server.H)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

print("SANDBOX=%s" % SANDBOX, flush=True)
print("CODE_REPO=%s" % projects.norm_repo(CODE), flush=True)
print("TEXT_REPO=%s" % projects.norm_repo(TEXT), flush=True)
print("PORT=%d" % a.port, flush=True)
print("TOKEN=%s" % TOKEN, flush=True)
print("READY", flush=True)

try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    pass
