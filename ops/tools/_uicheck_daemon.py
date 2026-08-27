# -*- coding: utf-8 -*-
"""Throwaway isolated daemon for a one-off UI screenshot check (GxP picker,
ops/docs/backlog/rbac-gxp). Same sandboxing pattern as ops/tests/*.py - own
tempdir for db/users/settings/policy/gxp-lock, own port - never touches the
real daemon/users.json or daemon/policy_live.json. Delete this file when the
check is done; it is not a real tool, just a scratch harness.

Run: py -3.12 ops/tools/_uicheck_daemon.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

tmp = tempfile.mkdtemp(prefix="helmdeck-uicheck-")
print("sandbox:", tmp)

from spine.storage import db
db.ROOT = tmp
db.DBPATH = os.path.join(tmp, "test.db")
from spine.auth import auth
auth.USERS = os.path.join(tmp, "users.json")
auth.SESS = os.path.join(tmp, "sessions.json")
from spine.storage import events
events.EV = os.path.join(tmp, "events.jsonl")
events.SET = os.path.join(tmp, "settings.json")
from spine.auth import policy
policy.LIVE = os.path.join(tmp, "policy_live.json")
from spine.auth import gxp
gxp.LOCK = os.path.join(tmp, "gxp.lock")
db.init(role="tool")

auth.create_user("uicheck", "uicheck-pw-12345", "owner")
print("test owner: uicheck / uicheck-pw-12345")

# a second, real-ish repo entry so the "known repos" picker has something to
# show without needing a "create new" round trip first.
events.save_settings({"pm": {"repos": [os.path.join(tmp, "sample-repo")]}}, actor="uicheck")

from spine.http import server
httpd = server.ThreadingHTTPServer(("127.0.0.1", 8199), server.H)
print("serving on http://127.0.0.1:8199")
httpd.serve_forever()
