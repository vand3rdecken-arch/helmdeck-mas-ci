# -*- coding: utf-8 -*-
"""Pins the two halves of "policy is data, per REPO" that used to report success
and change nothing (debts repo-template-card-kind-unwired and
repo-template-policy-presets-still-global, both closed 2026-08-31).

  1. CARD KIND. A repo whose template says `card_kind: new_direct_task` gets
     live-tree cards WITHOUT anyone saying so per card - and dispatch.new_track,
     the one place a card is born, is the one place that is read. Precedence is
     pinned too: an explicit caller beats the repo, and the repo only ever fills
     a silence.
  2. THE GUARD. The repo default may not smuggle a card past policy.machine -
     if live-tree work is switched off, the card falls back to the worktree
     instead of quietly doing what the template asked.
  3. POLICY PRESETS. Applying a template to repo B must not move repo A's
     values. Before, both went through the ONE global settings.json.
  4. THE GATE COMMAND is provisioned per repo, so a freshly onboarded repo has
     a real check instead of an empty gate station that passes silently.

Self-sandboxing: fake DB, patched settings, temp git repos - nothing touches
the real board, no settings.json is written, nothing is spawned.

Run: py -3.12 ops/tests/test_repo_template_wiring.py
"""
import os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.storage import events, trackstore


class FakeDB:
    """Doubles as the track store AND the project registry."""
    def __init__(self):
        self.tracks, self.projects = {}, {}
    # tracks
    def tracks_all(self):
        return [dict(t) for t in self.tracks.values()]
    def tracks_replace(self, ts):
        self.tracks = {t["id"]: dict(t) for t in ts}
    def track_put(self, t):
        self.tracks[t["id"]] = dict(t)
    def track_get(self, tid):
        t = self.tracks.get(tid)
        return dict(t) if t else None
    # projects
    def projects_all(self):
        return [dict(p) for p in self.projects.values()]
    def project_get(self, pid):
        p = self.projects.get(pid)
        return dict(p) if p else None
    def project_put(self, p):
        self.projects[p["id"]] = dict(p)
    def project_delete(self, pid):
        self.projects.pop(pid, None)


fails = []


def check(desc, ok):
    print(("  ok: " if ok else "  FAIL: ") + desc)
    if not ok:
        fails.append(desc)


# -- sandbox ------------------------------------------------------------------
# settings live in memory: save_settings must never reach the real settings.json.
SETTINGS = {"drivers": {"claude": {"type": "claude"}},
            "policy": {"machine": {"enabled": True, "roots": [], "perm": "bypassPermissions"}},
            "value_per_card": 0, "repo_hooks": {}}


def _save_settings(patch, actor="system", reason=""):
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(SETTINGS.get(k), dict):
            SETTINGS[k].update(v)
        else:
            SETTINGS[k] = v


events.settings = lambda: SETTINGS
events.save_settings = _save_settings
events.emit = lambda *a, **k: None

db = FakeDB()
trackstore._db = db
from spine.storage import db as dbmod
for _n in ("projects_all", "project_get", "project_put", "project_delete"):
    setattr(dbmod, _n, getattr(db, _n))

from spine.ops import projects
from cells.engineer.cards import dispatch

tmp = tempfile.mkdtemp(prefix="hd-tpl-")
doc_repo = os.path.join(tmp, "docs")
code_repo = os.path.join(tmp, "code")
for r in (doc_repo, code_repo):
    os.makedirs(r)
    subprocess.run(["git", "init", "-q", r], check=True)

projects.apply_template(doc_repo, "documents")
projects.apply_template(code_repo, "software-dev")

# -- 1) the repo decides the card kind ----------------------------------------
print("\n1) card_kind comes from the repo's template")
t = dispatch.new_track(doc_repo, "req-schreib-das-angebot", "Angebot schreiben",
                       lane="backlog")
check("documents repo -> live-tree card (direct=True)", t.get("direct") is True)
check("documents repo -> no worktree copy, the repo IS the workplace",
      t.get("worktree") == os.path.abspath(doc_repo))
check("documents repo -> carries the '(direct)' branch marker",
      t.get("branch") == dispatch.DIRECT_BRANCH)

