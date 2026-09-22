# -*- coding: utf-8 -*-
"""Deleting a PROJECT: the verb that was missing, and the delete that sticks.

The incident, 2026-09-20 04:01. Owner: "Lösch das project relevance feed."
Henry deleted the cards (he had a verb for that), removed the folder and the
Cloudflare page through hands, and reported "vollständig weg". The project row
survived, and two days later a full-screen onboarding step was still asking
the owner to give that project a type.

Owner's own diagnosis, and it is the right one: the problem was not a missing
tool, it was an ADJACENT tool. Paseo names the object in every verb
(archive_agent beside archive_workspace); six of our thirty carry no object at
all, and `delete` reads as universal.

Then, fixing it, a second defect: a bare project delete came BACK in the same
second under a new id, because sight_repo() saw a live card still carrying the
repo. A delete that ignores its references is a pause, not a delete.

Self-sandboxing: temp db throughout.
Run: py -3.12 ops/tests/test_delete_project.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_tmp = tempfile.mkdtemp(prefix="del_project_test_")
from spine.storage import db                                      # noqa: E402
db.ROOT = _tmp
db.DBPATH = os.path.join(_tmp, "test.db")
db.init()
from spine.ops import projects                                    # noqa: E402
from cells.copilot.chat import copilot_actions as ca              # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


REPO = os.path.join(_tmp, "repo-x")
os.makedirs(REPO, exist_ok=True)

print("\n[the verb exists at all]")
check("delete_project" in ca.ACTION_KINDS,
      "Henry has a verb for deleting a project")
check({"delete_card", "archive_card", "move_card"} <= set(ca.ACTION_KINDS),
      "and the card verbs have explicit-object names beside the bare ones")

p = projects.new_project("proj-x", "fixed", fixed_price=0.0, repo=REPO)
pid = p["id"]

print("\n[a card verb pointed at a PROJECT refuses, by name]")
msg = ca._project_not_card(pid)
check(bool(msg), "the guard fires on a project id")
check("PROJEKT" in (msg or "") and "delete_project" in (msg or ""),
      "it says what the id IS and names the right verb - got %r" % (msg or "")[:90])
check(ca._project_not_card("20260101-000000-not-a-project") is None,
      "and it stays out of the way for a real card id")

print("\n[the delete REFUSES while something can resurrect the project]")
_run = os.path.join(_tmp, "run-card-1")
os.makedirs(_run, exist_ok=True)
db.track_put({"id": "card-1", "repo": REPO, "branch": "b1", "lane": "working",
              # a real card always carries run_dir; archive_track logs into it
              "run_dir": _run})
try:
    projects.delete_project(pid, actor="owner")
    check(False, "a project with a live card must not delete silently")
except RuntimeError as e:
    check("1 aktiven Karte" in str(e) or "1 aktiven Karte(n)" in str(e),
          "it counts what is holding the project alive - got %r" % str(e)[:110])
    check("card-1" in str(e), "and names it")
check(db.project_get(pid) is not None, "nothing was deleted on the refusal")

print("\n[with archive_cards it sticks - and archives, never destroys]")
r = projects.delete_project(pid, actor="owner", archive_cards=True)
check(r["deleted"] == pid, "the project is gone")
check(r["archived_cards"] == ["card-1"], "the card was archived, by name - got %r"
      % (r["archived_cards"],))
check(db.project_get(pid) is None, "and it stays gone")
_t = [t for t in (db.tracks_all() or []) if t.get("id") == "card-1"]
check(_t and _t[0].get("archived"),
      "the card still EXISTS, archived - work is never destroyed for a cleanup")


print("%s[the REGISTRATION goes too, or the project comes straight back]" % (chr(10),))
# The actual cause, found on the third attempt. adopt_settings_repos() sights
# every path in pm.repos / repo_hooks / default_roject whenever a surface that
# needs the repo list opens. A path left in the settings recreated the project
# within seconds, three times, with no error anywhere - the record is
# DOWNSTREAM of the registration.
from spine.storage import events                                  # noqa: E402

REPO2 = os.path.join(_tmp, "repo-y")
os.makedirs(REPO2, exist_ok=True)
events.save_settings({"repo_hooks": {REPO2: {"on": True}},
                      "pm": {"repos": [REPO2]}}, actor="test")
p2 = projects.new_project("proj-y", "fixed", fixed_price=0.0, repo=REPO2)
r2 = projects.delete_project(p2["id"], actor="owner")
check(sorted(r2.get("unregistered") or []) == ["pm.repos", "repo_hooks"],
      "the delete reports which lists it removed the repo from - got %r"
      % (r2.get("unregistered"),))
s = events.settings()
check(REPO2 not in (s.get("repo_hooks") or {}),
      "repo_hooks really lost the key - save_settings MERGES, so omitting it "
      "is a no-op and reported a removal that never happened")
check(REPO2 not in ((s.get("pm") or {}).get("repos") or []),
      "and pm.repos too")
check(projects.adopt_settings_repos(actor="test") == [],
      "so the adoption pass has nothing left to sight - got %r"
      % projects.adopt_settings_repos(actor="test"))
check(db.project_get(p2["id"]) is None, "and the project stays deleted")

print("")
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("delete-project: all pinned - PASS")
