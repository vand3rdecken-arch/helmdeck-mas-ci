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


GET_ROUTES = {
    "/projects": projects_list_get,
}
POST_ROUTES = {
    "/projects": projects_new_post,
}
GET_CAPS = {
    "/projects": "projects.view",
}
POST_CAPS = {
    "/projects": "projects.manage",
}
# projects_update_post/projects_delete_post (/projects/<id>/update,
# /projects/<id>/delete) are path-param routes - see permissions.PATTERNS.
