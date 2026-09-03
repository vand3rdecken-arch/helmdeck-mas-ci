# -*- coding: utf-8 -*-
"""Connector routes (user-built board integrations, see connectors.py's
module docstring for the contract) - Nth slice of server.py's dispatch-table
split (see routes_auth.py for the pattern/rationale). GET /connectors (list
installed connectors + last-run + version count), POST /connectors/<name>/
rollback (restore the previous version, owner/operator only), POST
/connectors/<name>/run (execute now, files backlog cards, owner/operator
only). The rollback/run routes are path-param (parts[0]/parts[2]) so the
`if len(parts) == 3 and parts[0] == "connectors" and parts[2] == ...` guard
stays inline in server.py (same as the /processes/<id>/step precedent noted
in routes_misc.py) - only the route BODY moves here, verbatim. Bodies are
byte-identical to the inline blocks they replace.
"""
import json


def connectors_list_get(self, user):
    from cells.engineer.connectors import connectors
    return self._send(200, json.dumps(connectors.list_connectors()))


def connectors_rollback_post(self, user, name):
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from cells.engineer.connectors import connectors
    from spine.storage import events
    try:
        prev = connectors.rollback(name)
        events.emit("connector", "-", action="rollback", name=name, actor=user["name"])
        return self._send(200, json.dumps({"restored": prev}))
    except Exception as e:
        return self._send(400, json.dumps({"error": str(e)[:300]}))


def connectors_run_post(self, user, name):
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from cells.engineer.connectors import connectors
    try:
        made = connectors.run_connector(name, actor=user["name"])
        return self._send(200, json.dumps({"cards": len(made)}))
    except Exception as e:
        return self._send(400, json.dumps({"error": str(e)[:300]}))


GET_ROUTES = {
    "/connectors": connectors_list_get,
}
