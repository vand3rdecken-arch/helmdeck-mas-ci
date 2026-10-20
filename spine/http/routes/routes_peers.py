# -*- coding: utf-8 -*-
"""Connections to other HelmDeck instances (logic: spine/comms/peers.py).

  GET  /peers                       my connections (never a token)
  POST /peers                       {link, label?}: redeem a share link
  POST /peers/remove                {id}
  POST /peers/refresh               {id}: re-read the remote scope
  GET  /peers/room?peer=&room=&after=   a remote room's messages
  GET  /peers/room/wait?peer=&room=&after=   the same, held until new ones arrive
  POST /peers/room/post             {peer, room, text}
  GET  /peers/card?peer=&card=      a remote card

The account is ALWAYS the authenticated caller: a connection belongs to the
person who pasted the link, and nobody else's routes can use it.
"""
import json
from urllib.parse import parse_qs, urlparse

from spine.comms import peers


def _q(self):
    return {k: (v or [""])[0] for k, v in parse_qs(urlparse(self.path).query).items()}


def _fail(self, e, code=400):
    return self._send(code, json.dumps({"error": str(e)}))


def peers_get(self, user):
    return self._send(200, json.dumps({"peers": peers.mine(user["name"])}))


def peers_post(self, user, body):
    try:
        return self._send(200, json.dumps(peers.add(user["name"], body.get("link", ""), body.get("label", ""))))
    except peers.PeerError as e:
        return _fail(self, e)


def peers_remove_post(self, user, body):
    if not peers.remove(user["name"], body.get("id", "")):
        return _fail(self, "no such connection", 404)
    return self._send(200, json.dumps({"removed": True}))


def peers_refresh_post(self, user, body):
    try:
        return self._send(200, json.dumps(peers.refresh(user["name"], body.get("id", ""))))
    except peers.PeerError as e:
        return _fail(self, e, 404)


def peers_room_get(self, user):
    q = _q(self)
    try:
        after = int(q.get("after") or 0)
    except ValueError:
        after = 0
    try:
        return self._send(200, json.dumps(peers.call(user["name"], q.get("peer", ""), "room_read",
                                                     {"room": q.get("room", ""), "after": after})))
    except peers.PeerError as e:
        return _fail(self, e, 502)


def peers_room_wait_get(self, user):
    """Long-poll a remote room (the other instance's room_wait, ~20 s hold):
    the app re-arms this instead of re-reading on a timer."""
    q = _q(self)
    try:
        after = int(q.get("after") or 0)
    except ValueError:
        after = 0
    try:
        return self._send(200, json.dumps(peers.call(user["name"], q.get("peer", ""), "room_wait",
                                                     {"room": q.get("room", ""), "after": after, "timeout": 20})))
    except peers.PeerError as e:
        return _fail(self, e, 502)


def peers_room_post(self, user, body):
    try:
        return self._send(200, json.dumps(peers.call(user["name"], body.get("peer", ""), "room_post",
                                                     {"room": body.get("room", ""), "text": body.get("text", "")})))
    except peers.PeerError as e:
        return _fail(self, e, 502)


def peers_card_get(self, user):
    q = _q(self)
    try:
        return self._send(200, json.dumps(peers.call(user["name"], q.get("peer", ""), "card_get",
                                                     {"card": q.get("card", "")})))
    except peers.PeerError as e:
        return _fail(self, e, 502)


GET_ROUTES = {"/peers": peers_get, "/peers/room": peers_room_get, "/peers/room/wait": peers_room_wait_get,
              "/peers/card": peers_card_get}
POST_ROUTES = {"/peers": peers_post, "/peers/remove": peers_remove_post,
               "/peers/refresh": peers_refresh_post, "/peers/room/post": peers_room_post}
