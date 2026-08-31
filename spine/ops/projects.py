# -*- coding: utf-8 -*-
"""A PROJECT is the billable unit AND (owner decree 2026-08-30) the REPO record:
*"Pro Repo. Jedes Repo ist eigenes Projekt und eigenes Git."*

Two jobs, one record, on purpose. Before this, a repo entered HelmDeck implicitly
as an absolute path string on a card (dispatch.new_track), and everything a repo
type wants to preset was GLOBAL - two repos would overwrite each other's setup.
The obvious fix (a `repos` table / daemon/repos.json) was rejected by the same
decree that made settings idiot-proof: no second registry, no second edit place.
HelmDeck already had a THIRD, fake one - routes_gxp synthesised a repo list out
of `pm.repos | repo_hooks.keys() | {default_repo}` on every call - and adding a
fourth beside it would have been the bug, not the fix.

So the project record grows four fields (`repo`, `template`, `applied`,
`overrides`) and becomes the one place that answers "how does THIS repo run".

WHY IT LIVES HERE AND NOT UNDER `policy`
----------------------------------------
HARNESS.md:229-233: the chat configure path whitelists TOP-LEVEL keys only, so
anything under `policy` is chat-writable by construction. A repo's template must
not be rewritable by a sentence aimed at a *different* repo, so it may not live
there. helmdeck.db is outside settings.json entirely - the condition is met by
where the data sits, not by a check that could be forgotten.

ONE OWNER PER FIELD (CLAUDE.md, no monkey patches)
--------------------------------------------------
`template`/`applied` are mutated ONLY by apply_template(); `overrides` ONLY by
set_override(); a repo becomes known ONLY through sight_repo(). Nothing here
re-scans artifacts to guess state: `deviations` compares the value STORED at
apply time against the value live now - two recorded facts, not a reconstruction.

Its original job, unchanged - two real contract shapes:

  fixed  - a SOW for an agreed price. Cards under it consume effort, not value;
           the price only counts once the whole SOW is delivered (every card done).
  tm     - time & material: the client pays `rate` per hour actually worked.
           Value accrues with real elapsed time, not a per-card guess.

Cards opt in via `project_id` (sessions.EDITABLE); a card with no project keeps
today's behavior (its own `value`, counted on acceptance) - nothing regresses.
events.metrics() reads real hours from real lane-in-"working" duration
(events.time_in_work), not the touch-count tariff (that stays what it is:
human capacity/utilization, unrelated to billing)."""
import os
import time
from spine.storage import db

BILLINGS = ("fixed", "tm")


# ---------------------------------------------------------------------------
# REPO PATHS - the shape matters, and it bit us before
# ---------------------------------------------------------------------------
def norm_repo(path):
    """The canonical STORED form of a repo path.

    Deliberately abspath-only, exactly like dispatch.new_track:50 and
    dispatch.new_direct_task:358 - because `repo_hooks` is looked up by an EXACT
    string match on the card's own `repo` value (lanemachine._repo_hook:648).
    Normcasing here would produce a hook key that the card can never hit: the
    deploy step would silently not run and nothing would say why. So the stored
    form matches what a card carries, byte for byte, and case-insensitive
    matching happens in repo_key() where it belongs - on the COMPARISON, never
    on the value we write."""
    p = str(path or "").strip()
    if not p:
        return ""
    return os.path.abspath(os.path.expandvars(os.path.expanduser(p)))


def repo_key(path):
    """The COMPARISON form: normcase over the stored form. Windows hands us
    C:\\Repo and c:/repo for the same directory, so identity has to be decided
    here rather than by whichever spelling arrived first."""
    p = norm_repo(path)
    return os.path.normcase(p) if p else ""


def _slug(s):
    import re
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:32] or "project"


def list_projects():
    return db.projects_all()


def get_project(pid):
    return db.project_get(pid)


