# -*- coding: utf-8 -*-
"""Headless test for PROJECT SHARING (a shared room's project folders).

A project shared with an account shows that account its cards as the SUMMARY
view and nothing else. Through the real route handlers and the real db:

 1. Not shared: the guest's /projects/shared is empty and she does not see the cards.
 2. Shared: she lists the project, its cards come back as the whitelist (no repo
    path, worktree, session, cost) and sees_card is true for them.
 3. A card of ANOTHER project stays hidden; a card does not become hers (owns_card).
 4. Unshare takes effect on the next request (derived from the record).
 5. The owner's view lists every project with its share list; unknown accounts refused.

Self-sandboxing: temp DB, no network. Run: py -3.12 ops/tests/test_project_sharing.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-pshare-")

from spine.storage import db
db.ROOT = SANDBOX
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.auth import auth
from spine.ops import projects
from spine.http.routes import routes_projects

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


PW = "Correct-Horse-Battery-9"
for n, r in (("tien", "owner"), ("guest", "operator")):
    auth.create_user(n, PW, r, actor="test")
OWNER = {"name": "tien", "role": "owner"}
GUEST = {"name": "guest", "role": "operator"}

REPO_A = os.path.join(SANDBOX, "immobilien")
REPO_B = os.path.join(SANDBOX, "privat")
pa = projects.sight_repo(REPO_A, name="Immobilien")
pb = projects.sight_repo(REPO_B, name="Privat")

from spine.storage.trackstore import _save_track


def card(cid, repo):
    t = {"id": cid, "dispatched_by": "tien", "task": "Aufgabe " + cid, "lane": "working",
         "status": "idle", "client": "", "repo": repo, "worktree": "C:/wt/" + cid,
         "run_dir": "C:/rec/" + cid, "session_id": "sess-" + cid, "ai_cost": 12.5,
         "last_reply": "Ergebnis " + cid, "created": "2026-10-09 10:00:00",
         "updated": "2026-10-09 10:00:00"}
    _save_track(t)
    return t


ca = card("immo1", projects.norm_repo(REPO_A))
cb = card("privat1", projects.norm_repo(REPO_B))


class Req(object):
    path = "/projects/shared"

    def __init__(self):
        self.sent = None

    def _send(self, status, body, *a):
        self.sent = (status, json.loads(body))


def shared_get(user):
    r = Req()
    routes_projects.projects_shared_get(r, user)
    return r.sent[1]


check(shared_get(GUEST) == [], "1. nothing shared: the guest's project list is empty")
check(not auth.sees_card(GUEST, ca), "1. nothing shared: the card is not visible")

projects.share(pa["id"], add=["guest"], actor="tien")
got = shared_get(GUEST)
check([p["name"] for p in got] == ["Immobilien"], "2. shared: only the shared project is listed")
cards = got[0]["cards"] if got else []
check([c["id"] for c in cards] == ["immo1"], "2. shared: its card is listed")
leak = [k for k in ("repo", "worktree", "run_dir", "session_id", "ai_cost") if cards and k in cards[0]]
check(not leak, "2. the card is the whitelisted summary (leaked: %s)" % leak)
check(cards and cards[0].get("summary") is True and cards[0].get("last_reply") == "Ergebnis immo1",
      "2. summary flag and result are there")
check("repo" not in got[0], "2. the project itself carries no repo path")
check(auth.sees_card(GUEST, ca), "2. sees_card is true for a card of the shared project")

check(not auth.sees_card(GUEST, cb), "3. a card of another project stays hidden")
check(not auth.owns_card(GUEST, ca), "3. seeing is not owning (no steering, no transcript)")

projects.share(pa["id"], remove=["guest"], actor="tien")
check(shared_get(GUEST) == [] and not auth.sees_card(GUEST, ca),
      "4. unshare takes effect on the next request")

try:
    projects.share(pa["id"], add=["niemand"])
    check(False, "5. unknown account refused")
except ValueError:
    check(True, "5. unknown account refused")
check(projects.share("gibts-nicht", add=["guest"]) is None, "5. unknown project -> None")
projects.share(pb["id"], add=["guest"], actor="tien")
own = shared_get(OWNER)
check({p["name"] for p in own} == {"Immobilien", "Privat"}, "5. the owner sees every project")
check([p["geteilt_mit"] for p in own if p["name"] == "Privat"] == [["guest"]],
      "5. the owner's list carries the share list")

# 6. a folder becomes a project through the one door (sight_repo), and only if it exists
class Post(object):
    def __init__(self):
        self.sent = None

    def _send(self, status, body, *a):
        self.sent = (status, json.loads(body))


folder = os.path.join(SANDBOX, "Aktien")
os.makedirs(folder)
r = Post()
routes_projects.projects_folder_post(r, OWNER, {"path": folder, "name": "Aktien"})
check(r.sent[0] == 200 and r.sent[1]["name"] == "Aktien", "6. an existing folder is registered as a project")
r = Post()
routes_projects.projects_folder_post(r, OWNER, {"path": folder, "name": "Zweitname"})
check(r.sent[0] == 200 and r.sent[1]["name"] == "Aktien", "6. the same folder again returns the existing project")
r = Post()
routes_projects.projects_folder_post(r, OWNER, {"path": os.path.join(SANDBOX, "gibts-nicht")})
check(r.sent[0] == 400, "6. a missing folder is refused")

# 7. the folder picker's read: sub-folder NAMES only, no files, no hidden, parent given
root = os.path.join(SANDBOX, "browse")
for d in ("Immobilien", "aktien", ".versteckt"):
    os.makedirs(os.path.join(root, d))
open(os.path.join(root, "datei.txt"), "w").close()


class Get(object):
    def __init__(self, path):
        self.path = "/projects/browse?path=" + root_q(path)
        self.sent = None

    def _send(self, status, body, *a):
        self.sent = (status, json.loads(body))


def root_q(p):
    from urllib.parse import quote
    return quote(p)


g = Get(root)
routes_projects.projects_browse_get(g, OWNER)
check(g.sent[1]["dirs"] == ["aktien", "Immobilien"], "7. browse lists folders only, sorted, no files, no hidden")
check(g.sent[1]["parent"] == SANDBOX, "7. browse names the parent folder")
g = Get(os.path.join(root, "gibts-nicht"))
routes_projects.projects_browse_get(g, OWNER)
check(g.sent[1].get("error") and g.sent[1]["dirs"] == [], "7. a missing folder answers an error, not a crash")
check(routes_projects.POST_CAPS.get("/projects/folder") == "projects.manage"
      and routes_projects.GET_CAPS.get("/projects/browse") == "projects.manage",
      "7. browsing and registering a folder need projects.manage (owner)")

print()
print("FAILED: %d" % len(_fails) if _fails else "ALL PASS")
sys.exit(1 if _fails else 0)
