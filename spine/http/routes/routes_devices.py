# -*- coding: utf-8 -*-
"""Device routes (ops/docs/backlog/remote-device-execution) - a team member's
own PC as a card executor. Devices are for the TEAM (owner/operator), never
for `client` - a client is an external party restricted to their own card's
API surface (spine.auth.auth's role model docstring); a device is a trusted
teammate's own machine acting with that teammate's own role. The blanket
client block in server.py do_POST already keeps clients off every route
here (none of these paths are in its allowlist) - no extra check needed for
that, but each handler still verifies device OWNERSHIP (a device belongs to
exactly one user, spine.auth.devices.resolve, same discipline as
spine.auth.auth.owns_card for cards).

  POST /devices/register        {label, billing_scope} -> {id, token}   (owner/operator; billing_scope: "external" default or "shared")
  GET  /devices/mine                    -> [devices]      (owner/operator)
  POST /devices/<id>/revoke                                (owner/operator, own device)
  GET  /devices/<id>/queue              -> card or null    (device's own token)
  POST /devices/<id>/submit     {track, bundle_b64}         (device's own token - must be
                                                              the card's OWN exec_site device)
  POST /devices/reassign        {track, to_device}         (owner/operator recovery: move a
                                                              stuck card to a different OWN
                                                              device, or omit to_device to
                                                              clear it back to a normal card)
"""
import base64
import json
import os
import tempfile


def devices_register_post(self, user, body):
    if user["role"] not in ("owner", "operator"):
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from spine.auth import devices
    label = (body.get("label") or "").strip()
    billing_scope = (body.get("billing_scope") or "external").strip()
    try:
        rec = devices.register(user["name"], label, actor=user["name"],
                               billing_scope=billing_scope)
    except ValueError as e:
        return self._send(400, json.dumps({"error": str(e)}))
    return self._send(200, json.dumps(rec))


def devices_mine_get(self, user):
    if user["role"] not in ("owner", "operator"):
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from spine.auth import devices
    out = [{k: v for k, v in d.items() if k != "token_id"}
           for d in devices.list_devices(user["name"])]
    return self._send(200, json.dumps(out))


def devices_revoke_post(self, user, body, did):
    if user["role"] not in ("owner", "operator"):
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from spine.auth import devices
    if not devices.resolve(user, did):
        return self._send(404, json.dumps({"error": "no such device"}))
    devices.revoke(did, actor=user["name"])
    return self._send(200, json.dumps({"revoked": did}))


def devices_queue_get(self, user, did):
    # Long-poll, same shape as tracks_transcript_live_get: the device holds
    # the connection open rather than tight-polling. user here is whoever
    # the device's OWN token resolved to (spine.auth.auth.resolve already
    # ran in server.py._user() before this handler is reached) - devices.
    # resolve enforces that this specific device belongs to that user.
    import time as _t
    from spine.auth import devices
    from cells.engineer import dispatch
    # Registration already keeps a client from ever OWNING a device
    # (devices_register_post is owner/operator only) - this re-checks role
    # at USE time too, so a user demoted to client after registering a
    # device loses access to it immediately rather than on next re-auth.
    if user["role"] == "client" or not devices.resolve(user, did):
        return self._send(404, json.dumps({"error": "no such device"}))
    devices.touch(did)
    deadline = _t.time() + 20
    t = dispatch.claim_remote_task(did)
    while not t and _t.time() < deadline:
        _t.sleep(0.5)
        t = dispatch.claim_remote_task(did)
    return self._send(200, json.dumps(t))


def devices_submit_post(self, user, body, did):
    from spine.auth import devices
    from cells.engineer import dispatch
    # Same role re-check as devices_queue_get - see its comment.
    if user["role"] == "client" or not devices.resolve(user, did):
        return self._send(404, json.dumps({"error": "no such device"}))
    tid = body.get("track")
    bundle_b64 = body.get("bundle_b64")
    if not tid or not bundle_b64:
        return self._send(400, json.dumps({"error": "track and bundle_b64 required"}))
    try:
        raw = base64.b64decode(bundle_b64)
    except Exception:
        return self._send(400, json.dumps({"error": "bundle_b64 is not valid base64"}))
    fd, path = tempfile.mkstemp(suffix=".bundle")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        # device_id=did: a device may only submit against a card bound to
        # ITSELF (dispatch.submit_remote_result checks exec_site == this
        # device) - resolve() above already proved `did` belongs to `user`,
        # this additionally proves the CARD belongs to `did`.
        result = dispatch.submit_remote_result(tid, path, actor=user["name"], device_id=did)
    except RuntimeError as e:
        return self._send(400, json.dumps({"error": str(e)}))
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return self._send(200, json.dumps(result))


def devices_reassign_post(self, user, body):
    if user["role"] not in ("owner", "operator"):
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from cells.engineer import dispatch
    tid = body.get("track")
    to_device = (body.get("to_device") or "").strip()
    if not tid:
        return self._send(400, json.dumps({"error": "track required"}))
    try:
        result = dispatch.reassign_remote_task(tid, to_device, actor=user["name"])
    except RuntimeError as e:
        return self._send(400, json.dumps({"error": str(e)}))
    return self._send(200, json.dumps(result))


GET_ROUTES = {
    "/devices/mine": devices_mine_get,
}
POST_ROUTES = {
    "/devices/register": devices_register_post,
    "/devices/reassign": devices_reassign_post,
}
