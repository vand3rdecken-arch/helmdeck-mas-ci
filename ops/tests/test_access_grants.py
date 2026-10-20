# -*- coding: utf-8 -*-
"""Headless test for EXTERNAL-AGENT ACCESS (access grants + the /mcp door).

Every case is a way the door could leak, through the real handlers and db:

 1. No grant / a device token / garbage -> 401. A session is not enough.
 2. A grant cannot be ISSUED for a room you are not in or a card you do not
    own (write) - same refusal for unknown and foreign ids.
 3. tools/call reaches exactly the scope: another room/card is refused, a
    read-only entry refuses writes.
 4. The issuer's access is re-checked LIVE: removed from the room -> the grant
    stops reaching it, without touching the grant.
 5. Active is DERIVED: revoked or expired -> 401 with no sweeper.
 6. A post under a grant is the issuer's, marked via=mcp:<label>; steer goes
    to the card's worker with the issuer as actor; every call is recorded.
 7. Deleting the issuer's account drops its grants.

Self-sandboxing: temp DB, no network, no worker spawned (server._bg captured).
Run: py -3.12 ops/tests/test_access_grants.py
"""
import io
import time
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-access-")

from spine.storage import db
db.ROOT = SANDBOX   # BOTH, not just DBPATH - see test_hook_idle.py's preamble
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.auth import auth, access_grants
from spine.http import mcp, server
from cells.copilot.chat import rooms
from cells.copilot.chat import room_henry

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


bg = []
server._bg = lambda name, fn: bg.append(name)          # never spawn a worker
room_henry.maybe_answer = lambda msg, opts=None: None   # no Henry turn

PW = "Correct-Horse-Battery-9"
for n, r in (("tien", "owner"), ("ops", "operator"), ("member", "client")):
    auth.create_user(n, PW, r, actor="test")
U = {"tien": {"name": "tien", "role": "owner"}, "ops": {"name": "ops", "role": "operator"},
     "member": {"name": "member", "role": "client"}}

r1 = rooms.create("Team", "tien", ["member"])
r2 = rooms.create("Geheim", "tien", [])
mine = {"id": "c-mine", "status": "idle", "lane": "working", "task": "Meine Karte\nDetails",
        "branch": "c-mine", "run_dir": SANDBOX, "worktree": "", "turns": 1,
        "client": "member", "dispatched_by": "member", "updated": "2026-10-20 00:00:00"}
other = dict(mine, id="c-other", task="Fremde Karte", client="", dispatched_by="tien")
db.track_put(mine)
db.track_put(other)


class H:
    def __init__(self, token, origin=""):
        self.headers = {"Authorization": "Bearer " + token} if token else {}
        if origin:
            self.headers["Origin"] = origin
        self.code, self.wfile = None, io.BytesIO()

    def send_response(self, c): self.code = c
    def send_header(self, *a): pass
    def end_headers(self): pass

    def _send(self, code, body, ctype=None):
        self.code = code
        self.wfile.write(body.encode("utf-8"))


def claim(code):
    h = H("")
    mcp.mcp_post(h, {"claim": code})
    return h.code, json.loads(h.wfile.getvalue().decode("utf-8") or "{}")


