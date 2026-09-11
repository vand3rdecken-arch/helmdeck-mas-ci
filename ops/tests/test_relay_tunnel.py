# Self-sandboxed check of the relay's tunnel endpoints (/relay, /tunnel/pull,
# /tunnel/push): relay on an ephemeral localhost port, real HTTP + raw
# sockets. Covers relay-push-resilience Phase A - a truncated or malformed
# push body must answer cleanly (400, one log line) and never traceback or
# poison the keep-alive connection.
#   py -3.12 ops/tests/test_relay_tunnel.py
import http.client, io, json, os, sys, threading, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "surfaces", "relay"))
import relay  # noqa: E402  (reads env at import)

from http.server import ThreadingHTTPServer  # noqa: E402
srv = ThreadingHTTPServer(("127.0.0.1", 0), relay.H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

fails = []
def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        fails.append(name)

def get(path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
        return r.status, r.read()

def post(path, body, timeout=10):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body,
                                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

# -- (a) full round trip: /relay -> /tunnel/pull -> /tunnel/push -----------
ROOM = "test-room-a"
# /relay refuses with 503 until a daemon has pulled this room at least once
# (relay.py: `last_pull` starts at 0.0) - seed it the same way a real pull
# would, via the module's own room registry (white-box: this test imports
# relay.py directly).
relay._room(ROOM)["last_pull"] = time.time()

def phone_call():
    body = json.dumps({"pub": "phone-pub-a", "cipher": "phone-cipher-a"}).encode()
    return post(f"/relay?room={ROOM}", body, timeout=15)

result = {}
t = threading.Thread(target=lambda: result.__setitem__("r", phone_call()))
t.start()
time.sleep(0.3)   # let /relay queue the frame before we pull
st_pull, body_pull = get(f"/tunnel/pull?room={ROOM}")
frame = json.loads(body_pull)
check("pull sees queued frame", st_pull == 200 and frame.get("pub") == "phone-pub-a", body_pull)

push_body = json.dumps({"id": frame["id"], "cipher": "daemon-reply-cipher"}).encode()
st_push, b_push = post(f"/tunnel/push?room={ROOM}", push_body)
check("push acked", st_push == 200 and json.loads(b_push).get("ok") is True, b_push)

t.join(timeout=15)
st_relay, b_relay = result.get("r", (None, b""))
check("relay round trip delivers cipher", st_relay == 200
      and json.loads(b_relay).get("cipher") == "daemon-reply-cipher", b_relay)

# -- (b) truncated push body: declared Content-Length > actual bytes -------
# Capture the relay's OWN stderr, since that's where an unguarded json.loads
# would print a traceback via socketserver's default error handler.
_stderr_buf = io.StringIO()
_orig_stderr = sys.stderr
sys.stderr = _stderr_buf
try:
    import socket
    body = b'{"id": "deadbeef", "cipher": "AAAAAAAAAA'   # deliberately short
    declared = len(body) + 500                            # promise 500 more bytes
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    hdr = ("POST /tunnel/push?room=test-room-b HTTP/1.1\r\nHost: x\r\n"
           "Content-Type: application/json\r\nContent-Length: %d\r\n\r\n" % declared).encode()
    s.sendall(hdr + body)
    time.sleep(0.4)
    s.close()   # hang up with the promised bytes never sent
    time.sleep(0.4)
finally:
    sys.stderr = _orig_stderr
captured = _stderr_buf.getvalue()
check("truncated push: no traceback printed", "Traceback" not in captured, captured[:300])

st_health, b_health = get("/health")
check("truncated push: server still answers /health", st_health == 200, b_health)

# -- (c) complete but malformed JSON body -> 400 "bad json", keep-alive OK -
conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
conn.request("POST", "/tunnel/push?room=test-room-c", body=b"not json{{{",
             headers={"Content-Type": "application/json"})
resp = conn.getresponse()
st_bad = resp.status
b_bad = resp.read()
check("malformed push -> 400 bad json", st_bad == 400 and json.loads(b_bad).get("error") == "bad json", b_bad)

# same connection, next request: keep-alive must not be poisoned by the
# malformed body (the exact bug the /relay body-first comment documents)
conn.request("GET", "/health")
resp2 = conn.getresponse()
st_keepalive = resp2.status
b_keepalive = resp2.read()
check("keep-alive intact after bad json", st_keepalive == 200 and json.loads(b_keepalive).get("ok") is True,
      b_keepalive)
conn.close()

# -- (d) push for an unknown frame id -> 200 ok (nothing to deliver, no error)
st_unknown, b_unknown = post(f"/tunnel/push?room={ROOM}",
                              json.dumps({"id": "no-such-frame", "cipher": "x"}).encode())
check("push for unknown id -> 200 ok", st_unknown == 200 and json.loads(b_unknown).get("ok") is True, b_unknown)

srv.shutdown()
print()
print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
