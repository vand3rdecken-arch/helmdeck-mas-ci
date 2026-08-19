# -*- coding: utf-8 -*-
"""Relay pairing routes - ninth slice of server.py's dispatch-table split (see
routes_auth.py for the pattern/rationale). POST /relay/pair (mint the pairing
payload + a fresh device token, owner only), POST /relay/unpair. Bodies are
byte-identical to the inline blocks they replace.
"""
import json


def relay_pair_post(self, user, body):
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    from daemon.spine import relay_client
    from daemon.spine import auth
    try:
        pay = relay_client.pairing_payload()
    except ValueError as e:   # plain-http relay url: refuse to mint
        return self._send(400, json.dumps({"error": str(e)}))
    # a fresh device token so the phone authenticates through the
    # encrypted tunnel (carried as Bearer inside the sealed request).
    # Invites bring the teammate's OWN token - minting an owner
    # token there would leave a dangling owner credential per invite.
    if not body.get("invite"):
        pay["device_token"] = auth.issue_token(user["name"], "phone (relay)")
    return self._send(200, json.dumps(pay))


def relay_unpair_post(self, user, body):
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    from daemon.spine import relay_client
    return self._send(200, json.dumps(relay_client.unpair()))


POST_ROUTES = {
    "/relay/pair": relay_pair_post,
    "/relay/unpair": relay_unpair_post,
}