def new_project(name, billing, client="", fixed_price=None, rate=None, actor="owner",
                repo=""):
    if billing not in BILLINGS:
        raise ValueError("billing must be one of %s" % (BILLINGS,))
    if billing == "fixed" and fixed_price is None:
        raise ValueError("fixed price project needs fixed_price")
    if billing == "tm" and rate is None:
        raise ValueError("time & material project needs an hourly rate")
    repo = norm_repo(repo)
    if repo:
        clash = for_repo(repo)
        if clash:
            raise ValueError("Repo %s gehoert schon zu Projekt %s (%s) - ein Repo ist "
                             "genau ein Projekt." % (repo, clash["name"], clash["id"]))
    pid = time.strftime("%Y%m%d-%H%M%S") + "-" + _slug(name)
    p = {"id": pid, "name": name, "client": client, "billing": billing,
         "fixed_price": float(fixed_price) if fixed_price is not None else None,
         "rate": float(rate) if rate is not None else None,
         "status": "active", "actor": actor,
         # the repo half of the record - see the module docstring. `template` is
         # empty until apply_template() sets it; an empty template means "no
         # repo type chosen yet", which the onboarding screen asks about.
         "repo": repo, "template": "", "applied": {}, "overrides": {},
         "created": time.strftime("%Y-%m-%d %H:%M:%S"),
         "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    db.project_put(p)
    return p


# `template`, `applied` and `overrides` are deliberately NOT editable here:
# each has exactly one mutator below (apply_template / set_override), which is
# what keeps "vom Standard abgewichen" a recorded fact instead of a guess.
EDITABLE = ("name", "client", "billing", "fixed_price", "rate", "status", "repo")


def update_project(pid, patch, actor="owner"):
    p = db.project_get(pid)
    if not p:
        raise RuntimeError("no such project: " + pid)
    for k in EDITABLE:
        if k in patch and patch[k] is not None:
            if k == "repo":
                # one repo, one project: re-pointing a project at a repo that
                # already belongs to another one would give that repo two
                # templates and no way to tell which is in force.
                r = norm_repo(patch[k])
                clash = for_repo(r) if r else None
                if clash and clash["id"] != pid:
                    raise ValueError("Repo %s gehoert schon zu Projekt %s (%s)."
                                     % (r, clash["name"], clash["id"]))
                p[k] = r
            else:
                p[k] = float(patch[k]) if k in ("fixed_price", "rate") else patch[k]
    if p["billing"] not in BILLINGS:
        raise ValueError("billing must be one of %s" % (BILLINGS,))
    p["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    db.project_put(p)
    return p


def delete_project(pid, actor="owner"):
    if not db.project_get(pid):
        raise RuntimeError("no such project: " + pid)
    db.project_delete(pid)
    return {"deleted": pid}


# ---------------------------------------------------------------------------
# THE REPO RECORD - one reader, one mutator per field
# ---------------------------------------------------------------------------
def for_repo(path):
    """THE reader: the project that owns this repo path, or None.

    Case-insensitive by repo_key, so C:\\Repo and c:/repo resolve to the same
    record. Pure - it never creates anything; sight_repo() is the only door in."""
    k = repo_key(path)
    if not k:
        return None
    for p in db.projects_all():
        if repo_key(p.get("repo")) == k:
            return p
    return None


def known_repos():
    """Every repo HelmDeck actually knows, from the registry - not synthesised.

    This replaces routes_gxp's `pm.repos | repo_hooks.keys() | {default_repo}`
    union, which recomputed a repo list on every single call and could therefore
    never carry anything (like a template) that a repo needs to REMEMBER."""
    return sorted({p["repo"] for p in db.projects_all() if p.get("repo")})


def sight_repo(path, actor="owner", name=""):
    """THE door in: a repo becomes known here or not at all.

    Called at EVENT TIME - when a card is created against a repo, when the owner
    opens the repo settings, when legacy repos are adopted - never by a sweep
    that re-derives the world. Idempotent: seeing a known repo returns its
    existing project untouched, so callers may call it freely.

    The project it creates is billing-neutral (`fixed`, price 0): the repo half
    of the record is what the caller wanted, and forcing a billing decision at
    this moment would put a contract question in front of a technical one."""
    repo = norm_repo(path)
    if not repo:
        return None
    got = for_repo(repo)
    if got:
        return got
    p = new_project(name or os.path.basename(repo.rstrip("\\/")) or repo,
                    "fixed", fixed_price=0.0, actor=actor, repo=repo)
    _audit("repo_sighted", repo, actor, project=p["id"])
    return p


def _audit(op, repo, actor, **fields):
    """Every repo-record mutation lands in the append-only event log. Best
    effort by design: an audit that cannot be written must not swallow the
    owner's change, but it must also never be the reason a change is invisible -
    so failures surface as a printed line rather than silence."""
    try:
        from spine.storage import events
        events.emit("repo_config", "-", op=op, repo=repo, actor=actor, **fields)
    except Exception as e:                                   # noqa: BLE001
        print("projects: audit for %s/%s failed: %s" % (op, repo, e), flush=True)


def apply_template(repo, template_id, actor="owner"):
    """THE mutator for `template` + `applied`. Raises on an unknown template.

    What it does NOT do: touch settings that would only pretend to work. The
    template's global presets are written through events.save_settings, its
    per-repo deploy hook through repo_hooks - and its `stations` list is pure
    display, resolved by resolve(). Level-B governance flags (worktreeIsolation,
    gateBeforeReview) are deliberately absent from every template: ARCHITECTURE.md
    :160-162 records that nothing reads them yet, so setting them would report
    success and change nothing - the worst answer a config path can give.

    `applied` is the snapshot of what the template actually set, at the moment it
    set it. That snapshot is what makes a later deviation a comparison of two
    recorded facts rather than a reconstruction (CLAUDE.md, no monkey patches)."""
    from spine.registry import templates as tpl
    t = tpl.get(template_id)
    if not t:
        raise ValueError("unbekannte Vorlage: %s (es gibt: %s)"
                         % (template_id, ", ".join(tpl.ids())))
    p = sight_repo(repo, actor=actor)
    if not p:
        raise ValueError("kein Repo-Pfad angegeben")
    repo = p["repo"]
    applied = {}
    # -- 1. the per-repo half: deploy hook AND gate command, under repo_hooks --
    # The gate command joined the deploy hook here because they have the same
    # shape (a shell command that belongs to ONE repo) but opposite defaults: an
    # empty deploy hook is harmless ("nothing to ship"), an empty gate command
    # means the card clears the gate station having checked nothing. Before this,
    # a freshly cloned repo had no gate at all and nothing said so -
    # lanemachine._gate simply found no helmdeck.gate and skipped the block.
    # A helmdeck.gate file IN the repo still wins over this preset (_gate's
    # resolution order): the file is the repo declaring its own check.
    from spine.storage import events
    hooks = dict(events.settings().get("repo_hooks") or {})
    entry = dict(hooks.get(repo) or {})
    entry["deploy"] = t.get("deploy_hook", "")
    entry["gate"] = t.get("gate_cmd", "")
    hooks[repo] = entry
    events.save_settings({"repo_hooks": hooks}, actor=actor,
                         reason="Vorlage %s fuer %s" % (template_id, repo))
    applied["repo_hooks.deploy"] = entry["deploy"]
    applied["repo_hooks.gate"] = entry["gate"]
    # -- 2. the policy presets: RECORDED for this repo, not written globally ---
    # This used to fan the template's `settings` out through events.save_settings
    # into the one global settings.json, which meant applying a template to repo
    # B moved those values for repo A too (debt
    # repo-template-policy-presets-still-global). The decree is "pro Repo", so
    # the presets now live where the rest of the repo's answer already lives:
    # the project record. `applied` was ALREADY the snapshot of what the template
    # set - it just had no reader. policy_for() is that reader.
    #
    # Nothing is lost for repos without a template: policy_for falls through to
    # the global settings value, which stays the workspace default it always was.
    for dotted, val in (t.get("settings") or {}).items():
        applied[dotted] = val
    # -- 3. the record ---------------------------------------------------------
    p["template"] = template_id
    p["applied"] = applied
    p["overrides"] = {}          # a fresh template start is a fresh baseline
    p["applied_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    p["applied_by"] = actor
    p["updated"] = p["applied_at"]
    db.project_put(p)
    _audit("template_applied", repo, actor, template=template_id, applied=applied)
    return p


def set_override(repo, key, value, actor="owner"):
    """THE mutator for `overrides`: one key of this repo deliberately differs
    from what its template set.

    Recorded at the moment of the change, at one owner - the U-Bahn map then
    RENDERS the deviation instead of deducing it. PRD §5: the template sets the
    starting value, the owner may change it, and the change must be visible.
    Passing value=None removes the override (back to the template's value)."""
    p = for_repo(repo)
    if not p:
        raise ValueError("Repo %s ist nicht bekannt - erst eine Vorlage waehlen."
                         % norm_repo(repo))
    ov = dict(p.get("overrides") or {})
    if value is None:
        ov.pop(key, None)
    else:
        ov[key] = value
    p["overrides"] = ov
    p["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    db.project_put(p)
    _audit("override_set", p["repo"], actor, key=key, value=value)
    return p


def policy_for(repo, key, default=None):
    """The value `policy.<key>` has FOR THIS REPO. THE reader of the per-repo
    presets (debt repo-template-policy-presets-still-global).

    Three recorded facts, in falling order - never a reconstruction:
      1. `overrides` - the owner deliberately moved this key for this repo;
      2. `applied`   - what the repo's template set when it was applied;
      3. the global settings value - the workspace default, which is what a repo
         with no template has always used and still uses.

    Total: an unknown repo, a missing record or an unreadable db all mean "no
    per-repo answer", which falls through to (3). A repo config problem may cost
    the customisation, never the caller's decision.

    Callers pass the SUB-key (`auto_accept_green`), matching how they read it
    from the settings blob; the dotted form is this function's business."""
    dotted = "policy." + str(key or "")
    try:
        p = for_repo(repo) if repo else None
    except Exception as e:                                   # noqa: BLE001
        print("projects: per-repo policy for %s unreadable (%s) - using the "
              "workspace default" % (repo, e), flush=True)
        p = None
    if p:
        ov = p.get("overrides") or {}
        if dotted in ov:
            return ov[dotted]
        ap = p.get("applied") or {}
        if dotted in ap:
            return ap[dotted]
    from spine.storage import events
    v = (events.settings().get("policy") or {}).get(key)
    return default if v is None else v


def _live(dotted):
    """The value a dotted settings path has RIGHT NOW. `repo_hooks.deploy` is
    resolved per repo by the caller, everything else is a global settings read."""
    from spine.storage import events
    cur = events.settings()
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def resolve(repo):
    """How THIS repo runs: Default -> Vorlage -> overrides, plus the deviations.

    The single answer the U-Bahn map, the onboarding screen and Henry all read,
    so none of them can describe the repo differently from the others.

    `deviations` is derived by comparing the value STORED in `applied` against
    the value live now. Both sides are recorded facts, which is the difference
    between a legitimate derivation and the kind of reconstruction CLAUDE.md
    forbids: nothing here guesses what the template *would* have set."""
    from spine.registry import templates as tpl
    p = for_repo(repo)
    path = p["repo"] if p else norm_repo(repo)
    tid = (p or {}).get("template") or ""
    t = tpl.get(tid) if tid else None
    applied = (p or {}).get("applied") or {}
    overrides = (p or {}).get("overrides") or {}

    from spine.storage import events
    _entry = (events.settings().get("repo_hooks") or {}).get(path) or {}
    hook = _entry.get("deploy", "")
    gate_cmd = _entry.get("gate", "")

    deviations = []
    for dotted, was in applied.items():
        if dotted == "repo_hooks.deploy":
            now = hook
        elif dotted == "repo_hooks.gate":
            now = gate_cmd
        elif dotted.startswith("policy."):
            # Per-repo since the presets stopped being global: comparing against
            # the WORKSPACE value here would report a deviation for every repo
            # whose template legitimately differs from the workspace default -
            # the map would light up permanently and mean nothing. The honest
            # comparison is the value in force FOR THIS REPO against what its
            # template set, which makes a deviation exactly what the word says:
            # the owner moved it.
            now = policy_for(path, dotted[len("policy."):])
        else:
            now = _live(dotted)
        if now != was:
            deviations.append({"key": dotted, "template_value": was, "value": now,
                               "explicit": dotted in overrides})
    return {
        "repo": path,
        "known": bool(p),
        "project": {"id": p["id"], "name": p["name"]} if p else None,
        "template": tid,
        "template_label": (t or {}).get("label", ""),
        "template_who": (t or {}).get("who", ""),
        "card_kind": (t or {}).get("card_kind", ""),
        # `stations` is the list the template declares as ACTIVE. resolve() does
        # not decide what a station IS - sessions.flow() owns the graph and only
        # asks this for the on/off answer. `station_notes` is the same deal for
        # "active, but here is what it actually means for this repo type" (the
        # gate that runs empty in a document repo).
        "stations": list((t or {}).get("stations") or []),
        "station_notes": dict((t or {}).get("notes") or {}),
        "deploy_hook": hook,
        # The gate command IN FORCE for this repo as far as settings know. It is
        # deliberately not the whole answer: a `helmdeck.gate` file inside the
        # repo outranks it (lanemachine._gate), and this record cannot see that
        # file. So the map may say "the template set this" while the repo's own
        # file is what actually runs - which is why _gate logs the SOURCE it
        # used on the card timeline rather than leaving the owner to infer it.
        "gate_cmd": gate_cmd,
        "applied": applied,
        "overrides": overrides,
        "deviations": deviations,
        "applied_at": (p or {}).get("applied_at", ""),
        "applied_by": (p or {}).get("applied_by", ""),
    }


def adopt_settings_repos(actor="system"):
    """Fold the pre-record repo mentions into real project records, once.

    This is the migration named in the PRD (§4.1, "beim ersten Sehen eines
    unbekannten Repos automatisch ein Projekt anlegen"): the three legacy places
    a repo could be mentioned - `pm.repos`, `repo_hooks` keys, `default_repo` -
    are read ONE time and turned into records through sight_repo. After that the
    registry is authoritative and nothing re-derives a repo list from settings.

    Idempotent and cheap (one settings read + one db read), so calling it when a
    surface that needs the repo list opens is a sighting, not a sweep. Total: a
    failure to adopt must never take down the caller's screen."""
    out = []
    try:
        from spine.storage import events
        s = events.settings()
        seen = list((s.get("pm") or {}).get("repos") or [])
        seen += list((s.get("repo_hooks") or {}).keys())
        if s.get("default_repo"):
            seen.append(s["default_repo"])
        for r in seen:
            p = sight_repo(r, actor=actor)
            if p:
                out.append(p["repo"])
    except Exception as e:                                   # noqa: BLE001
        print("projects: adopting legacy repos failed: %s" % e, flush=True)
    return sorted(set(out))


def billed_value(project, hours, all_done):
    """What this project has earned so far, given the real hours worked across
    its cards and whether every one of its cards has reached 'done'.

    fixed: the whole SOW price counts once fully delivered - not before (avoids
           recognizing revenue on a partially-done contract), and not per-card.
    tm:    hours * rate, counted as worked - a client on time & material pays
           for time spent regardless of which individual card is done yet."""
    if project["billing"] == "fixed":
        return project["fixed_price"] if all_done else 0.0
    return round(hours * project["rate"], 2)