t2 = dispatch.new_track(code_repo, "req-bau-das-ding", "Feature bauen", lane="backlog")
check("software-dev repo -> isolated worktree card (not direct)",
      not t2.get("direct") and not t2.get("machine"))
check("software-dev repo -> gets a real derived branch",
      t2.get("branch") not in (dispatch.DIRECT_BRANCH, dispatch.MACHINE_BRANCH))

# -- 2) an explicit caller still wins -----------------------------------------
print("\n2) the repo default only fills a silence")
t3 = dispatch.new_track(doc_repo, "req-ausnahme", "isoliert bitte", lane="backlog",
                        card_kind="new_track")
check("explicit card_kind=new_track beats the repo default",
      not t3.get("direct") and t3.get("branch") != dispatch.DIRECT_BRANCH)

# -- 3) the guard is not bypassable -------------------------------------------
print("\n3) policy.machine=off makes the repo default fall back, not sneak through")
SETTINGS["policy"]["machine"]["enabled"] = False
t4 = dispatch.new_track(doc_repo, "req-gesperrt", "Angebot", lane="backlog")
check("machine disabled -> falls back to the worktree",
      not t4.get("direct") and t4.get("worktree") == "")
SETTINGS["policy"]["machine"]["enabled"] = True

# a repo that is not a git repo at all must not become a live-tree card either
plain = os.path.join(tmp, "plain")
os.makedirs(plain)
projects.apply_template(plain, "documents")
t5 = dispatch.new_track(plain, "req-kein-git", "Text", lane="backlog")
check("non-git folder -> falls back to the worktree", not t5.get("direct"))

# -- 4) policy presets are per repo, not workspace-global ---------------------
print("\n4) applying a template to one repo does not move another's policy")
check("documents repo allows the 'prepare' mode",
      "prepare" in projects.policy_for(doc_repo, "auto_dispatch_modes", []))
check("software-dev repo does NOT (its template says ['do'])",
      "prepare" not in projects.policy_for(code_repo, "auto_dispatch_modes", []))
check("the two repos really differ at the same moment",
      projects.policy_for(doc_repo, "auto_dispatch_modes", [])
      != projects.policy_for(code_repo, "auto_dispatch_modes", []))
check("an unknown repo falls back to the workspace default",
      projects.policy_for(os.path.join(tmp, "nope"), "auto_dispatch_modes", ["x"]) == ["x"])

# An owner override beats the template, and only for that repo. The value is
# deliberately one NEITHER template sets, so "it leaked" and "it was already
# there" cannot be confused - the trap the first version of this check fell into.
projects.set_override(code_repo, "policy.auto_dispatch_modes", ["cowork"])
check("override wins for the repo it was set on",
      projects.policy_for(code_repo, "auto_dispatch_modes", []) == ["cowork"])
check("...and does not leak to the other repo",
      projects.policy_for(doc_repo, "auto_dispatch_modes", []) == ["do", "prepare"])
check("...and does not leak into the workspace default either",
      (SETTINGS.get("policy") or {}).get("auto_dispatch_modes") is None)
check("the deviation is RECORDED, not guessed",
      any(d["key"] == "policy.auto_dispatch_modes" and d["explicit"]
          for d in projects.resolve(code_repo)["deviations"]))
check("a repo still on its template shows no deviation",
      not projects.resolve(doc_repo)["deviations"])
projects.set_override(code_repo, "policy.auto_dispatch_modes", None)
check("removing the override falls back to the template value",
      projects.policy_for(code_repo, "auto_dispatch_modes", []) == ["do"])

# -- 5) the gate command is provisioned per repo ------------------------------
print("\n5) a freshly onboarded repo gets a real gate command")
code_view = projects.resolve(code_repo)
check("software-dev repo has a gate command", bool(code_view.get("gate_cmd")))
check("...and it points at the generic, repo-derived gate",
      "repo_gate.py" in code_view.get("gate_cmd", ""))
check("documents repo declares no gate command (honest empty)",
      projects.resolve(doc_repo).get("gate_cmd") == "")
check("the gate command is stored PER REPO under repo_hooks",
      (SETTINGS["repo_hooks"].get(os.path.abspath(code_repo)) or {}).get("gate"))

print("\n%s (%d checks failed)" % ("FAILED" if fails else "ALL PASS", len(fails)))
sys.exit(1 if fails else 0)
