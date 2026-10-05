# -*- coding: utf-8 -*-
"""Private Henry for restricted roles (cells/copilot/chat/private_henry.py).

  GET  /henry/history   my own conversation (the `chat` table, keyed by MY account)
  POST /henry/post      {text}: send a message; Henry's reply arrives as the next entry

Roles without a private Henry (owner: the full chat; client: rooms only) get 403.
The account is always the authenticated caller - there is no parameter to read
someone else's conversation (that is chat_grants, with consent).
"""
import json

from cells.copilot.chat import private_henry


def henry_history_get(self, user):
    if not private_henry.allowed(user):
        return self._send(403, json.dumps({"error": "no private Henry for this role"}))
    return self._send(200, json.dumps({"entries": private_henry.history(user)}))


def henry_post_post(self, user, body):
    if not private_henry.allowed(user):
        return self._send(403, json.dumps({"error": "no private Henry for this role"}))
    try:
        e = private_henry.post(user, body.get("text", ""))
    except ValueError as ex:
        return self._send(400, json.dumps({"error": str(ex)}))
    return self._send(200, json.dumps(e))


GET_ROUTES = {"/henry/history": henry_history_get}
POST_ROUTES = {"/henry/post": henry_post_post}
