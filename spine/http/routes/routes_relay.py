# -*- coding: utf-8 -*-
"""Relay pairing routes - ninth slice of server.py's dispatch-table split (see
routes_auth.py for the pattern/rationale). POST /relay/pair (mint the pairing
payload + a fresh device token, owner only), POST /relay/unpair, and the
device-code pairing pair added for W2b (relay_client.py's own header carries
the full rationale - a camera-less, keyboard-less device like a Wear OS watch
can neither scan the existing QR nor type a link): POST /relay/pair/code
mints a short spoken code standing in for the same payload; GET
/relay/pair/claim trades it in exactly once. Bodies are byte-identical to the
inline blocks they replace.
"""
import json


def relay_pair_post(self, user, body):
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    from spine.comms import relay_client
    from spine.auth import auth
    try:
        pay = relay_client.pairing_payload()
    except ValueError as e:   # plain-http relay url: refuse to mint
        return self._send(400, json.dumps({"error": str(e)}))
    # a fresh device token so the phone authenticates through the
    # encrypted tunnel (carried as Bearer inside the sealed request).
    # Invites bring the teammate's OWN token - minting an owner
    # token there would leave a dangling owner credential per invite.
    #
    # unused_days pays debt [pair-token-no-ttl]: the pairing WINDOW was 15
    # minutes but the token inside the code never expired, so an abandoned or
    # leaked pairing code stayed a live credential over direct-LAN mode
    # forever. It now dies unclaimed. A token the phone actually presented is
    # a normal device token from that moment on (auth._token_expired).
    if not body.get("invite"):
        pay["device_token"] = auth.issue_token(
            user["name"], "phone (relay)",
            unused_days=auth.PAIR_UNUSED_TTL_DAYS)
    return self._send(200, json.dumps(pay))


def relay_unpair_post(self, user, body):
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    from spine.comms import relay_client
    return self._send(200, json.dumps(relay_client.unpair()))


def relay_pair_code_post(self, user, body):
    # Owner-only, same as relay_pair_post - always mints a FRESH device token
    # (no "invite" branch: this route exists for the owner's OWN second
    # device, not for onboarding a teammate, who already has the QR/link
    # path and a phone camera to use it with).
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    from spine.comms import relay_client
    from spine.auth import auth
    try:
        pay = relay_client.pairing_payload()
    except ValueError as e:
        return self._send(400, json.dumps({"error": str(e)}))
    # `label` is what the owner's token list will show for this device
    # (auth.py: "purely so a human can tell two devices apart") - defaults to
    # something generic rather than failing the request over a missing field.
    label = (body.get("label") or "device (code)").strip()[:40]
    pay["device_token"] = auth.issue_token(user["name"], label,
                                           unused_days=auth.PAIR_UNUSED_TTL_DAYS)
    code, ttl = relay_client.mint_claim_code(pay)
    return self._send(200, json.dumps({"code": code, "expires_in": ttl}))


def relay_pair_claim_get(self, user):
    # DELIBERATELY UNAUTHENTICATED - registered in server.py's `OPEN` tuple,
    # same class as /glance. The claiming device (the watch) has no session
    # and no token yet; that is the entire point of this route. The
    # single-use code IS the credential, exactly like pair_pending already is
    # for the QR path - `user` is accepted but unused, matching every other
    # OPEN handler's signature.
    from urllib.parse import parse_qs, urlparse
    from spine.comms import relay_client
    code = (parse_qs(urlparse(self.path).query).get("code") or [""])[0]
    pay = relay_client.claim_code(code)
    if not pay:
        return self._send(404, json.dumps({"error": "unknown or expired code"}))
    return self._send(200, json.dumps(pay))


GET_ROUTES = {
    "/relay/pair/claim": relay_pair_claim_get,
}
POST_ROUTES = {
    "/relay/pair": relay_pair_post,
    "/relay/pair/code": relay_pair_code_post,
    "/relay/unpair": relay_unpair_post,
}
