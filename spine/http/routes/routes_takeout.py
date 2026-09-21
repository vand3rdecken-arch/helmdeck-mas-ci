# -*- coding: utf-8 -*-
"""Takeout as a FEATURE: start it, watch it, list what exists, restore one.

Owner 2026-09-21: "needs to be like actual feature with ui and all". The
engine already existed and was tested (ops/tools/takeout.py); this is the half
that makes it a product - routes with capabilities, a job that runs in the
background because a real export takes tens of seconds, and a status a screen
can poll.

TWO THINGS THAT ARE NOT NEGOTIABLE HERE.

1. ONE JOB AT A TIME, per process. Two exports writing at once would produce
   two containers from two different moments and the second would silently
   win the "latest" position. The guard is a lock plus a running flag, and a
   second start is REFUSED with the id of the one already running - not
   queued, not ignored.

2. SCOPE IS PER ACCOUNT unless the caller is the owner. db_export takes
   `--account`, and a product where any operator can export every account's
   chat and memory is not a takeout, it is a data leak with a button. The
   owner gets everything; everyone else gets their own rows. This is enforced
   HERE, not in the UI - a screen that hides a button is not a permission.
"""
import json
import os
import threading
import time

_lock = threading.Lock()
_job = {"state": "idle", "id": None, "started": 0, "finished": 0,
        "box": None, "error": None, "parts": {}, "notes": []}


def _tool():
    import importlib.util
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    spec = importlib.util.spec_from_file_location(
        "takeout", os.path.join(root, "ops", "tools", "takeout.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, root


def _is_owner(user):
    try:
        from spine.auth import auth
        return (auth.role_of(user) or "") == "owner"
    except Exception:                                            # noqa: BLE001
        return False


def _run(user, with_recordings, account):
    mod, root = _tool()
    try:
        box, man = mod.build(os.path.join(root, "daemon", "takeout"),
                             with_recordings=with_recordings, account=account)
        with _lock:
            _job.update(state="done", finished=time.time(), box=box,
                        parts=man.get("parts") or {}, notes=man.get("notes") or [])
    except Exception as e:                                       # noqa: BLE001
        with _lock:
            _job.update(state="failed", finished=time.time(), error=str(e)[:400])
    try:
        from spine.storage import events
        events.emit("takeout", "-", op="export", actor=user,
                    state=_job["state"], box=_job.get("box"))
    except Exception:                                            # noqa: BLE001
        pass


def takeout_status_get(self, user):
    """What the screen polls. Also lists the containers already on disk, so a
    fresh session after a restart still SEES yesterday's archive instead of
    an empty page that reads as 'you have no backup'."""
    mod, root = _tool()
    base = os.path.join(root, "daemon", "takeout")
    boxes = []
    if os.path.isdir(base):
        for name in sorted(os.listdir(base), reverse=True)[:20]:
            box = os.path.join(base, name)
            man = os.path.join(box, mod.MANIFEST)
            if not os.path.isfile(man):
                continue
            try:
                m = json.load(open(man, encoding="utf-8"))
            except ValueError:
                boxes.append({"name": name, "broken": "manifest unlesbar"})
                continue
            size = sum((p.get("bytes") or 0) for p in (m.get("parts") or {}).values())
            boxes.append({"name": name, "created": m.get("created"),
                          "bytes": size, "complete": bool(m.get("complete")),
                          "parts": m.get("parts") or {},
                          "not_included": m.get("not_included") or []})
    with _lock:
        job = dict(_job)
    return self._send(200, json.dumps(
        {"ok": True, "job": job, "boxes": boxes,
         "handover": [{"what": w, "why": y} for w, y in mod.HANDOVER]},
        ensure_ascii=False))


def takeout_start_post(self, user, body):
    with _lock:
        if _job["state"] == "running":
            return self._send(409, json.dumps(
                {"ok": False, "error": "laeuft bereits", "id": _job["id"]}))
        _job.update(state="running", id=str(int(time.time())), started=time.time(),
                    finished=0, box=None, error=None, parts={}, notes=[])
    # Owner exports the whole workspace; anyone else only their own rows.
    account = None if _is_owner(user) else user
    from spine.ops import bgthread
    bgthread.spawn("takeout", lambda: _run(user, bool(body.get("recordings")),
                                           account))
    with _lock:
        return self._send(200, json.dumps({"ok": True, "id": _job["id"],
                                           "scope": account or "workspace"}))


def takeout_verify_post(self, user, body):
    mod, root = _tool()
    name = (body.get("name") or "").strip()
    box = os.path.join(root, "daemon", "takeout", os.path.basename(name))
    if not name or not os.path.isdir(box):
        return self._send(404, json.dumps({"ok": False, "error": "kein solches Archiv"}))
    problems = mod.verify(box)
    return self._send(200, json.dumps({"ok": not problems, "problems": problems},
                                      ensure_ascii=False))


GET_ROUTES = {"/takeout": takeout_status_get}
POST_ROUTES = {"/takeout/start": takeout_start_post,
               "/takeout/verify": takeout_verify_post}
# settings.read is the ceiling of the closed vocabulary; the handlers narrow
# it further themselves (scope per account, owner gets everything) exactly
# like /harness/export does. Restoring is NOT a route: it replaces the whole
# db and must be a deliberate act at the machine, not a button on a phone.
GET_CAPS = {"/takeout": "settings.read"}
POST_CAPS = {"/takeout/start": "settings.read",
             "/takeout/verify": "settings.read"}
