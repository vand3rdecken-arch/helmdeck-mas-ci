# -*- coding: utf-8 -*-
"""Misc small routes - seventh slice of server.py's dispatch-table split (see
routes_auth.py for the pattern/rationale). GET /processes (list, syncing
first), POST /processes/new (file a request), GET /me (identity + the PUBLIC
UI policy every role needs - lang, lane labels, ai_billing mode). The nested
/processes/<id>/step sub-router (path-param dispatch, not exact-match) stays
inline for now - a future slice. Bodies are byte-identical to the inline
blocks they replace.
"""
import json


def processes_get(self, user):
    from cells.process import processes
    try:
        processes.sync()
    except Exception:
        pass
    return self._send(200, json.dumps(processes.list_processes(
        client=user["name"] if user["role"] == "client" else None)))


def me_get(self, user):
    # Carries the PUBLIC UI policy, not just the identity: the
    # workspace language (and the lane labels the board renders) has
    # to reach EVERY role, or the app is German for an operator and
    # English for the owner - exactly the split this replaced.
    # /dashboard/data can't serve it: it strips settings for
    # non-owners and 403s clients. Whitelisted, never the whole
    # settings blob - that stays owner-only.
    from spine.storage import events, userconfig
    from spine.auth import permissions
    pol = events.settings().get("policy") or {}
    profile = userconfig.resolve(user["name"])
    return self._send(200, json.dumps({
        "name": user["name"], "role": user["role"],
        # Card 4 (ops/docs/backlog/rbac-gxp): the app's ONE source for "what
        # may I see/do" - derived live from permissions.matrix() every call,
        # never cached here or in the client beyond a query invalidation on
        # login/role-change. Nav renders from this, not from a role string.
        "caps": sorted(permissions.matrix().get(user["role"], set())),
        # THE ACCOUNT's config (accounts-boards-prd phase 1): the account's own
        # rows resolved over the workspace defaults. Log in on any device and
        # this is the same - that is the whole point of the phase.
        "profile": profile,
        # Which of those the account actually CHOSE, as opposed to inherited
        # from the workspace. The client cannot infer this from `profile` (a
        # resolved value looks identical either way), and two flows turn on
        # it: the first-login language step is shown only when `lang` is not
        # in here, and the device->account migration only offers to push up
        # when the list is empty. Derived from the table on every call, never
        # a stored "migrated" flag on the device.
        "profile_keys": sorted(userconfig.stored(user["name"])),
        # `ui` predates the profile and older bundles still read it, so it now
        # answers with the RESOLVED language rather than the raw workspace one.
        # One question, one answer: an old client that never learns to call
        # /me/config still renders in the language the account picked.
        "ui": {"lang": profile.get("lang", "de"),
               "lane_labels": pol.get("lane_labels") or {},
               # flat (Max subscription) vs metered (API): every
               # role renders AI-cost chips, and a flat plan must
               # never read as $-spend - so the mode rides here.
               "ai_billing": events.ai_billing()},
    }))


def me_config_put(self, user, body):
    """Write MY OWN profile rows. SELF-SCOPE IS THE AUTHORIZATION: the account
    written to is `user["name"]`, taken from the resolved session and never
    from the body, so there is no way to address someone else's rows and
    therefore no new capability to grant, revoke or get wrong. A `client` - the
    role that may otherwise only file and comment - may call this, deliberately:
    it is their own view, not the workspace's. The owner-only POST /settings is
    untouched and remains the only way to move anything shared.

    `migrate: true` marks the one-time device->account push (see
    userconfig.write) - same whitelist, same bound, but it can only FILL
    absent keys, never overwrite an account that already has a profile."""
    from spine.storage import userconfig
    patch = body.get("config")
    if patch is None:
        return self._send(400, json.dumps({"error": "config required"}))
    written, skipped, err = userconfig.write(
        user["name"], patch, actor=user["name"],
        migrate=bool(body.get("migrate")))
    if err:
        return self._send(400, json.dumps({"error": err}))
    # Answer with the new resolved state so the client never has to guess what
    # landed - `skipped` is how a migrating device learns its values lost to an
    # account that already had them, instead of silently believing it won.
    return self._send(200, json.dumps({
        "ok": True, "written": written, "skipped": skipped,
        "profile": userconfig.resolve(user["name"]),
        "profile_keys": sorted(userconfig.stored(user["name"])),
    }))


def processes_new_post(self, user, body):
    from cells.process import processes
    req = body.get("request")
    if not req:
        return self._send(400, json.dumps({"error": "request required"}))
    client = user["name"] if user["role"] == "client" else body.get("client", "")
    return self._send(200, json.dumps(processes.create(
        req, client=client, due=body.get("due", ""), actor=user["name"])))


def voice_transcribe_post(self, user, body):
    # STT stage of the LIVE voice pipeline (spine/media/stt.py): the
    # phone's LiveMic module cut one utterance with its own VAD and sends it
    # here as a WAV blob over the sealed relay. Team-only, same gate as /chat
    # (cap chat.use) - a transcript's whole purpose is to become a chat turn.
    import base64
    from spine.media import stt
    b64 = body.get("audio") or ""
    try:
        wav = base64.b64decode(b64, validate=True) if b64 else b""
    except Exception:
        return self._send(400, json.dumps({"error": "audio must be base64"}))
    try:
        text, info = stt.transcribe(wav, lang=(body.get("lang") or "").strip() or None)
    except RuntimeError as e:
        # 501: the capability is absent (package/model), not the request wrong -
        # the app surfaces the reason instead of pretending it heard silence.
        return self._send(501, json.dumps({"error": str(e)[:200]}))
    return self._send(200, json.dumps({"text": text, "info": info}))


GET_ROUTES = {
    "/processes": processes_get,
    "/me": me_get,
}
POST_ROUTES = {
    "/processes/new": processes_new_post,
    "/voice/transcribe": voice_transcribe_post,
}
PUT_ROUTES = {
    "/me/config": me_config_put,
}
# /processes, /me, /processes/new are open to every role by design (client
# filtering happens by parameter, not by capability) - no entry here for them.
POST_CAPS = {
    "/voice/transcribe": "chat.use",
}
# PUT /me/config is deliberately absent from a *_CAPS table: it is self-scoped
# (see me_config_put), so the capability matrix has nothing to say about it -
# every authenticated account may write its own profile and no account can
# reach another's. PUT_CAPS exists so that a LATER put route must make the
# opposite case explicitly rather than inherit this one's openness.
PUT_CAPS = {}
