# -*- coding: utf-8 -*-
"""THE PROJECT LAYER of the harness config, and the chain it sits on top of.

Phase 1 of ops/docs/backlog/harness-config-ui (owner complaint 2026-09-02:
"Henrys Regeln stehen als Fliesstext und sind nirgends sichtbar oder
einstellbar; drei Ebenen, fuer den Nutzer unsichtbar vermischt"). db.py holds
the rows; this module owns the four things that make an overlay honest:

  - THE CHAIN. `code default -> seed -> workspace -> project`, later wins.
    resolve() answers with the value AND the layer it came from, because the
    whole feature is the badge: "Geerbt vom Workspace" vs "Fuer dieses Projekt
    gesetzt". A resolver that returned only the value would force every caller
    to re-derive the provenance, and they would each get it slightly wrong.

  - ABSENT MEANS INHERITED. Clearing a value DELETES its row (db.
    project_config_delete), it never stores a null. The Paseo rule the
    settings-ia-redesign card already cites, and the reason `layer` is
    derivable at all: "absent" is a property of the table, not a sentinel
    value every consumer has to agree on.

  - THE WHITELIST, DERIVED. overridable() is the set of paths whose own
    declaration says they may differ per project - `project: True` on a
    _config_schema knob, `scope: "project"` on a BEHAVIOR_RULE. There is
    deliberately no hand-kept list here: a second list beside the schema is
    exactly the drift the card was written against (the configure-allowlist in
    board-copilot.md is the worked example of that drift).

  - THE TRACKED WRITE. write() returns the previous value (the undo handle)
    and mirrors op/actor/before/after into the append-only sink, the same
    shape spine/auth/policy.py::_mirror uses. The audit law is not worked
    around here, it is used.

WHICH PROJECT APPLIES WHEN (design doc section 3, resolved at EVENT TIME)
------------------------------------------------------------------------
Henry is ONE agent per workspace and many of his turns have no repo at all
(machine_task, board questions). A stored "current project" would be exactly
the assumption the no-monkey-patches law forbids, so there is none: callers
resolve the project from the event they are already holding, at one owner each.

  for_card(track)   - a card turn: the card's own repo. Fixed at dispatch.
  for_chat(repo)    - a chat turn naming a repo: that repo, else default_repo.
  ""                - everything else. The overlay simply does not apply, and
                      resolve() then answers from the workspace layer.

WHY THE ROWS KEY ON repo_key() AND NOT ON THE PROJECT ID
--------------------------------------------------------
A project record can be created after the fact (projects.sight_repo is the one
door in), but a card carries a repo PATH from the moment it is dispatched. Key
on the path's comparison form and the overlay is answerable before the project
record exists, and survives the record being recreated. repo_key() (not
norm_repo) because Windows hands us C:\\Repo and c:/repo for one directory.
"""

MAX_VALUE_BYTES = 8192     # per key, JSON-encoded
MAX_KEYS_PER_WRITE = 32

# The chain, in application order. Exported so the app can mirror the badge
# vocabulary and ops/tests can hold the two halves equal - the same discipline
# DOORS/SCOPES already live under.
LAYERS = ("default", "seed", "workspace", "project")


def project_key(repo):
    """The stored form of a project key. "" when there is no repo, which is a
    legitimate answer meaning "workspace only", not an error."""
    if not repo:
        return ""
    from spine.ops import projects
    return projects.repo_key(repo)


def for_card(track):
    """The project a CARD turn belongs to: the repo the card was dispatched
    against. One owner, no guessing - if the card has no repo it has no project
    overlay, and that is the honest answer rather than a fallback to whatever
    repo happens to be the default."""
    return project_key((track or {}).get("repo") or "")


def for_chat(repo=""):
    """The project a CHAT turn belongs to: the repo it names, else the
    workspace's default_repo. A board question that names no repo still lands
    on the default repo because that is what the owner means by "das Repo" -
    but a machine_task, which names none and means none, should pass "" and get
    the workspace layer."""
    if not repo:
        from spine.storage import events
        repo = events.settings().get("default_repo") or ""
    return project_key(repo)


# ---------------------------------------------------------------------------
# The whitelist, derived from the declarations that already exist
# ---------------------------------------------------------------------------
def overridable():
    """{path: declaring-table} for every key a project may override.

    Derived, never kept: a knob becomes project-overridable by carrying
    `project: True` in spine/http/apimeta.py's schema or `scope: "project"` in
    spine/registry/behavior.py's rule table, in the same commit that gives it a
    row. Both tables are already the single source of truth for their half; a
    third list here could only disagree with them."""
    out = {}
    try:
        from spine.registry import behavior
        for r in behavior.BEHAVIOR_RULES:
            if r.get("scope") == "project":
                out[behavior.rule_path(r["key"])] = "behavior"
    except Exception:                                        # noqa: BLE001
        pass                  # a broken rule table must never break a resolve
    try:
        from spine.http import apimeta
        from spine.storage import events
        for e in apimeta._config_schema(events.settings()):
            if e.get("project"):
                out[e["path"]] = "settings"
    except Exception:                                        # noqa: BLE001
        pass
    return out


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------
def _dig(doc, path):
    """(value, present) for a dotted path in a nested dict. `present` is the
    load-bearing half: a knob whose stored value happens to equal the default
    is still SET, and the badge must say so."""
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None, False
        cur = cur[part]
    return cur, True


