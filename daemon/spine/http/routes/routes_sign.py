# -*- coding: utf-8 -*-
"""Signing routes - the only way an approval enters the system.

  GET  /sign/subject/<tid>   what signing this card would commit to
  POST /sign                 {card, meaning, reason, password} -> the record

Deliberate shape:

RE-AUTHENTICATION IS NOT OPTIONAL AND NOT THE SESSION.
    A signature needs the password again at the moment of signing
    (21 CFR 11.200(a)(1)), and it goes through auth.verify_password, which
    mints nothing - login() would create a session and a device token on every
    signature. The lockout applies there too, so this endpoint cannot be used
    as a brute-force oracle once login is rate-limited.

THE SIGNER IS THE AUTHENTICATED USER, NEVER A BODY FIELD.
    routes_policy.py takes its actor from the request body, which is forgeable;
    that pattern must not spread to the one record whose entire value is who
    signed it. `user["name"]` or nothing.

SIGNING DOES NOT ACCEPT THE CARD.
    This writes a record. The lane machine independently refuses to land an
    in-scope card without a valid one. Two steps on purpose: the human decides,
    the machine verifies - and a signature that never gets used stays on the
    card as evidence that someone approved something that then drifted.
"""
import json


def sign_subject_get(self, user, tid):
    from daemon.spine.auth import signatures
    from daemon.spine.storage.trackstore import _load, _find
    t = _find(_load(), tid)
    if not t:
        return self._send(404, json.dumps({"error": "no such card"}))
    from daemon import gxp
    subj, why = signatures.subject(t)
    return self._send(200, json.dumps({
        "card": tid,
        "in_scope": gxp.in_scope(t),
        "four_eyes": gxp.four_eyes(),
        "dispatched_by": t.get("dispatched_by"),
        "signer": {"name": user["name"], "role": user["role"]},
        "subject": subj, "blocked": why,
        "signatures": t.get("signatures") or [],
    }))


def sign_post(self, user, body):
    from daemon.spine.auth import auth, signatures
    from daemon.spine.storage import events
    from daemon.spine.storage.trackstore import _find, _load, _mutate

    tid = (body.get("card") or "").strip()
    meaning = (body.get("meaning") or "").strip()
    reason = body.get("reason") or ""
    password = body.get("password") or ""

    t = _find(_load(), tid)
    if not t:
        return self._send(404, json.dumps({"error": "no such card"}))
    if meaning not in signatures.MEANINGS:
        return self._send(400, json.dumps(
            {"error": "meaning must be one of %s" % (signatures.MEANINGS,)}))

    # The subject is computed HERE, server-side, from git - never taken from
    # the request. A client-supplied commit id would let a signature name a
    # state the signer never saw, which is the one thing the binding exists to
    # prevent.
    subj, why = signatures.subject(t)
    if why:
        return self._send(409, json.dumps({"error": why}))

    if not auth.verify_password(user["name"], password):
        # 401 and a flat message: the audit distinguishes wrong-password from
        # locked-out, the response does not.
        return self._send(401, json.dumps({"error": "password not accepted"}))

    try:
        sig = signatures.create(t, user["name"], user["role"], meaning, reason, subj)
    except ValueError as e:
        return self._send(400, json.dumps({"error": str(e)}))

    def _append(tt):
        tt.setdefault("signatures", []).append(sig)
    _mutate(tid, _append)

    events.emit("signature", tid, op="signed", actor=user["name"],
                role=user["role"], meaning=meaning, reason=sig["reason"],
                at_utc=sig["signed_at"], head=subj["head"], base=subj["base"],
                seq=sig["seq"])

    # A rejection is an instruction, not a dead end: send it back to the worker
    # so the reason becomes the next turn's brief instead of dying in the log.
    if meaning == "rejected":
        try:
            from daemon.cells.engineer import sessions
            sessions.move_lane(tid, "working", actor=user["name"])
            if sig["reason"]:
                sessions.steer(tid, "Freigabe abgelehnt: " + sig["reason"],
                               actor=user["name"], source="gxp-rejection")
        except Exception as e:
            print("sign: rejection follow-up failed:", e)

    return self._send(200, json.dumps({"ok": True, "signature": sig}))
