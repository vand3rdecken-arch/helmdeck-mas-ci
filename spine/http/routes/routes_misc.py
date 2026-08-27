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
    from spine.storage import events
    from spine.auth import permissions
    pol = events.settings().get("policy") or {}
    return self._send(200, json.dumps({
        "name": user["name"], "role": user["role"],
        # Card 4 (ops/docs/backlog/rbac-gxp): the app's ONE source for "what
        # may I see/do" - derived live from permissions.matrix() every call,
        # never cached here or in the client beyond a query invalidation on
        # login/role-change. Nav renders from this, not from a role string.
        "caps": sorted(permissions.matrix().get(user["role"], set())),
        "ui": {"lang": pol.get("lang", "de"),
               "lane_labels": pol.get("lane_labels") or {},
               # flat (Max subscription) vs metered (API): every
               # role renders AI-cost chips, and a flat plan must
               # never read as $-spend - so the mode rides here.
               "ai_billing": events.ai_billing()},
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
# /processes, /me, /processes/new are open to every role by design (client
# filtering happens by parameter, not by capability) - no entry here for them.
POST_CAPS = {
    "/voice/transcribe": "chat.use",
}
