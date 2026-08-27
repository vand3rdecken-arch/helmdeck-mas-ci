# Self-sandboxed check of the relay's OTA endpoints: fixture updates dirs in a
# tempdir, relay on an ephemeral localhost port, real HTTP requests. Covers the
# card's server half: channel routing, rollback directive, asset serving.
#   py -3.12 ops/tests/test_ota_relay.py
import json, os, sys, tempfile, threading, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="hd-ota-")

def make_update(d, marker):
    os.makedirs(os.path.join(d, "bundles"), exist_ok=True)
    with open(os.path.join(d, "bundles", "app.hbc"), "w") as f:
        f.write("bundle-" + marker)
    with open(os.path.join(d, "assets", "logo.png")[:0] or os.path.join(d, "logo.png"), "w") as f:
        f.write("png-" + marker)
    with open(os.path.join(d, "metadata.json"), "w") as f:
        json.dump({"fileMetadata": {"android": {
            "bundle": "bundles/app.hbc",
            "assets": [{"path": "logo.png", "ext": "png"}]}}}, f)

PROD = os.path.join(TMP, "updates")
make_update(PROD, "prod")
make_update(PROD + "-beta", "beta")

os.environ["HELMDECK_UPDATES_DIR"] = PROD
sys.path.insert(0, os.path.join(ROOT, "surfaces", "relay"))
import relay  # noqa: E402  (reads env at import)

from http.server import ThreadingHTTPServer  # noqa: E402
srv = ThreadingHTTPServer(("127.0.0.1", 0), relay.H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

def get(path, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers or {})
    with urllib.request.urlopen(req) as r:
        return r.status, dict(r.headers), r.read()

fails = []
def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        fails.append(name)

H = {"expo-platform": "android", "expo-runtime-version": "1.0.0", "expo-protocol-version": "1"}

# 1) production manifest (no channel header)
st, hd, body = get("/updates/manifest", H)
man = json.loads(body)
check("prod manifest 200 json", st == 200 and hd["content-type"] == "application/json")
check("prod manifest protocol header", hd.get("expo-protocol-version") == "1")
check("prod launchAsset has no channel param", "channel=" not in man["launchAsset"]["url"], man["launchAsset"]["url"])

# 2) unknown channel falls back to production
st2, _, body2 = get("/updates/manifest", {**H, "expo-channel-name": "nope"})
check("unknown channel -> prod manifest", st2 == 200 and json.loads(body2)["id"] == man["id"])

# 3) beta channel: own dir, channel-tagged asset urls, different bundle
st3, _, body3 = get("/updates/manifest", {**H, "expo-channel-name": "beta"})
man3 = json.loads(body3)
check("beta manifest differs", st3 == 200 and man3["id"] != man["id"])
check("beta asset url carries channel", "channel=beta" in man3["launchAsset"]["url"], man3["launchAsset"]["url"])

# 4) assets: channel-scoped + traversal rejected
st4, _, b4 = get("/updates/assets?path=bundles/app.hbc&channel=beta")
check("beta asset content", st4 == 200 and b4 == b"bundle-beta", b4[:30])
st5, _, b5 = get("/updates/assets?path=bundles/app.hbc")
check("prod asset content", st5 == 200 and b5 == b"bundle-prod", b5[:30])
try:
    st6, _, _ = get("/updates/assets?path=../updates-beta/bundles/app.hbc")
except urllib.error.HTTPError as e:
    st6 = e.code
check("traversal rejected", st6 == 404)

# 5) rollback marker on beta -> multipart directive; prod untouched
with open(os.path.join(PROD + "-beta", "rollback.json"), "w") as f:
    json.dump({"commitTime": "2026-08-04T00:00:00.000Z"}, f)
st7, hd7, b7 = get("/updates/manifest", {**H, "expo-channel-name": "beta"})
check("rollback is multipart", st7 == 200 and hd7["content-type"].startswith("multipart/mixed; boundary="))
check("rollback part is a directive", b'name="directive"' in b7 and b'"rollBackToEmbedded"' in b7, b7[:120])
check("rollback carries commitTime", b'"commitTime": "2026-08-04T00:00:00.000Z"' in b7 or b'"commitTime":"2026-08-04T00:00:00.000Z"' in b7, b7)
st8, hd8, _ = get("/updates/manifest", H)
check("prod unaffected by beta rollback", st8 == 200 and hd8["content-type"] == "application/json")

# 6) rollback marker without commitTime -> mtime fallback still yields a directive
MARKER = os.path.join(PROD + "-beta", "rollback.json")
os.remove(MARKER)
with open(MARKER, "w") as f:
    f.write("{}")
st9, hd9, b9 = get("/updates/manifest", {**H, "expo-channel-name": "beta"})
check("empty marker -> mtime commitTime", st9 == 200 and b'"commitTime"' in b9 and b'null' not in b9)

# 7) marker that isn't JSON at all -> still a directive (mtime), never a 500
with open(MARKER, "wb") as f:
    f.write(b"\x00garbage{{{")
st10, hd10, b10 = get("/updates/manifest", {**H, "expo-channel-name": "beta"})
check("corrupt marker -> directive", st10 == 200 and b'"rollBackToEmbedded"' in b10)
os.remove(MARKER)

# 8) hostile channel names: must fall back to prod, never traverse or crash
for ch in ("..", "a/b", "..%2f..", "x" * 65, "beta;echo", "."):
    stx, _, bx = get("/updates/manifest", {**H, "expo-channel-name": ch})
    check(f"channel {ch!r} -> prod fallback", stx == 200 and json.loads(bx)["id"] == man["id"])

# 9) channel dir whose bundle vanished -> clean 404
os.remove(os.path.join(PROD + "-beta", "bundles", "app.hbc"))
try:
    st11, _, _ = get("/updates/manifest", {**H, "expo-channel-name": "beta"})
except urllib.error.HTTPError as e:
    st11 = e.code
check("missing bundle -> 404", st11 == 404)

# 10) no updates dir at all (fresh VM) -> 404 for manifest and assets
relay.UPDATES_DIR = os.path.join(TMP, "gone")
for path in ("/updates/manifest", "/updates/assets?path=bundles/app.hbc"):
    try:
        stz, _, _ = get(path, H)
    except urllib.error.HTTPError as e:
        stz = e.code
    check(f"no dir -> 404 for {path.split('?')[0]}", stz == 404)
relay.UPDATES_DIR = PROD

srv.shutdown()
print()
print("ALL PASS" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)
