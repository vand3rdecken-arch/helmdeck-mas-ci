# -*- coding: utf-8 -*-
"""End-to-end against a DEPLOYED relay (worker or relay.py) by URL - plays the
phone and the daemon with plain HTTP, no crypto (the relay only shuttles opaque
frames, so real ciphertext is not needed to prove routing, timeouts and limits).

  py -3.12 ops/tests/test_relay_worker_e2e.py https://helmdeck-relay.<sub>.workers.dev
"""
import json, sys, threading, time, urllib.error, urllib.request, uuid

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:6790").rstrip("/")
ROOM = "e2e-" + uuid.uuid4().hex[:12]
fails = 0

def req(method, path, body=None, timeout=60, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               # workers.dev sits behind Cloudflare's browser integrity check,
                               # which 403s (error 1010) the default Python-urllib agent
                               headers={"content-type": "application/json",
                                        "user-agent": "HelmDeck-e2e/1.0", **(headers or {})})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)

def check(name, ok, detail=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (("  " + detail) if detail and not ok else ""))
    if not ok: fails += 1

# 1) health
code, body, _ = req("GET", "/health", timeout=15)
try:
    h = json.loads(body or b"{}")
except ValueError:
    print("FAIL health returned non-JSON: HTTP %s %r" % (code, body[:200])); sys.exit(1)
check("health ok + instance", code == 200 and h.get("ok") is True and h.get("instance"), repr(body[:120]))

# 2) phone before any daemon pull -> 503
code, body, _ = req("POST", "/relay?room=" + ROOM, {"pub": "p", "cipher": "c"}, timeout=15)
check("relay without daemon -> 503", code == 503, "%s %r" % (code, body[:80]))

# 3) daemon pull on empty room -> 204 after ~25 s
t0 = time.time(); code, body, _ = req("GET", "/tunnel/pull?room=" + ROOM, timeout=40)
check("empty pull -> 204 in ~25 s", code == 204 and 20 <= time.time() - t0 <= 35, "%s after %.1fs" % (code, time.time() - t0))

# 4) round trip: daemon thread pulls, answers; phone gets the cipher back
got = {}
def daemon():
    for _ in range(3):
        c, b, _ = req("GET", "/tunnel/pull?room=" + ROOM, timeout=40)
        if c == 200:
            f = json.loads(b); got["frame"] = f
            req("POST", "/tunnel/push?room=" + ROOM, {"id": f["id"], "cipher": "REPLY:" + f["cipher"]}, timeout=15)
            return
th = threading.Thread(target=daemon); th.start(); time.sleep(1.5)
code, body, _ = req("POST", "/relay?room=" + ROOM, {"pub": "PUB", "cipher": "HELLO"}, timeout=60)
th.join(45)
check("round trip phone->daemon->phone", code == 200 and json.loads(body or b"{}").get("cipher") == "REPLY:HELLO",
      "%s %r frame=%r" % (code, body[:80], got.get("frame")))
check("frame carries pub+cipher+id", got.get("frame", {}).get("pub") == "PUB" and got.get("frame", {}).get("cipher") == "HELLO")

# 5) bad inputs
code, _, _ = req("POST", "/relay", {"pub": "p", "cipher": "c"}, timeout=15)
check("missing room -> 400", code == 400)
code, _, _ = req("POST", "/relay?room=" + ROOM, {"pub": "p"}, timeout=15)
check("missing cipher -> 400", code == 400)
code, _, _ = req("GET", "/tunnel/pull?room=../x", timeout=15)
check("bad room id -> 400", code == 400)
big = {"pub": "p", "cipher": "x" * (5 * 1024 * 1024)}
code, _, _ = req("POST", "/relay?room=" + ROOM, big, timeout=60)
check("oversize frame -> 413", code == 413, str(code))

# 6) push for unknown id is a harmless 200
code, _, _ = req("POST", "/tunnel/push?room=" + ROOM, {"id": "nope", "cipher": "x"}, timeout=15)
check("push unknown id -> 200", code == 200)

# 7) static routes
code, body, hdr = req("GET", "/.well-known/assetlinks.json", timeout=15)
check("assetlinks", code == 200 and b"app.helmdeck" in body)
code, body, _ = req("GET", "/pair?c=%22%3E%3Cscript%3Ealert(1)%3C/script%3E", timeout=15)
check("pair page escapes c (no raw <script> from input)", code == 200 and b"<script>alert(1)</script>" not in body)
code, body, _ = req("GET", "/privacy", timeout=15)
check("privacy page", code == 200 and b"Datenschutz" in body)

# 8) OTA surface (may legitimately 404 when no bundle is staged)
code, body, hdr = req("GET", "/updates/manifest", timeout=15,
                      headers={"expo-platform": "android", "expo-runtime-version": "0.0.0"})
check("manifest wrong runtime -> 404 (or 200 legacy)", code in (404, 200), str(code))
code, _, _ = req("GET", "/updates/assets?path=C:/Windows/win.ini", timeout=15)
check("assets drive-letter path -> 404", code == 404, str(code))
code, _, _ = req("GET", "/updates/assets?path=../../x", timeout=15)
check("assets traversal -> 404", code == 404, str(code))

print("\n%d failed" % fails)
sys.exit(1 if fails else 0)