def _base_layers(path):
    """The three layers below the project overlay, as [(layer, value, present)].

    `default` is the declared default (behavior rule / events.DEFAULTS), `seed`
    the policy plane's own value where it has one, `workspace` settings.json.

    Honest note on `workspace`: events.save_settings writes the whole merged
    document back, so once ANY setting has been saved the file also contains
    every default. That makes "the file has it" a weak signal, and the chain
    does not lean on it - the distinction this module has to get right, and the
    only one the UI renders, is workspace vs project. `default`/`seed` are
    reported so a caller can show where a value ultimately comes from; they are
    never used to decide whether a project row exists."""
    from spine.storage import events
    rows = []

    dv, dp = None, False
    try:
        from spine.registry import behavior
        rule = behavior.by_path(path)
        if rule is not None:
            dv, dp = behavior.default_of(rule), True
    except Exception:                                        # noqa: BLE001
        pass
    if not dp:
        dv, dp = _dig(events.DEFAULTS, path)
    rows.append(("default", dv, dp))

    sv, sp = None, False
    if path.startswith("policies."):
        try:
            from spine.auth import policy
            sv, sp = _dig({"policies": policy.get_policies()}, path)
        except Exception:                                    # noqa: BLE001
            pass
    rows.append(("seed", sv, sp))

    wv, wp = _dig(events.settings(), path)
    rows.append(("workspace", wv, wp))
    return rows


def chain(path, project=""):
    """The full resolution chain for one key: a list of
    {layer, value, present}, lowest first, with the project overlay last.

    This IS the "Vererbungskette" the design doc's G1 asks for. The UI renders
    the last present layer as the value and the layer NAME as the badge, so the
    screen never has to guess and two screens can never disagree."""
    rows = [{"layer": ly, "value": v, "present": p} for ly, v, p in _base_layers(path)]
    pv, pp = None, False
    if project:
        st = stored(project)
        if path in st:
            pv, pp = st[path], True
    rows.append({"layer": "project", "value": pv, "present": pp})
    return rows


def resolve(path, project=""):
    """{value, layer, inherited} - the effective value and where it came from.

    `inherited` is simply "the project did not set this", which is what the row
    badge and the presence of a reset link are both driven by."""
    eff = {"value": None, "layer": "default", "inherited": True}
    for row in chain(path, project):
        if row["present"]:
            eff = {"value": row["value"], "layer": row["layer"],
                   "inherited": row["layer"] != "project"}
    return eff


def stored(project):
    """Only the rows this project actually set (no inheritance folded in).

    A key retired from the whitelist stays on disk but stops being served - the
    resolved config must only ever contain keys some table still declares, or
    the screen would render a row nothing can explain."""
    if not project:
        return {}
    from spine.storage import db
    allowed = overridable()
    return {k: v for k, v in db.project_config_get(project).items() if k in allowed}


def resolve_all(project=""):
    """{path: {value, layer, inherited}} for every overridable key. What the
    harness screen and Henry's turn overlay both read - one call, one shape, so
    the two can never drift apart."""
    return {p: resolve(p, project) for p in overridable()}


# ---------------------------------------------------------------------------
# The one tracked writer
# ---------------------------------------------------------------------------
def validate(patch):
    """(cleaned, error). A single bad key fails the WHOLE write rather than
    being dropped, so a caller is never told "ok" about a value that did not
    land - the rule userconfig.validate already established."""
    if not isinstance(patch, dict):
        return None, "config must be an object"
    if not patch:
        return None, "config is empty"
    if len(patch) > MAX_KEYS_PER_WRITE:
        return None, "too many keys (max %d)" % MAX_KEYS_PER_WRITE
    import json
    allowed = overridable()
    for k, v in patch.items():
        if k not in allowed:
            return None, "not overridable per project: %s" % str(k)[:60]
        if v is None:
            continue                      # None = clear = delete, checked below
        try:
            enc = json.dumps(v)
        except (TypeError, ValueError):
            return None, "value for %s is not JSON" % k
        if len(enc.encode("utf-8")) > MAX_VALUE_BYTES:
            return None, "value for %s exceeds %d bytes" % (k, MAX_VALUE_BYTES)
    return dict(patch), None


def write(project, patch, actor="system", note=None):
    """Set (or, with a None value, CLEAR) project rows. Returns (before, error).

    `before` is the undo handle, and it is a COMPLETE patch over exactly the
    touched keys: a key that was inherited comes back as None, which write()
    reads as "clear". So revert(write(...)) restores INHERITANCE rather than
    pinning the old effective value - those are different states, and conflating
    them is how an "undo" silently freezes a workspace default into a project.
    Same contract as spine/auth/policy.py::swap returning its before-dict, with
    the one addition the extra layer forces.

    The mirror goes into the same append-only sink as every policy swap. It is
    not a second audit path - it is the existing one, called."""
    from spine.storage import db, events
    cleaned, err = validate(patch)
    if err:
        return None, err
    if not project:
        return None, "no project: this value has no per-project layer to write to"

    was = db.project_config_get(project)
    before = {k: was.get(k) for k in cleaned}

    drop = [k for k, v in cleaned.items() if v is None]
    keep = {k: v for k, v in cleaned.items() if v is not None}
    if drop:
        db.project_config_delete(project, drop)
    if keep:
        db.project_config_put(project, keep)

    try:
        after = {k: v for k, v in keep.items()}
        events.emit("reconfig", "-", op="project_config", section=project,
                    actor=actor, before=before, after=after,
                    cleared=sorted(drop), note=note)
    except Exception:                                        # noqa: BLE001
        pass                  # a sink hiccup never blocks the write that landed
    return before, None


def revert(project, before, actor="system", note="revert"):
    """Put a `before` from write() back. It is already a complete patch (None
    where the key was inherited), so this is just write() again - which is the
    point: undo travels the SAME tracked path as the change, and lands in the
    audit as its own entry rather than as a silent rollback."""
    if not before:
        return None, None
    return write(project, before, actor=actor, note=note)