def call(token, method, params=None, rid=1, origin=""):
    h = H(token, origin)
    mcp.mcp_post(h, {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
    raw = h.wfile.getvalue().decode("utf-8")
    return h.code, (json.loads(raw) if raw and h.code == 200 else raw)


def tool(token, name, **args):
    code, r = call(token, "tools/call", {"name": name, "arguments": args})
    res = r["result"]
    return res.get("isError", False), res["content"][0]["text"]


print("1. no grant -> 401")
check(call("", "tools/list")[0] == 401, "no header -> 401")
check(call("hdm_nope", "tools/list")[0] == 401, "unknown hdm_ token -> 401")
dev = auth.issue_token("member", "phone", actor="test")
dtok = dev if isinstance(dev, str) else dev["token"]
check(auth.resolve(token=dtok) and call(dtok, "tools/list")[0] == 401, "a device token does not open /mcp")

print("2. issue only what you reach yourself")
for scope, why in (([{"kind": "room", "id": r2["id"]}], "room not a member of"),
                   ([{"kind": "card", "id": "c-other", "write": True}], "card not owned (write)"),
                   ([{"kind": "card", "id": "nope"}], "unknown card"),
                   ([], "empty scope")):
    try:
        access_grants.grant(U["member"], "cursor", scope, 24, sealed_only=False)
        check(False, "refused: " + why)
    except ValueError:
        check(True, "refused: " + why)
try:
    access_grants.grant(U["member"], "cursor", [{"kind": "room", "id": r1["id"]}], 99999, sealed_only=False)
    check(False, "hours bounded")
except ValueError:
    check(True, "hours bounded")

g, code_rw = access_grants.grant(U["member"], "cursor",
                                 [{"kind": "room", "id": r1["id"], "write": True},
                                  {"kind": "card", "id": "c-mine", "write": True}], 24, sealed_only=False)
ro, code_ro = access_grants.grant(U["member"], "claude-ro", [{"kind": "room", "id": r1["id"]}], 24, sealed_only=False)
check(code_rw.startswith("hdc_") and not g["claimed"], "issue returns a one-time CODE, not a token")
check(call(code_rw, "tools/list")[0] == 401, "the claim code itself does not open /mcp")
c, r = claim(code_rw)
tok = r.get("token", "")
check(c == 200 and tok.startswith("hdm_") and r["issuer"] == "member", "claim -> token")
check(claim(code_rw)[0] == 404, "the same link a second time -> nothing")
check(claim("hdc_nope")[0] == 404, "unknown code -> 404")
tok_ro = claim(code_ro)[1]["token"]
check(all(x["claimed"] for x in access_grants.mine(U["member"])), "claimed shows in the issuer's list")
check(not any(t in json.dumps(x) for x in db.access_grants_of("member") for t in (tok, code_rw)),
      "neither token nor code is stored")
_, late = access_grants.grant(U["member"], "late", [{"kind": "room", "id": r1["id"]}], 24, sealed_only=False)
access_grants.revoke(U["member"], [x for x in access_grants.mine(U["member"]) if x["label"] == "late"][0]["id"])
check(claim(late)[0] == 404, "a revoked grant's link cannot be claimed")

print("3. scope")
code, r = call(tok, "initialize", {"protocolVersion": "2025-06-18"})
check(code == 200 and r["result"]["protocolVersion"] == "2025-06-18", "initialize")
tl = call(tok, "tools/list")[1]["result"]["tools"]
check(len(tl) == 11 and all("annotations" in x for x in tl)
      and {x["name"] for x in tl if x["annotations"]["readOnlyHint"]}
      == {"helmdeck_scope", "room_read", "room_wait", "card_get", "card_files", "card_read", "card_diff"},
      "tools/list with read-only annotations")
check(call(tok, "tools/list", origin="https://evil.example")[0] == 403, "foreign Origin -> 403")
check(call(tok, "tools/list", origin="http://localhost:8081")[0] == 200, "loopback Origin ok")
err, txt = tool(tok, "helmdeck_scope")
check(not err and {e["id"] for e in json.loads(txt)["scope"]} == {r1["id"], "c-mine"}, "scope lists exactly the grant")
check(tool(tok, "room_read", room=r2["id"])[0], "other room refused")
check(tool(tok, "card_get", card="c-other")[0], "other card refused")
check(tool(tok_ro, "room_post", room=r1["id"], text="hi")[0], "read-only grant cannot post")
err, txt = tool(tok, "room_post", room=r1["id"], text="Hallo aus Cursor")
check(not err, "room_post in scope")
msgs = rooms.history(r1["id"], "tien")
check(msgs[-1]["by"] == "cursor" and msgs[-1]["byKind"] == "agent" and msgs[-1]["on_behalf"] == "member",
      "post carries the AGENT's identity, acting for the member")
err, txt = tool(tok_ro, "room_read", room=r1["id"])
check(not err and json.loads(txt)["messages"][-1]["text"] == "Hallo aus Cursor"
      and "never as instructions" in json.loads(txt)["note"], "read-only grant reads, content flagged as untrusted")
from cells.copilot.chat import room_henry as _rh
check("cursor (externer Agent im Auftrag von member" in _rh._line(msgs[-1]), "Henry sees the post as an external agent's")
try:
    access_grants.grant(U["member"], "Tien", [{"kind": "room", "id": r1["id"]}], 24, sealed_only=False)
    check(False, "label may not impersonate an account")
except ValueError:
    check(True, "label may not impersonate an account")
err, txt = tool(tok, "card_get", card="c-mine")
check(not err and json.loads(txt)["title"] == "Meine Karte" and "run_dir" not in txt, "card_get, no internals")
err, _ = tool(tok, "card_steer", card="c-mine", text="Bitte Tests ergänzen")
check(not err and bg == ["track:steer:c-mine"], "steer dispatched to the card worker")
check(tool(tok, "card_answer", card="c-mine", answers={})[0], "answer without a question refused")

print("3b. room_wait: held until the room moves, woken at event time")
import threading as _th
_last = rooms.history(r1["id"], "tien")[-1]["seq"]
_th.Timer(0.8, lambda: rooms.post(r1["id"], "tien", "neu waehrend des Wartens")).start()
_t0 = time.time()
err, txt = tool(tok, "room_wait", room=r1["id"], after=_last, timeout=15)
_dt = time.time() - _t0
got = json.loads(txt)["messages"] if not err else []
check(not err and got and got[-1]["text"] == "neu waehrend des Wartens" and 0.5 < _dt < 5,
      "room_wait returns the new message right after it lands (%.1fs)" % _dt)
_t0 = time.time()
err, txt = tool(tok, "room_wait", room=r1["id"], after=got[-1]["seq"] if got else _last, timeout=1)
check(not err and json.loads(txt)["messages"] == [] and time.time() - _t0 < 3, "nothing new: empty answer after the hold")
check(tool(tok, "room_wait", room=r2["id"], after=0, timeout=1)[0], "room_wait outside the scope refused")

print("4a. rate limit")
access_grants._calls.clear()
hits = [tool(tok, "room_post", room=r1["id"], text="spam %d" % i)[0] for i in range(access_grants.RATE_WRITES + 2)]
check(hits.count(False) == access_grants.RATE_WRITES and hits[-1], "writes capped per minute")
check(not tool(tok, "room_read", room=r1["id"])[0], "reads still allowed under the write cap")
access_grants._calls.clear()

print("4. issuer's access re-checked live")
rooms.set_members(r1["id"], "tien", remove=["member"])
check(tool(tok, "room_read", room=r1["id"])[0], "issuer left the room -> grant stops reaching it")
rooms.set_members(r1["id"], "tien", add=["member"])

print("5. revoke / expiry")
access_grants.revoke(U["member"], ro["id"])
check(call(tok_ro, "tools/list")[0] == 401, "revoked -> 401")
row = db.access_grant_by_th(access_grants._th(tok))
row["expires"] = 1
db.access_grant_put(row)
check(call(tok, "tools/list")[0] == 401, "expired -> 401")
try:
    access_grants.revoke(U["ops"], g["id"])
    check(False, "only the issuer revokes")
except ValueError:
    check(True, "only the issuer revokes")

print("6. recorded")
uses = db.access_grant_uses_of(g["id"])
check(any(u["tool"] == "room_post" and u["ok"] for u in uses)
      and any(u["tool"] == "card_get" and not u["ok"] for u in uses), "every call recorded, ok and refused")

print("8. OAuth 2.1 (register -> authorize with the link -> token with PKCE)")
import base64 as _b64, hashlib as _hl
from urllib.parse import urlencode, urlsplit, parse_qs as _pq
from spine.auth import mcp_oauth
BASE = "https://relay.example/mcp/" + "a" * 32
st, _, body, _ = mcp_oauth.route("GET", "wk/prm", "", "", BASE)
check(st == 200 and json.loads(body)["authorization_servers"] == [BASE], "protected-resource metadata")
st, _, body, _ = mcp_oauth.route("GET", "wk/as", "", "", BASE)
md = json.loads(body)
check(md["code_challenge_methods_supported"] == ["S256"] and md["token_endpoint"] == BASE + "/token", "server metadata")
check(mcp_oauth.route("POST", "register", "", json.dumps({"redirect_uris": ["http://evil.example/cb"]}), BASE)[0] == 400,
      "non-loopback http redirect refused")
st, _, body, _ = mcp_oauth.route("POST", "register", "", json.dumps({"redirect_uris": ["http://127.0.0.1:5555/cb"], "client_name": "Claude Code"}), BASE)
cid = json.loads(body)["client_id"]
check(st == 201 and cid, "dynamic client registration")
ver = "v" * 50
chal = _b64.urlsafe_b64encode(_hl.sha256(ver.encode()).digest()).decode().rstrip("=")
qs = urlencode({"response_type": "code", "client_id": cid, "redirect_uri": "http://127.0.0.1:5555/cb",
                "code_challenge": chal, "code_challenge_method": "S256", "state": "xyz", "resource": BASE})
st, ct, body, hd = mcp_oauth.route("GET", "authorize", qs, "", BASE)
check(st == 200 and "Claude Code" in body and "frame-ancestors" not in body, "authorize shows the paste-your-link page")
check(mcp_oauth.route("GET", "authorize", qs.replace("127.0.0.1%3A5555", "evil.example"), "", BASE)[0] == 400,
      "unregistered redirect_uri: no redirect at all")
og, ocode = access_grants.grant(U["tien"], "Claude von Lena", [{"kind": "room", "id": r2["id"]}], 24, sealed_only=False)
form = qs + "&" + urlencode({"link": BASE + "#c=" + ocode + "&k=x"})
st, _, _, hd = mcp_oauth.route("POST", "authorize", "", form, BASE)
loc = _pq(urlsplit(hd.get("Location", "")).query)
check(st == 302 and loc.get("state") == ["xyz"] and loc.get("code"), "link redeemed -> redirect with code + state")
acode = loc["code"][0]
tok_req = lambda v: urlencode({"grant_type": "authorization_code", "code": acode, "client_id": cid,
                               "redirect_uri": "http://127.0.0.1:5555/cb", "code_verifier": v})
st, _, body, _ = mcp_oauth.route("POST", "token", "", tok_req("wrong" * 10), BASE)
check(st == 400, "wrong PKCE verifier refused")
st, _, body, _ = mcp_oauth.route("POST", "token", "", tok_req(ver), BASE)
check(st == 400, "code is single-use even after a failed exchange")
# a fresh round with the right verifier
og2, ocode2 = access_grants.grant(U["tien"], "Claude von Lena 2", [{"kind": "room", "id": r2["id"]}], 24, sealed_only=False)
st, _, _, hd = mcp_oauth.route("POST", "authorize", "", qs + "&" + urlencode({"link": ocode2}), BASE)
acode = _pq(urlsplit(hd["Location"]).query)["code"][0]
st, _, body, _ = mcp_oauth.route("POST", "token", "", tok_req(ver), BASE)
otok = json.loads(body).get("access_token", "")
check(st == 200 and otok.startswith("hdm_"), "token issued for the right verifier")
check(not tool(otok, "room_read", room=r2["id"])[0], "OAuth token reads its room")
st, _, _, hd = mcp_oauth.route("POST", "authorize", "", qs + "&" + urlencode({"link": ocode2}), BASE)
check(st == 200, "a used link at /authorize -> the page again, no redirect")
h401 = H("")
mcp.mcp_post(h401, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
check(h401.code == 401, "401 without token (WWW-Authenticate carries resource_metadata)")

print("9. sealed (end-to-end) door")
from spine.comms import e2ee, mcp_door
from spine.storage import events as _ev
dsk, _ = e2ee.generate_keypair()
_ev.save_settings({"relay": {"sk": e2ee.export_sec(dsk), "url": "https://relay.example"}})
seen_by_relay = []
_inproc_real = None
from spine.comms import relay_client
def _fake_inproc(inner):
    h = H("")
    h.headers = {k: v for k, v in (inner.get("headers") or {}).items()}
    mcp.mcp_post(h, json.loads(inner["body"]))
    return {"status": h.code, "headers": {}, "body": h.wfile.getvalue().decode("utf-8")}
relay_client._inproc = _fake_inproc
csk, cpk = e2ee.generate_keypair()
def sealed(inner):
    env = {"sealed": 1, "pub": e2ee.export_pub(cpk),
           "cipher": e2ee.seal_b64(json.dumps(inner).encode(), csk, dsk.public_key)}
    raw = json.dumps(env)
    seen_by_relay.append(raw)
    out = mcp_door._answer({"body": raw, "base": BASE})
    return json.loads(e2ee.open_b64(json.loads(out["body"])["cipher"], csk, dsk.public_key))
sg, scode = access_grants.grant(U["tien"], "Shim", [{"kind": "room", "id": r2["id"]}], 24)
r = sealed({"body": json.dumps({"claim": scode}), "auth": "", "ts": time.time(), "n": "n1"})
stok = json.loads(r["body"]).get("token", "")
check(r["status"] == 200 and stok, "claim through the seal")
call_in = {"body": json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                               "params": {"name": "room_read", "arguments": {"room": r2["id"]}}}),
           "auth": "Bearer " + stok, "ts": time.time(), "n": "n2"}
r = sealed(call_in)
check(r["status"] == 200 and "result" in json.loads(r["body"]), "MCP call through the seal")
check(not any(stok in x or scode in x or "room_read" in x for x in seen_by_relay),
      "the relay saw neither code, token nor request")
check(sealed(call_in)["status"] == 409, "a replayed sealed frame is refused")
stale = dict(call_in, n="n3", ts=time.time() - 3600)
check(sealed(stale)["status"] == 409, "a stale sealed frame is refused")
bad = mcp_door._answer({"body": json.dumps({"sealed": 1, "pub": e2ee.export_pub(cpk), "cipher": "AAAA"}), "base": BASE})
check(bad["status"] == 400, "garbage cipher -> 400")

print("9b. sealed-only grants (the default)")
so_g, so_code = access_grants.grant(U["tien"], "Nur E2E", [{"kind": "room", "id": r2["id"]}], 24)
check(so_g["sealed_only"] is True, "new grants are sealed-only by default")
c, rr = claim(so_code)
check(c == 403 and "end-to-end" in rr.get("error", ""), "a plain claim of a sealed-only link is refused")
r = sealed({"body": json.dumps({"claim": so_code}), "auth": "", "ts": time.time(), "n": "so1"})
so_tok = json.loads(r["body"]).get("token", "")
check(r["status"] == 200 and so_tok, "...and the code was NOT burnt: the sealed claim still works")
check(call(so_tok, "tools/list")[0] == 403, "its token is refused on the direct path")
r = sealed({"body": json.dumps({"jsonrpc": "2.0", "id": 9, "method": "tools/list"}),
            "auth": "Bearer " + so_tok, "ts": time.time(), "n": "so2"})
check(r["status"] == 200, "...and accepted sealed")
check(not mcp._sealed_now(), "the sealed marker is cleared after the call")
og3, ocode3 = access_grants.grant(U["tien"], "OAuth E2E", [{"kind": "room", "id": r2["id"]}], 24)
st, _, body, _ = mcp_oauth.route("POST", "authorize", "", qs + "&" + urlencode({"link": ocode3}), BASE)
check(st == 200 and "end-to-end" in body, "OAuth sign-in with a sealed-only link explains instead of redirecting")
check(len(mcp_door.shim_sha()) == 64, "the daemon knows the shim's sha256 for the link")

print("10. a card's code: read-only fence + proposals through the worker")
import subprocess as _sp
REPO = os.path.join(SANDBOX, "repo")
os.makedirs(os.path.join(REPO, "src"))
def _g(*a): _sp.run(["git", "-C", REPO, *a], check=True, capture_output=True)
_sp.run(["git", "init", "-q", REPO], check=True)
_g("config", "user.email", "t@t"); _g("config", "user.name", "t")
open(os.path.join(REPO, "src", "app.py"), "w", newline="\n").write("def hello():\n    return 1\n")
open(os.path.join(REPO, ".env"), "w").write("API_KEY=sk-live-123\n")
open(os.path.join(REPO, ".gitignore"), "w").write("settings.json\n")
open(os.path.join(REPO, "settings.json"), "w").write('{"token": "secret"}')
_g("add", "src/app.py", ".env", ".gitignore"); _g("commit", "-qm", "init")
open(os.path.join(REPO, "src", "app.py"), "a", newline="\n").write("\ndef bye():\n    return 2\n")
code_card = dict(mine, id="c-code", repo=REPO, worktree="", branch="", task="Code Karte")
db.track_put(code_card)
bg.clear()
_, c_ro = access_grants.grant(U["tien"], "reader", [{"kind": "card", "id": "c-code"}], 24, sealed_only=False)
_, c_cd = access_grants.grant(U["tien"], "coder", [{"kind": "card", "id": "c-code", "code": True}], 24, sealed_only=False)
t_ro, t_cd = claim(c_ro)[1]["token"], claim(c_cd)[1]["token"]
err, txt = tool(t_ro, "card_files", card="c-code")
fl = json.loads(txt)["files"] if not err else []
check(not err and "src/app.py" in fl and ".gitignore" in fl, "card_files lists tracked files")
check(".env" not in fl and "settings.json" not in fl, "secrets: denied (.env) and ignored (settings.json) never listed")
err, txt = tool(t_ro, "card_read", card="c-code", path="src/app.py")
check(not err and "def bye" in json.loads(txt)["text"], "card_read returns the working-tree content")
for bad in (".env", "settings.json", "../repo/.env", "/etc/passwd", "src/../.env"):
    check(tool(t_ro, "card_read", card="c-code", path=bad)[0], "card_read refuses %s" % bad)
err, txt = tool(t_ro, "card_diff", card="c-code")
check(not err and "+def bye" in json.loads(txt)["diff"], "card_diff shows the uncommitted change")
patch = ("--- a/src/app.py\n+++ b/src/app.py\n@@ -1,5 +1,5 @@\n def hello():\n-    return 1\n+    return 42\n \n def bye():\n     return 2\n")
check(tool(t_ro, "card_propose", card="c-code", patch=patch)[0], "read-only grant cannot propose")
check(tool(t_cd, "card_propose", card="c-code", patch="--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-x\n+y\n")[0],
      "a patch on a denied file is refused before git")
check(tool(t_cd, "card_propose", card="c-code", patch="--- a/nope.py\n+++ b/nope.py\n@@ -1 +1 @@\n-a\n+b\n")[0],
      "a patch on a file the card does not have is refused")
before = open(os.path.join(REPO, "src", "app.py")).read()
err, txt = tool(t_cd, "card_propose", card="c-code", patch=patch, note="hello soll 42 liefern")
check(not err and bg == ["track:steer:c-code"], "a clean patch goes to the card's worker as a steer")
check(open(os.path.join(REPO, "src", "app.py")).read() == before, "the proposal touched no file itself")
sc = json.loads(tool(t_cd, "helmdeck_scope")[1])["scope"]
check(sc and sc[0]["code"] is True and sc[0]["write"] is True, "code level implies write and shows in scope")

print("7. account delete drops grants")
auth.delete_user("member", actor="tien")
check(db.access_grants_of("member") == [], "grants gone with the issuer")

print("\n%s" % ("FAIL (%d)" % len(_fails) if _fails else "PASS"))
sys.exit(1 if _fails else 0)
