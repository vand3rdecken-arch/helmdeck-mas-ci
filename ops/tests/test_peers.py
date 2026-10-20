# -*- coding: utf-8 -*-
"""Headless test for CONNECTIONS TO OTHER INSTANCES (spine/comms/peers.py).

One sandbox db plays both sides: "tien" issues a share link (the other
instance), "member" pastes it here. The HTTP hop is routed in-process to the
real door (mcp_door._answer) - sealing, claim, token and tools are the real
code; only the socket is skipped.

 1. A link without key, plain-http to a foreign host, or garbage is refused.
 2. add() redeems end-to-end: the bytes on the wire carry neither code nor
    token; the token is stored ENCRYPTED and no route/public view returns it.
 3. The cached scope names the remote rooms; call() reads and posts there,
    and the post shows up remotely as the agent, acting for its issuer.
 4. Connections are per ACCOUNT: another account cannot use them.
 5. Henry's spawn gets one stdio MCP server per connection, with no secret in
    the config, and the warm-process key changes when connections do.
 6. A revoked grant surfaces as an error on the connection, not a crash.
 7. Account delete drops the connections.

Run: py -3.12 ops/tests/test_peers.py
"""
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-peers-")
from spine.storage import db
db.ROOT = SANDBOX
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.auth import auth, access_grants
from spine.comms import e2ee, mcp_door, peers, relay_client
from spine.http import mcp
from cells.copilot.chat import rooms, room_henry

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


room_henry.maybe_answer = lambda msg, opts=None: None
PW = "Correct-Horse-Battery-9"
for n, r in (("tien", "owner"), ("member", "operator"), ("other", "operator")):
    auth.create_user(n, PW, r, actor="test")
U = {n: auth.get_user(n) for n in ("tien", "member", "other")}
dsk, _ = e2ee.generate_keypair()
events.save_settings({"relay": {"sk": e2ee.export_sec(dsk), "url": "https://relay.example"}})
room = rooms.create("Projekt Nord", "tien", [])
rooms.post(room["id"], "tien", "Kickoff am Montag")


class H:
    def __init__(self, headers):
        self.headers, self.code, self.wfile = headers, None, io.BytesIO()
    def send_response(self, c): self.code = c
    def send_header(self, *a): pass
    def end_headers(self): pass
    def _send(self, code, body, ctype=None):
        self.code = code
        self.wfile.write(body.encode("utf-8"))


def _inproc(inner):
    h = H(dict(inner.get("headers") or {}))
    mcp.mcp_post(h, json.loads(inner["body"]))
    return {"status": h.code, "headers": {}, "body": h.wfile.getvalue().decode("utf-8")}
relay_client._inproc = _inproc

wire = []


class _Resp:
    def __init__(self, b): self.b = b
    def read(self): return self.b
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _urlopen(req, timeout=None):
    raw = req.data.decode("utf-8")
    wire.append(raw)
    out = mcp_door._answer({"body": raw})
    return _Resp(out["body"].encode("utf-8"))
peers.urllib.request.urlopen = _urlopen

URL = "https://relay.example/mcp/" + "z" * 32
KEY = e2ee.export_pub(dsk.public_key)


def link(code, key=KEY):
    from urllib.parse import quote
    return "%s#c=%s&k=%s" % (URL, code, quote(key, safe=""))


print("1. bad links")
for bad, why in (("https://x/mcp/abc#c=hdc_1", "no key"), ("http://evil.example/mcp/a#c=1&k=2", "plain http"),
                 ("hallo", "garbage")):
    try:
        peers.add("member", bad)
        check(False, "refused: " + why)
    except peers.PeerError:
        check(True, "refused: " + why)

