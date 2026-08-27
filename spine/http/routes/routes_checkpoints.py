# -*- coding: utf-8 -*-
"""Checkpoint routes (the program's own undo history, see checkpoints.py's
module docstring) - Nth slice of server.py's dispatch-table split (see
routes_auth.py for the pattern/rationale). GET /checkpoints (list, newest
first), GET /checkpoints/<id>/diff (per-field before->after + connector
add/remove), POST /checkpoints/<id>/restore (owner only - rolls settings.json
+ connectors/ back, itself checkpointed first). The diff/restore routes are
path-param (prefix/suffix or parts[0]/parts[2]) so their guards stay inline
in server.py (same as the /processes/<id>/step precedent noted in
routes_misc.py) - only the route BODY moves here, verbatim. Bodies are
byte-identical to the inline blocks they replace.
"""
import json


def checkpoints_list_get(self, user):
    from spine.ops import checkpoints
    return self._send(200, json.dumps(checkpoints.list_checkpoints()))


def checkpoints_diff_get(self, user, cid):
    # OWNER ONLY (cap settings.read via permissions.PATTERNS), same as restore
    # below. The diff carries settings before->after VALUES, so it hands out
    # relay.sk, glance_token and registration.invite_code to anyone who can
    # read settings - same secret class settings.read already protects.
    from spine.ops import checkpoints
    try:
        return self._send(200, json.dumps(checkpoints.diff(cid)))
    except (RuntimeError, ValueError) as e:
        return self._send(404, json.dumps({"error": str(e)}))


def checkpoints_restore_post(self, user, cid):
    # cap settings.write via permissions.PATTERNS - restore mutates settings.json.
    from spine.ops import checkpoints
    try:
        checkpoints.restore(cid, actor=user["name"])
        return self._send(200, json.dumps({"restored": cid}))
    except Exception as e:
        return self._send(400, json.dumps({"error": str(e)[:300]}))


GET_ROUTES = {
    "/checkpoints": checkpoints_list_get,
}
