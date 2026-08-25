# -*- coding: utf-8 -*-
"""Device registry - a thin metadata layer on top of auth.py's existing
device tokens, not a new identity system. issue_token()/resolve() already
turn a bearer credential into `{"name", "role"}`; a device's HTTP calls are
authenticated AS the user who registered it, for free. What auth.py does NOT
know is "this token is Alice's laptop, and it executes remote cards" - that
mapping lives here, in daemon/devices.json (git-ignored runtime data, same
tier as users.json/helmdeck.db).

A device inherits its owner's role. There is no separate "device role" -
registering a device does not grant capability beyond what the owning user
already has (spine/registry/debt.py machine-task-blast-radius names exactly
this risk for the machine-task roles list; devices.py does not repeat it -
device work is ALWAYS the normal gated worktree/branch path, never
machine/direct/fast-track, see cells/engineer/dispatch.py's new_remote_task).
"""
import json
import os
import secrets
import time

from daemon.paths import DAEMON_ROOT as ROOT

DEVICES = os.path.join(ROOT, "devices.json")


def _load():
    if not os.path.exists(DEVICES):
        return []
    try:
        with open(DEVICES, encoding="utf-8") as f:
            return json.load(f)
    except ValueError:
        return []


def _save(devices):
    tmp = DEVICES + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(devices, f, indent=2)
    os.replace(tmp, DEVICES)


def register(owner_name, label, actor=None, billing_scope="external"):
    """Mint a device token (via auth.issue_token, so it is hashed at rest
    the same way every other device credential is - devices.py never stores
    or sees the plaintext beyond this one return) and record its metadata.
    Returns {id, token} - the token is returned HERE AND NOWHERE ELSE, same
    rule as auth.issue_token itself.

    billing_scope: "external" (default) - this device's own Claude account/
    subscription pays for its turns, NOT the daemon's. spine.storage.events'
    ai_billing/plan_calibration is workspace-global, calibrated against ONE
    account's quota (debt ai-billing-workspace-global/plan-share-
    calibration) - an "external" device's usage must never be folded into
    that pool once real usage capture exists (ops/docs/backlog/
    remote-device-execution/PLAN-hardening.md, Phase D). "shared" is the
    only other value: the daemon's own account/API key is used remotely
    (e.g. a company-provisioned box), so ITS usage DOES belong in the
    shared pool like a local card's. Recorded now, before Phase D needs it,
    so that work has a field to key off instead of a schema migration."""
    if billing_scope not in ("external", "shared"):
        raise ValueError("billing_scope must be 'external' or 'shared'")
    from spine.auth import auth
    if not auth.get_user(owner_name):
        raise ValueError("no such user: %s" % owner_name)
    token = auth.issue_token(owner_name, "device:" + (label or "device"),
                             actor=actor or owner_name)
    did = secrets.token_hex(8)
    devices = _load()
    devices.append({
        "id": did, "owner": owner_name, "label": label or "device",
        "token_id": auth._token_hash(token)[:12],
        "billing_scope": billing_scope,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "last_seen": None,
    })
    _save(devices)
    return {"id": did, "token": token}


def list_devices(owner_name=None):
    devices = _load()
    if owner_name:
        devices = [d for d in devices if d["owner"] == owner_name]
    return devices


def get_device(did):
    return next((d for d in _load() if d["id"] == did), None)


def touch(did):
    devices = _load()
    for d in devices:
        if d["id"] == did:
            d["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _save(devices)
            return


def revoke(did, actor=None):
    devices = _load()
    d = next((x for x in devices if x["id"] == did), None)
    if not d:
        raise ValueError("no such device: %s" % did)
    from spine.auth import auth
    u = auth.get_user(d["owner"])
    if u:
        for t in list(u.get("tokens") or []):
            if t.get("id") == d["token_id"]:
                auth.revoke_token(d["owner"], t["id"], actor=actor or d["owner"])
    _save([x for x in devices if x["id"] != did])


def resolve(user, did):
    """(device or None). A device belongs to exactly one user - even an
    owner/operator may not reach another user's device by id, same
    ownership discipline as auth.owns_card for cards."""
    d = get_device(did)
    if not d or not user or d["owner"] != user.get("name"):
        return None
    return d
