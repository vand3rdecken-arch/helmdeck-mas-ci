# -*- coding: utf-8 -*-
"""Project routes (client/billing containers tracks can belong to) - Nth
slice of server.py's dispatch-table split (see routes_auth.py for the
pattern/rationale). GET /projects (list, owner/operator only), POST
/projects (create, owner only), POST /projects/<id>/update, POST
/projects/<id>/delete. The update/delete routes are path-param (parts[0]/
parts[2]) so their guard stays inline in server.py (same as the
/processes/<id>/step precedent noted in routes_misc.py) - only the route
BODY moves here, verbatim. Bodies are byte-identical to the inline blocks
they replace.
"""
import json


def projects_list_get(self, user):
    from spine.ops import projects
    return self._send(200, json.dumps(projects.list_projects()))


def projects_new_post(self, user, body):
    from spine.ops import projects
    try:
        return self._send(200, json.dumps(projects.new_project(
            body.get("name"), body.get("billing"), client=body.get("client", ""),
            fixed_price=body.get("fixed_price"), rate=body.get("rate"),
            actor=user["name"])))
    except (ValueError, TypeError) as e:
        return self._send(400, json.dumps({"error": str(e)}))


def projects_update_post(self, user, body, pid):
    from spine.ops import projects
    try:
        return self._send(200, json.dumps(
            projects.update_project(pid, body, actor=user["name"])))
    except (RuntimeError, ValueError) as e:
        return self._send(400, json.dumps({"error": str(e)}))


def projects_delete_post(self, user, body, pid):
    from spine.ops import projects
    try:
        return self._send(200, json.dumps(
            projects.delete_project(pid, actor=user["name"])))
    except RuntimeError as e:
        return self._send(400, json.dumps({"error": str(e)}))


# ---------------------------------------------------------------------------
# THE REPO HALF of the project record (owner decree 2026-08-30: a repo IS a
# project). Both routes live here rather than beside /loop/map because they read
# and write the SAME record the routes above do - splitting them across two
# files is how a second edit place gets built by accident.
# ---------------------------------------------------------------------------
def repo_templates_get(self, user):
    """The repo-type catalog + every repo HelmDeck knows, with its chosen type.

    ONE payload for the onboarding picker, because the picker is useless with
    half of it: it needs the types on offer AND which repos have not chosen one.

    Adoption of the pre-record repo mentions (pm.repos / repo_hooks keys /
    default_repo) happens here rather than in a boot sweep: opening this screen
    IS the sighting, and folding it in at that moment is what lets the registry
    be the only source of a repo list from then on."""
    from cells.engineer.cards import sessions
    from spine.ops import projects
    from spine.registry import templates
    projects.adopt_settings_repos(actor=user["name"])
    return self._send(200, json.dumps({
        "templates": templates.catalog(),
        "repos": [projects.resolve(r) for r in projects.known_repos()],
        # sent so the picker cannot hard-code which stations a template is even
        # allowed to switch - the honest list lives in sessions.py and there is
        # deliberately no second copy of it in the client
        "switchable": list(sessions.SWITCHABLE_STATIONS),
        "stations": list(sessions.STATIONS),
    }, ensure_ascii=False))


def repo_template_post(self, user, body):
    """Choose the repo type. THE write path for `template` - the very mutator
    Henry's chat verb calls, so the screen and the chat cannot disagree."""
    from spine.ops import projects
    repo = body.get("repo") or ""
    try:
        projects.apply_template(repo, body.get("template") or "", actor=user["name"])
        return self._send(200, json.dumps(projects.resolve(repo), ensure_ascii=False))
    except (ValueError, RuntimeError) as e:
        return self._send(400, json.dumps({"error": str(e)}, ensure_ascii=False))


def projects_shared_get(self, user):
    """Project folders for the room: what THIS account may see of them. An
    account that is not the owner gets only the projects shared with it, each
    with its cards as the whitelisted summary (auth.shared_view) - no repo
    path, no billing. The owner gets every project with its share list, so the
    room can offer the toggle. Cards are read from the record at request time."""
    from spine.auth import auth
    from spine.ops import projects
    from spine.storage import db
    owner = user.get("role") == "owner"
    mine = projects.list_projects() if owner else projects.shared_with(user["name"])
    tracks = db.tracks_all() or []
    out = []
    for p in mine:
        key = projects.repo_key(p.get("repo"))
        cards = [t for t in tracks if key and projects.repo_key(t.get("repo")) == key
                 and not t.get("archived") and not t.get("board_hidden")]
        cards.sort(key=lambda t: t.get("updated") or t.get("created") or "", reverse=True)
        out.append({"id": p["id"], "name": p["name"],
                    "geteilt_mit": list(p.get("geteilt_mit") or []),
                    "cards": [auth.shared_view(t) for t in cards[:60]],
                    "card_count": len(cards)})
    out.sort(key=lambda x: x["name"].lower())
    return self._send(200, json.dumps(out, ensure_ascii=False))


