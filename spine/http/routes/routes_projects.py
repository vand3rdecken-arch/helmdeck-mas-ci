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


GET_ROUTES = {
    "/projects": projects_list_get,
    "/repo/templates": repo_templates_get,
}
POST_ROUTES = {
    "/projects": projects_new_post,
    "/repo/template": repo_template_post,
}
GET_CAPS = {
    "/projects": "projects.view",
    "/repo/templates": "projects.view",
}
POST_CAPS = {
    "/projects": "projects.manage",
    "/repo/template": "projects.manage",
}
# projects_update_post/projects_delete_post (/projects/<id>/update,
# /projects/<id>/delete) are path-param routes - see permissions.PATTERNS.