print("2. redeem end-to-end, token encrypted")
g, code = access_grants.grant(U["tien"], "Nord-Agent", [{"kind": "room", "id": room["id"], "write": True}], 24)
wire.clear()
p = peers.add("member", link(code), "Team Nord")
check(p["label"] == "Team Nord" and p["info"].get("for") == "tien", "connection stored with remote scope")
row = db.peer_get("member", p["id"])
check(row["token_enc"] and "hdm_" not in row["token_enc"], "token stored encrypted")
check(not any(code in w or "hdm_" in w for w in wire), "neither code nor token on the wire")
check("token" not in json.dumps(peers.mine("member")) and "token_enc" not in json.dumps(peers.mine("member")),
      "public view never carries the token")

print("3. remote rooms through the connection")
sc = p["info"]["scope"]
check(sc and sc[0]["name"] == "Projekt Nord" and sc[0]["write"], "scope names the remote room")
r = peers.call("member", p["id"], "room_read", {"room": room["id"]})
check(r["messages"][-1]["text"] == "Kickoff am Montag", "read a remote room")
peers.call("member", p["id"], "room_post", {"room": room["id"], "text": "Gruss aus Instanz B"})
last = rooms.history(room["id"], "tien")[-1]
check(last["by"] == "Nord-Agent" and last["byKind"] == "agent" and last["on_behalf"] == "tien",
      "the post lands remotely as the agent, acting for the issuer")

print("4. per account")
try:
    peers.call("other", p["id"], "room_read", {"room": room["id"]})
    check(False, "another account cannot use the connection")
except peers.PeerError:
    check(True, "another account cannot use the connection")
check(peers.mine("other") == [], "another account does not see it")

print("5. Henry's spawn")
from cells.copilot.chat import copilot
args = copilot._lean_mcp_args("member")
cfg = json.loads(args[args.index("--mcp-config") + 1])
srv = list(cfg["mcpServers"].values())
check(len(srv) == 1 and srv[0]["args"][-2:] == ["member", p["id"]], "one stdio MCP server per connection")
check("hdm_" not in args[-1] and row["token_enc"] not in args[-1], "no secret in the MCP config")
check(copilot._lean_mcp_args("other")[-1].endswith("mcp-none.json"), "an account without connections stays lean")
fp1 = copilot._peers_fp("member")
g2, code2 = access_grants.grant(U["tien"], "Nord-2", [{"kind": "room", "id": room["id"]}], 24)
p2 = peers.add("member", link(code2))
check(copilot._peers_fp("member") != fp1, "the warm-process key moves when connections change")

print("5b. card workers of the account get the same connections")
from spine.agent import drivers
argv = drivers.build_argv("card", {"allowed_tools": []}, "brief", account="member")
cfgs = [json.loads(argv[i + 1]) for i, a in enumerate(argv) if a == "--mcp-config"]
peer_srv = [n for c in cfgs for n in c["mcpServers"] if n.startswith("helmdeck_")]
allowed = [argv[i + 1] for i, a in enumerate(argv) if a == "--allowedTools"]
check(len(peer_srv) == 2 and all(("mcp__%s__*" % n) in allowed for n in peer_srv),
      "a card dispatched by the account gets its connections, tools pre-authorised")
argv2 = drivers.build_argv("card", {"allowed_tools": []}, "brief", account="other")
check(not any("helmdeck_" in a for a in argv2), "a card of another account gets none")
check("hdm_" not in " ".join(argv), "no secret in the card's argv")

print("6. revoked on the other side")
access_grants.revoke(U["tien"], g["id"])
try:
    peers.call("member", p["id"], "room_read", {"room": room["id"]})
    check(False, "revoked -> PeerError")
except peers.PeerError:
    check(True, "revoked -> PeerError")
check("revoked" in (db.peer_get("member", p["id"])["err"] or ""), "the connection shows the revocation")

print("7. account delete")
auth.delete_user("member", actor="tien")
check(db.peers_of("member") == [], "connections gone with the account")

print("\n%s" % ("FAIL (%d)" % len(_fails) if _fails else "PASS"))
sys.exit(1 if _fails else 0)
