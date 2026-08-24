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


def _sign_one(user, tid, meaning, reason, password):
    """Produce and store ONE signature. Password already verified by the caller;
    it is passed through because an APPROVAL also unlocks the user's signing
    key (signkeys.py) - the password is cryptographically required for the
    tag, not merely checked against a hash.

    Split out so the batch route cannot drift from the single route - one
    implementation of "what a signature is", two ways in.
    """
    from daemon.spine.auth import signatures
    from daemon.spine.storage import events
    from daemon.spine.storage.trackstore import _find, _load, _mutate

    t = _find(_load(), tid)
    if not t:
        return {"card": tid, "ok": False, "error": "no such card"}
    if meaning not in signatures.MEANINGS:
        return {"card": tid, "ok": False,
                "error": "meaning must be one of %s" % (signatures.MEANINGS,)}
    subj, why = signatures.subject(t)
    if why:
        return {"card": tid, "ok": False, "error": why}
    try:
        sig = signatures.create(t, user["name"], user["role"], meaning, reason, subj)
    except ValueError as e:
        return {"card": tid, "ok": False, "error": str(e)}

    # APPROVED gets the independently verifiable anchor: a GPG-signed git tag
    # an auditor checks with stock `git verify-tag` + the exported public key,
    # no HelmDeck code in the loop. STRICT on purpose: an approval that could
    # not be anchored is refused outright, because "signed, but you have to
    # trust our database about it" is exactly the gap the tag closes - a soft
    # fallback here would quietly reopen it. reviewed/rejected stay
    # record-only: they authorise nothing, so they need no anchor.
    if meaning == "approved":
        from daemon.spine.auth import signkeys
        manifestation = {"card": tid, "actor": sig["actor"],
                         "role": sig["actor_role"], "meaning": meaning,
                         "reason": sig["reason"], "signed_at": sig["signed_at"],
                         "head": subj["head"], "base": subj["base"]}
        try:
            tag_name, tag_sha, fpr = signkeys.create_approval_tag(
                t["repo"], tid, sig["seq"], subj["head"], user["name"],
                password, manifestation)
        except Exception as e:
            return {"card": tid, "ok": False,
                    "error": "approval tag failed: %s" % str(e)[:200]}
        sig["git"] = {"tag": tag_name, "tag_sha": tag_sha,
                      "fingerprint": fpr, "merge_sha": None}

    def _append(tt):
        tt.setdefault("signatures", []).append(sig)
    _mutate(tid, _append)

    # tag_sha in the event = the cross-witness (gxp-mode-design.md 2.0): the
    # sink names the tag, the tag names the card - editing either store now
    # contradicts the other.
    events.emit("signature", tid, op="signed", actor=user["name"],
                role=user["role"], meaning=meaning, reason=sig["reason"],
                at_utc=sig["signed_at"], head=subj["head"], base=subj["base"],
                seq=sig["seq"], tag=sig.get("git", {}).get("tag"),
                tag_sha=sig.get("git", {}).get("tag_sha"))
    if meaning == "rejected":
        _reject_followup(tid, user["name"], sig["reason"])
    return {"card": tid, "ok": True, "signature": sig}


def _reject_followup(tid, actor, reason):
    """A rejection is an instruction, not a dead end: back to working, and the
    reason becomes the worker's next brief instead of dying in the log."""
    try:
        from daemon.cells.engineer import sessions
        sessions.move_lane(tid, "working", actor=actor)
        if reason:
            sessions.steer(tid, "Freigabe abgelehnt: " + reason,
                           actor=actor, source="gxp-rejection")
    except Exception as e:
        print("sign: rejection follow-up failed:", tid, e)


def sign_batch_post(self, user, body):
    """Sign SEVERAL cards with ONE password entry.

    21 CFR 11.200 speaks of a SERIES of signings, and batch approval with a
    single credential entry is established practice in regulated document and
    LIMS systems - provided every record gets its own full manifestation (name,
    UTC time, meaning) and the signer sees each item at signing time. Both hold
    here: one password check, N independent records, each bound to its own
    commit pair.

    Not all-or-nothing. A card that drifted since the list was drawn fails on
    its own and the rest still land - forcing the whole batch to fail because
    one branch moved would train people to re-sign blindly.
    """
    from daemon.spine.auth import auth

    items = body.get("cards") or []
    if not isinstance(items, list) or not items:
        return self._send(400, json.dumps({"error": "no cards given"}))
    if len(items) > 50:
        return self._send(400, json.dumps({"error": "at most 50 cards at a time"}))
    if not auth.verify_password(user["name"], body.get("password") or ""):
        return self._send(401, json.dumps({"error": "password not accepted"}))

    results = [_sign_one(user, (it.get("card") or "").strip(),
                         (it.get("meaning") or "").strip(), it.get("reason") or "",
                         body.get("password") or "")
               for it in items]
    return self._send(200, json.dumps({"results": results}))


def sign_post(self, user, body):
    """Sign ONE card. Shares _sign_one with the batch route, so there is exactly
    one implementation of what a signature is."""
    from daemon.spine.auth import auth

    if not auth.verify_password(user["name"], body.get("password") or ""):
        # 401 and a flat message: the audit distinguishes wrong-password from
        # locked-out, the response does not.
        return self._send(401, json.dumps({"error": "password not accepted"}))

    r = _sign_one(user, (body.get("card") or "").strip(),
                  (body.get("meaning") or "").strip(), body.get("reason") or "",
                  body.get("password") or "")
    if not r["ok"]:
        # 409 for "the card is not in a signable state" (uncommitted work, drift),
        # 404 for a card that is not there, 400 for a bad request.
        err = r["error"]
        code = 404 if "no such card" in err else 400 if "meaning must be" in err else 409
        return self._send(code, json.dumps({"error": err}))
    return self._send(200, json.dumps({"ok": True, "signature": r["signature"]}))
