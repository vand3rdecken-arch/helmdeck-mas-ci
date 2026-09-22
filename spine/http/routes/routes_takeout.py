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
        _escalate_failure(user, e, account)
    try:
        from spine.storage import events
        events.emit("takeout", "-", op="export", actor=user,
                    state=_job["state"], box=_job.get("box"))
    except Exception:                                            # noqa: BLE001
        pass



def _facts():
    """What a diagnosis actually needs, gathered by CODE. Henry should reason
    about the failure, not go hunting for the same five numbers every time -
    and a fact the harness can measure must never be something the model
    guesses at (EVIDENCE law)."""
    import shutil
    out = {}
    root = _tool()[1]
    try:
        total, _used, free = shutil.disk_usage(root)
        out["disk_free_mb"] = round(free / 1e6)
        out["disk_total_mb"] = round(total / 1e6)
    except OSError:
        pass
    try:
        out["db_mb"] = round(os.path.getsize(
            os.path.join(root, "daemon", "helmdeck.db")) / 1e6)
    except OSError:
        pass
    box = os.path.join(root, "daemon", "takeout")
    try:
        out["existing_archives"] = len(os.listdir(box)) if os.path.isdir(box) else 0
    except OSError:
        pass
    return out


def _escalate_failure(user, exc, account):
    """Hand the failure to the broker. Best-effort by contract: an escalation
    that itself raises must not become a second, quieter failure."""
    try:
        from spine.registry import escalations
        facts = _facts()
        detail = ("Archiv-Export fehlgeschlagen fuer %s.\nFehler: %s\nFakten: %s\n"
                  "Das Archiv ist der Umzugs- und Sicherungsweg; ein halb "
                  "geschriebener Behaelter wird von takeout.py --verify erkannt "
                  "(fehlender Vollstaendigkeitsmarker), ist aber NICHT brauchbar. "
                  "Sag dem Owner in einem Satz, woran es lag und was er tun "
                  "soll; wenn die Ursache behebbar ist (Platz, Pfad, "
                  "gesperrte Datei), behebe sie und starte den Export neu."
                  % (account or "den ganzen Workspace", str(exc)[:400], facts))
        escalations.emit("takeout_failed", None, detail)
    except Exception as e:                                       # noqa: BLE001
        print("takeout: escalation failed - %s" % str(e)[:160])

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



# ---------------------------------------------------------------------------
# IMPORT FROM ANOTHER SYSTEM. Owner 2026-09-22: "if users only used claude or
# other system let him pull this from other systems as well". This is the
# other half of "seamless": a takeout archive covers a HelmDeck user moving
# machines, but the far more common arrival is someone with months of Claude
# Code or Cursor notes and no HelmDeck at all.

def foreign_get(self, user):
    """What is importable on THIS machine, and - equally - what is not.

    The absent list is not padding. A Cursor user who sees no mention of
    Cursor cannot tell whether we looked; at first run he has no way to
    check, and a silent empty result is exactly the failure this card exists
    to end."""
    from spine.memory import foreign
    from spine.storage import events
    repo = (events.settings().get("default_repo") or "").strip() or None
    found, absent = foreign.discover(repo=repo)
    return self._send(200, json.dumps({"ok": True, "sources": found,
                                       "absent": absent}, ensure_ascii=False))


def foreign_import_post(self, user, body):
    """Import ONE source. `dry` previews with the same code path that writes,
    so a preview can never promise something the import does not do."""
    from spine.memory import foreign
    from spine.storage import events
    want = (body.get("id") or "").strip()
    if not want:
        return self._send(400, json.dumps({"ok": False, "error": "welche Quelle?"}))
    repo = (events.settings().get("default_repo") or "").strip() or None
    found, _absent = foreign.discover(repo=repo)
    src = next((s for s in found if s["id"] == want), None)
    if not src:
        return self._send(404, json.dumps(
            {"ok": False, "error": "Quelle nicht (mehr) da: %s" % want}))
    res = foreign.import_source(src, actor=user or "owner",
                                dry_run=bool(body.get("dry")))
    return self._send(200, json.dumps({"ok": True, "source": src["label"],
                                       "result": res}, ensure_ascii=False))

def foreign_scan_post(self, user, body):
    """The AGENT pass, and it is EXPLICIT on purpose.

    Measured 2026-09-22: ~30 s, against milliseconds for the adapters. A step
    that slow must never sit in the fast path of a screen someone is waiting
    on - it is an extra button, not a default. It returns only what the
    adapters did NOT already know, so a machine we fully understand shows an
    honest zero rather than a padded list."""
    from spine.memory import foreign
    from spine.storage import events
    repo = (events.settings().get("default_repo") or "").strip() or None
    known = [s["path"] for s in foreign.discover(repo=repo)[0]]
    hits, problems = foreign.discover_with_agent(known_paths=known)
    return self._send(200, json.dumps({"ok": True, "sources": hits,
                                       "problems": problems}, ensure_ascii=False))


GET_ROUTES = {"/takeout": takeout_status_get,
              "/memory/foreign": foreign_get}
POST_ROUTES = {"/takeout/start": takeout_start_post,
               "/takeout/verify": takeout_verify_post,
               "/memory/foreign/import": foreign_import_post,
               "/memory/foreign/scan": foreign_scan_post}
# settings.read is the ceiling of the closed vocabulary; the handlers narrow
# it further themselves (scope per account, owner gets everything) exactly
# like /harness/export does. Restoring is NOT a route: it replaces the whole
# db and must be a deliberate act at the machine, not a button on a phone.
GET_CAPS = {"/takeout": "settings.read",
            "/memory/foreign": "settings.read"}
POST_CAPS = {"/takeout/start": "settings.read",
             "/takeout/verify": "settings.read",
             # writes into the caller own memory only
             "/memory/foreign/import": "settings.write",
             # read-only: the agent looks, it does not write
             "/memory/foreign/scan": "settings.read"}