def projects_share_post(self, user, body):
    from spine.ops import projects
    try:
        p = projects.share(body.get("id", ""), add=body.get("add") or [],
                           remove=body.get("remove") or [], actor=user["name"])
    except ValueError as e:
        return self._send(400, json.dumps({"error": str(e)}))
    if p is None:
        return self._send(404, json.dumps({"error": "unknown project"}))
    return self._send(200, json.dumps({"id": p["id"], "geteilt_mit": p.get("geteilt_mit") or []}))


def projects_folder_post(self, user, body):
    """Register a FOLDER on this machine as a project (the way a repo becomes
    known: projects.sight_repo, THE door in). The room panel offers it so a
    folder like "Immobilien" can be shown to someone without filing a card
    first. The folder must exist; a name is optional (default: its folder name)."""
    import os
    from spine.ops import projects
    path = projects.norm_repo(body.get("path") or "")
    if not path or not os.path.isdir(path):
        return self._send(400, json.dumps({"error": "Ordner nicht gefunden: %s" % (body.get("path") or "")},
                                          ensure_ascii=False))
    name = (body.get("name") or "").strip()[:60]
    p = projects.sight_repo(path, actor=user["name"], name=name)
    return self._send(200, json.dumps({"id": p["id"], "name": p["name"]}, ensure_ascii=False))


BROWSE_MAX = 400


def _drives():
    import os
    return [d for d in ("%s:\\" % c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ") if os.path.isdir(d)]


def projects_browse_get(self, user):
    """The folder picker's one read: the sub-FOLDERS of `path` on this machine
    (names only - never files, never contents), its parent, and the drive roots
    on Windows. Empty path = the owner's home. Hidden/system names are skipped.
    Capability projects.manage (owner): the same account that already has the
    machine tools; a guest never reaches the filesystem through it."""
    import os
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(self.path).query)
    raw = (q.get("path") or [""])[0].strip()
    path = os.path.abspath(raw) if raw else os.path.expanduser("~")
    out = {"path": path, "parent": "", "dirs": [], "drives": _drives() if os.name == "nt" else []}
    parent = os.path.dirname(path.rstrip(os.sep + "/"))
    if parent and parent != path.rstrip(os.sep + "/"):
        out["parent"] = parent
    if not os.path.isdir(path):
        out["error"] = "Ordner nicht gefunden"
        return self._send(200, json.dumps(out, ensure_ascii=False))
    try:
        names = [n for n in os.listdir(path)
                 if not n.startswith((".", "$")) and os.path.isdir(os.path.join(path, n))]
    except OSError as e:
        out["error"] = "Kein Zugriff: %s" % str(e)[:80]
        return self._send(200, json.dumps(out, ensure_ascii=False))
    names.sort(key=str.lower)
    out["dirs"] = names[:BROWSE_MAX]
    out["truncated"] = len(names) > BROWSE_MAX
    return self._send(200, json.dumps(out, ensure_ascii=False))


GET_ROUTES = {
    "/projects": projects_list_get,
    "/projects/browse": projects_browse_get,
    "/projects/shared": projects_shared_get,
    "/repo/templates": repo_templates_get,
}
POST_ROUTES = {
    "/projects": projects_new_post,
    "/projects/share": projects_share_post,
    "/projects/folder": projects_folder_post,
    "/repo/template": repo_template_post,
}
GET_CAPS = {
    "/projects": "projects.view",
    "/repo/templates": "projects.view",
    "/projects/browse": "projects.manage",
}
POST_CAPS = {
    "/projects": "projects.manage",
    "/projects/share": "projects.manage",
    "/projects/folder": "projects.manage",
    "/repo/template": "projects.manage",
}
# projects_update_post/projects_delete_post (/projects/<id>/update,
# /projects/<id>/delete) are path-param routes - see permissions.PATTERNS.
