# -*- coding: utf-8 -*-
"""Control/teach routes (screen-recording demo capture) - eighth slice of
server.py's dispatch-table split (see routes_auth.py for the pattern/
rationale). GET /control/state (current TeachSession + background job names),
POST /control/teach/start, POST /control/teach/stop, POST /control/distill
(demo -> playbook, backgrounded), POST /control/demo (scripted browser demo,
backgrounded). `_ctl`/`_ctl_lock`/`_bg` stay in server.py since they are
shared module state used by many other routes too (steer/answer/dispatch/
gate/nightshift-plan) - reached via a lazy `import server` (no cycle:
resolved at call time). Bodies are byte-identical to the inline blocks they
replace.
"""
import json


def control_state_get(self, user):
    from spine.http import server
    with server._ctl_lock:
        s = server._ctl["teach"]
        return self._send(200, json.dumps(
            {"teach": s.rid if s and not s.stopped.is_set() else None,
             "busy": list(server._ctl["busy"])}))


def control_teach_start_post(self, user, body):
    from spine.http import server
    from spine.ops.teach import TeachSession
    with server._ctl_lock:
        if server._ctl["teach"] and not server._ctl["teach"].stopped.is_set():
            return self._send(409, json.dumps({"error": "already recording",
                                               "id": server._ctl["teach"].rid}))
        s = TeachSession(body.get("title") or "unnamed task").start()
        server._ctl["teach"] = s
    return self._send(200, json.dumps({"id": s.rid}))


def control_teach_stop_post(self, user, body):
    from spine.http import server
    with server._ctl_lock:
        s = server._ctl["teach"]
    if not s:
        return self._send(404, json.dumps({"error": "not recording"}))
    rid = s.stop()
    return self._send(200, json.dumps({"id": rid}))


def control_distill_post(self, user, body):
    import os
    from spine.http import server
    rid = os.path.basename(body.get("id") or "")
    if not rid:
        return self._send(400, json.dumps({"error": "id required"}))
    from spine.ops.distill import distill
    server._bg("distill:" + rid, lambda: distill(rid))
    return self._send(200, json.dumps({"started": rid}))


def control_demo_post(self, user, body):
    import swarm
    from spine.http import server
    server._bg("demo", swarm.browser_demo)
    return self._send(200, json.dumps({"started": "browser-demo"}))


GET_ROUTES = {
    "/control/state": control_state_get,
}
POST_ROUTES = {
    "/control/teach/start": control_teach_start_post,
    "/control/teach/stop": control_teach_stop_post,
    "/control/distill": control_distill_post,
    "/control/demo": control_demo_post,
}
