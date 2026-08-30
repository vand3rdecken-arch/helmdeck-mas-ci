# -*- coding: utf-8 -*-
"""Repo-Onboarding mit Harness-Templates - the four Phase-2 acceptance criteria.

One test per card from ops/docs/repo-onboarding-templates.md §6, each phrased as
the PRD phrased it, because a criterion restated in the tester's own words is a
criterion nobody can check against the agreement:

  1 repo-project-record  - two repos carry different templates at the same time
                           WITHOUT overwriting each other
  2 repo-templates-catalog - a broken template file can never stop a card
  3 loopmap-per-repo     - the map shows the right pipeline for both repo types,
                           DERIVED from /loop/map, with nothing switched off that
                           is actually law
  4 chat-template-verb   - the sentences from §4.3.3 work, and "Gate weg" /
                           "Review aus" are refused WITH A ROUTE, not a wall

SELF-SANDBOXING - and this is not a formality here.
Everything below writes settings and projects. ops/tests/test_reset_gxp_guard.py
once ran unsandboxed and wiped the owner's live recordings; the same shape of
mistake here would rewrite his real repo_hooks and settings.json. So db.DBPATH,
events.SET and events.EV are all redirected into a temp dir BEFORE anything
imports them for real, and the run asserts it is not pointing at the repo root.
No daemon, no git, no network, no LLM.
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _sandbox(tmp):
    """Point every persistent store at `tmp`, then PROVE it moved. An assert
    that the sandbox took hold is the whole difference between this file and the
    one that deleted real data."""
    from spine.storage import db, events
    db.DBPATH = os.path.join(tmp, "test.db")
    events.SET = os.path.join(tmp, "settings.json")
    events.EV = os.path.join(tmp, "events.jsonl")
    if hasattr(db, "_local") and getattr(db._local, "c", None) is not None:
        db._local.c = None
    for p in (db.DBPATH, events.SET, events.EV):
        assert os.path.dirname(os.path.abspath(p)) == os.path.abspath(tmp), \
            "sandbox failed - refusing to run against %s" % p
        assert os.path.abspath(p) != os.path.join(ROOT, os.path.basename(p))
    db.init(role="tool")
    return db, events


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-repotpl-")
    db, events = _sandbox(tmp)
    from cells.copilot import copilot_actions as ca
    from cells.engineer import sessions
    from spine.ops import projects
    from spine.registry import templates

    repo_dev = os.path.join(tmp, "code-repo")
    repo_doc = os.path.join(tmp, "text-repo")
    os.makedirs(repo_dev, exist_ok=True)
    os.makedirs(repo_doc, exist_ok=True)

    # ---------------------------------------------------------------- card 1
    print("\n[1] repo-project-record - two repos, two templates, no collision")
    projects.apply_template(repo_dev, "software-dev", actor="owner")
    projects.apply_template(repo_doc, "documents", actor="owner")
    a, b = projects.resolve(repo_dev), projects.resolve(repo_doc)
    check(a["template"] == "software-dev" and b["template"] == "documents",
          "each repo kept its own template (%s / %s)" % (a["template"], b["template"]))
    check("deploy" in a["stations"] and "deploy" not in b["stations"],
          "the templates really differ: deploy on for code, off for text")
    check(a["project"]["id"] != b["project"]["id"],
          "two distinct project records back them")
    # the collision the PRD was actually worried about
    projects.apply_template(repo_dev, "software-dev", actor="owner")
    check(projects.resolve(repo_doc)["template"] == "documents",
          "re-applying one repo's template did NOT overwrite the other's")

    # path shape: a hook key that a card can never hit is the silent killer
    hooks = events.settings().get("repo_hooks") or {}
    check(projects.norm_repo(repo_dev) in hooks,
          "the deploy hook is keyed the way a card spells its repo (exact-match safe)")
    check(projects.for_repo(repo_dev.upper()) is not None
          or projects.for_repo(repo_dev.lower()) is not None,
          "repo lookup is case-insensitive (Windows hands us both spellings)")
    check(projects.known_repos() and all(os.path.isabs(r) for r in projects.known_repos()),
          "known_repos comes from the registry, absolute (%d)" % len(projects.known_repos()))

    # ---------------------------------------------------------------- card 2
    print("\n[2] repo-templates-catalog - a broken file may never stop a card")
    tdir = templates.DIR
    path = os.path.join(tdir, "software-dev.md")
    keep = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            keep = f.read()
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("---\nid: software-dev\nlabel:\n  - not: a mapping\n   bad\n---\n")
        got = templates.get("software-dev")
        check(bool(got) and got["label"] == "Software-Entwicklung",
              "a mangled template file falls back to the built-in, still usable")
        check(len(templates.catalog()) >= 2, "the catalog still offers both types")
        from spine.registry import harness
        check(any("software-dev" in k for k in harness.errors()),
              "and the breakage is VISIBLE in harness.errors(), not swallowed")
        # the real acceptance sentence: a card can still be started
        v = projects.resolve(repo_dev)
        f2 = sessions.flow(None, repo_view=v)
        check(len(f2["nodes"]) == 4 and bool(f2["gate"]),
              "the lane machine still resolves while a template file is broken")
    finally:
        if keep is not None:
            with open(path, "w", encoding="utf-8") as f:
                f.write(keep)
        templates.get("software-dev")          # reload the good file

    # ---------------------------------------------------------------- card 3
    print("\n[3] loopmap-per-repo - the right pipeline, derived, nothing law is 'off'")
    for repo, tid, want_deploy in ((repo_dev, "software-dev", True),
                                   (repo_doc, "documents", False)):
        v = projects.resolve(repo)
        f = sessions.flow(None, repo_view=v)
        st = {n["key"]: n for n in f["nodes"]}
        st["gate"], st["deploy"] = f["gate"], f["deploy"]
        check(f["stations"] == list(sessions.STATIONS),
              "%s: station order comes from the server, not the client" % tid)
        # deploy: off for documents; for software-dev it is ON in the template
        # but has no command yet, which must read as off-with-a-reason
        check(st["deploy"]["active"] is False and st["deploy"].get("off_reason"),
              "%s: deploy is off and SAYS WHY (%s)"
              % (tid, (st["deploy"].get("off_reason") or "")[:48]))
        for law in ("backlog", "working", "gate", "review"):
            check(st[law]["active"] is True,
                  "%s: %s is never rendered as switched off - it is law/entrance"
                  % (tid, law))
        check(st["gate"]["kind"] == "fixed", "%s: gate stays kind=fixed" % tid)
        _ = want_deploy
    # the documents template must LABEL the empty gate rather than hide it
    vdoc = projects.resolve(repo_doc)
    fdoc = sessions.flow(None, repo_view=vdoc)
    check("leer" in (fdoc["gate"].get("note") or "").lower(),
          "documents: the gate is labelled 'laeuft leer' instead of being hidden")
    # and turning deploy on must make it appear
    projects.apply_template(repo_dev, "software-dev", actor="owner")
    ca._run_action({"type": "set_station", "repo": repo_dev, "station": "deploy",
                    "on": True, "command": "echo ship"}, "owner", "owner")
    fdev = sessions.flow(None, repo_view=projects.resolve(repo_dev))
    check(fdev["deploy"]["active"] is True,
          "deploy switches ON once a real command exists")

    # ---------------------------------------------------------------- card 4
    print("\n[4] chat-template-verb - the sentences work, refusals carry a route")
    r = ca._run_action({"type": "apply_template", "repo": repo_doc,
                        "template": "documents"}, "owner", "owner")
    check("Strecke" in r and "Deploy (aus)" in r,
          "'wie ein Doku-Repo' answers with the PIPELINE, not a key dump")
    r = ca._run_action({"type": "set_station", "repo": repo_dev, "station": "deploy",
                        "on": False}, "owner", "owner")
    check("AUS" in r, "'kein automatischer Deploy mehr' switches the station off")
    check((projects.resolve(repo_dev).get("deploy_hook") or "") == "",
          "...and really empties repo_hooks.<repo>.deploy")

    for word in ("gate", "Gate", "review", "Abnahme"):
        r = ca._run_action({"type": "set_station", "repo": repo_dev,
                            "station": word, "on": False}, "owner", "owner")
        # the PRD's rule: a boundary produces a POINTER to the workflow that is
        # open, never a full stop. Both readings offer auto_accept_green; the
        # gate additionally routes the "remove it entirely" reading to a card.
        check("auto_accept_green" in r,
              "'%s abschalten' is refused WITH a route, not a wall" % word)
    r = ca._run_action({"type": "set_station", "repo": repo_dev,
                        "station": "warp-drive", "on": False}, "owner", "owner")
    check("keine Station" in r and "->" in r,
          "an invented station is rejected and the real route is shown")

    # the fixed keys stay fixed - a station verb must not become a key setter
    before = json.dumps(events.settings(), sort_keys=True)
    ca._run_action({"type": "set_station", "repo": repo_dev, "station": "gate",
                    "on": False}, "owner", "owner")
    check(json.dumps(events.settings(), sort_keys=True) == before,
          "a refused station change wrote NOTHING to settings")

    # role gate
    r = ca._run_action({"type": "apply_template", "repo": repo_dev,
                        "template": "documents"}, "client", "client")
    check("chat_configure_roles" in r, "a non-configuring role is refused by policy key")
    check(projects.resolve(repo_dev)["template"] == "software-dev",
          "...and the template did not change")

    # deviation is RECORDED at write time, not deduced later
    projects.apply_template(repo_doc, "documents", actor="owner")
    ca._run_action({"type": "configure", "repo": repo_doc,
                    "patch": {"policy.auto_accept_green": True}}, "owner", "owner")
    dev = projects.resolve(repo_doc)["deviations"]
    check(any(d["key"] == "policy.auto_accept_green" and d["explicit"] for d in dev),
          "a value moved away from the template is recorded as an explicit override")

    print("\n%s (%d failed)" % ("FAIL" if _fails else "PASS", len(_fails)))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
