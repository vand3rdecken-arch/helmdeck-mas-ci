# -*- coding: utf-8 -*-
"""HelmDeck relay - a ZERO-KNOWLEDGE reverse tunnel (Paseo's model). A phone
reaches a daemon behind NAT without port-forwarding AND the relay operator can
neither read nor forge the traffic: every request/response is NaCl-box sealed
end-to-end (see daemon/e2ee.py) before it ever touches the relay. The relay only
shuttles opaque frames, routed by a PUBLIC room id (never the encryption key).

  phone  --POST /relay?room=R  {pub, cipher}-->  relay  --GET /tunnel/pull?room=R-->  daemon
  phone  <--            {cipher}            --  relay  <--POST /tunnel/push?room=R {id,cipher}--

  * cipher = base64( nonce(24) || XSalsa20-Poly1305 ciphertext ) of the inner
    request/response - meaningless to the relay.
  * pub    = the phone's Curve25519 public key (public by definition), so the
    daemon can derive the shared key; the daemon pins it per room (TOFU).
  * room   = a public routing id handed out at pairing. Leaking it lets someone
    queue frames, but they still can't decrypt or seal valid ones.

Deploy: `python relay/relay.py` (PORT env, default 6790); front it with TLS.
Stateless, nothing persisted."""
import base64, hashlib, json, os, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

PORT = int(os.environ.get("HELMDECK_RELAY_PORT", "6790"))
# Bind to localhost when a TLS reverse proxy (nginx/Caddy) fronts the relay -
# then the plain-HTTP port is never exposed. 0.0.0.0 only for direct testing.
BIND = os.environ.get("HELMDECK_RELAY_BIND", "0.0.0.0")
PULL_TIMEOUT = 25
REPLY_TIMEOUT = 120
# app self-update channel (public by design: Android verifies the signature)
APK_DIR = os.environ.get("HELMDECK_APK_DIR", "/opt/helmdeck-apk")

_lock = threading.Lock()
_rooms = {}   # room -> {"q": [...], "cv": Condition, "waiting": {id: slot}, "last_pull": ts}

# --- phone pairing (App Links) -------------------------------------------
# Android verifies HelmDeck can own https://<relay>/pair via this file, so a
# scanned QR opens the app directly instead of the browser. Fingerprint = SHA256
# of the HelmDeck release keystore (archive/apk/swarmdeck-release.jks).
ASSETLINKS = [{
    "relation": ["delegate_permission/common.handle_all_urls"],
    "target": {
        "namespace": "android_app",
        "package_name": "app.helmdeck",
        "sha256_cert_fingerprints": [
            "75:21:BA:FA:C1:AD:10:08:27:DA:BA:BA:1D:53:75:6A:07:72:B3:95:20:0A:E5:47:D6:6E:63:3C:4F:79:0D:F4"
        ],
    },
}]
# Fallback shown only when the app is NOT installed / App Link not yet verified
# (a verified link never loads this page). Hands the code to the app or offers
# the APK. __C__ is the base64 {r,k,t} pairing code from the QR.
PAIR_HTML = """<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>HelmDeck koppeln</title>
<style>body{background:#0e0f10;color:#e4e6e6;font:16px/1.5 system-ui,sans-serif;
text-align:center;padding:40px 20px}a{display:inline-block;margin:10px;padding:12px 20px;
border-radius:10px;text-decoration:none;font-weight:600}.p{background:#2893cc;color:#fff}
.g{border:1px solid #333;color:#cacdce}</style>
<h2>HelmDeck koppeln</h2>
<p>Wenn sich die App nicht automatisch geöffnet hat:</p>
<a class=p href="helmdeck://pair?c=__C__">In HelmDeck öffnen</a><br>
<a class=g href="/apk/helmdeck.apk">HelmDeck installieren (APK)</a>
<p style="color:#6f7680;font-size:13px;margin-top:22px">Einmal installieren – Updates kommen danach automatisch, ohne Neuinstallation.</p>
<script>location.replace("helmdeck://pair?c=__C__");</script>"""

# --- OTA self-hosted Expo Updates (Paseo-style silent updates) ----------
# `expo export --platform android` output lives here (metadata.json + the .hbc
# bundle + assets). We serve it as an Expo Updates v1 manifest so the app pulls
# JS/asset updates on launch - no reinstall. Unsigned application/json manifest
# (code signing is optional per the spec). Publish a new build by replacing this
# dir (deploy/push_update.sh); the manifest is rebuilt from disk each request.
UPDATES_DIR = os.environ.get("HELMDECK_UPDATES_DIR", "/opt/helmdeck-updates")
_CT = {"hbc": "application/javascript", "js": "application/javascript",
       "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
       "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml",
       "ttf": "font/ttf", "otf": "font/otf", "json": "application/json"}

def _b64url_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return base64.urlsafe_b64encode(h.digest()).decode().rstrip("=")

def _norm(rel):
    """metadata.json paths may use backslashes (Windows export) - normalise to
    forward slashes and reject traversal."""
    s = os.path.normpath((rel or "").replace("\\", "/")).replace("\\", "/")
    return None if s.startswith("..") or s.startswith("/") else s

def _update_file(rel):
    n = _norm(rel)
    if not n:
        return None
    fp = os.path.join(UPDATES_DIR, *n.split("/"))
    return fp if os.path.isfile(fp) else None

def _build_manifest(platform, base_url, runtime_version):
    meta_path = os.path.join(UPDATES_DIR, "metadata.json")
    if not os.path.isfile(meta_path):
        return None
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    fm = (meta.get("fileMetadata") or {}).get(platform)
    if not fm or not fm.get("bundle"):
        return None

    def asset(rel, ext):
        fp = _update_file(rel)
        if not fp:
            return None
        n = _norm(rel)
        a = {"key": n, "contentType": _CT.get((ext or "").lower().lstrip("."), "application/octet-stream"),
             "url": base_url + "/updates/assets?path=" + quote(n), "hash": _b64url_sha256(fp)}
        if ext:
            a["fileExtension"] = "." + ext.lstrip(".")
        return a

    launch = asset(fm["bundle"], "")
    if not launch:
        return None
    launch["contentType"] = "application/javascript"
    launch.pop("fileExtension", None)
    assets = [a for a in (asset(x.get("path"), x.get("ext", "")) for x in fm.get("assets", [])) if a]
    # id MUST be a UUID; derive it from the bundle hash so it's stable per build
    # (the client skips an update whose id it already applied).
    uid = str(uuid.uuid5(uuid.NAMESPACE_URL, launch["hash"]))
    created = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(os.path.getmtime(meta_path)))
    return {"id": uid, "createdAt": created, "runtimeVersion": runtime_version,
            "launchAsset": launch, "assets": assets, "metadata": {}, "extra": {}}


ROOM_IDLE_GC = 3600  # daemons rotate rooms on unpair; sweep dead ones


def _room(rid):
    with _lock:
        r = _rooms.get(rid)
        if r is None:
            # GC on the growth path: drop rooms nothing pulled for an hour and
            # that hold no queued frames or waiting callers. Keeps a long-lived
            # relay from accumulating every room id it ever saw.
            now = time.time()
            for k in [k for k, v in _rooms.items()
                      if now - v["last_pull"] > ROOM_IDLE_GC
                      and not v["q"] and not v["waiting"]]:
                del _rooms[k]
            r = {"q": [], "cv": threading.Condition(_lock), "waiting": {}, "last_pull": 0.0}
            _rooms[rid] = r
        return r


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _room_id(self):
        return (parse_qs(urlparse(self.path).query).get("room") or [""])[0]

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _send(self, code, body=b""):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/health":
            return self._send(200, json.dumps({"ok": True, "rooms": len(_rooms)}))
        if p == "/updates/manifest":
            # Expo Updates v1 manifest for the self-hosted OTA channel. Unsigned
            # JSON is valid per the spec (code signing optional).
            q = parse_qs(urlparse(self.path).query)
            platform = (self.headers.get("expo-platform") or (q.get("platform") or ["android"])[0])
            rtv = (self.headers.get("expo-runtime-version") or (q.get("runtime-version") or ["1.0.0"])[0])
            host = self.headers.get("host") or ""
            man = _build_manifest(platform, "https://" + host, rtv)
            if not man:
                return self._send(404, json.dumps({"error": "no update available"}))
            body = json.dumps(man).encode("utf-8")
            self.send_response(200)
            self.send_header("expo-protocol-version", "1")
            self.send_header("expo-sfv-version", "0")
            self.send_header("cache-control", "private, max-age=0")
            self.send_header("content-type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if p == "/updates/assets":
            q = parse_qs(urlparse(self.path).query)
            fp = _update_file((q.get("path") or [""])[0])
            if not fp:
                return self._send(404, json.dumps({"error": "not found"}))
            ext = fp.rsplit(".", 1)[-1].lower() if "." in os.path.basename(fp) else ""
            with open(fp, "rb") as f:
                blob = f.read()
            self.send_response(200)
            self.send_header("content-type", _CT.get(ext, "application/octet-stream"))
            self.send_header("cache-control", "public, max-age=31536000, immutable")
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)
            return
        if p.startswith("/apk/"):
            # version.json + the signed APK, uploaded by deploy/push_relay.sh.
            # Serving them is safe: an APK signed with a different key than the
            # installed app simply refuses to install.
            name = os.path.basename(p)          # flattens any ../ attempt
            fp = os.path.join(APK_DIR, name)
            if not (name and os.path.isfile(fp)):
                return self._send(404, json.dumps({"error": "not found"}))
            ct = ("application/json" if name.endswith(".json")
                  else "application/vnd.android.package-archive")
            with open(fp, "rb") as f:
                blob = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)
            return
        if p == "/tunnel/pull":
            rid = self._room_id()
            if not rid:
                return self._send(400, json.dumps({"error": "room required"}))
            room = _room(rid)
            deadline = time.time() + PULL_TIMEOUT
            with room["cv"]:
                room["last_pull"] = time.time()
                while not room["q"]:
                    left = deadline - time.time()
                    if left <= 0:
                        return self._send(204)
                    room["cv"].wait(left)
                frame = room["q"].pop(0)
            return self._send(200, json.dumps(frame))
        if p == "/.well-known/assetlinks.json":
            body = json.dumps(ASSETLINKS)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body.encode())
            return
        if p == "/pair":
            c = (parse_qs(urlparse(self.path).query).get("c") or [""])[0]
            html = PAIR_HTML.replace("__C__", c).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return
        return self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        p = urlparse(self.path).path
        if p == "/tunnel/push":                       # daemon -> phone (response)
            room = _room(self._room_id())
            data = json.loads(self._body() or b"{}")
            rid = data.get("id")
            with room["cv"]:
                slot = room["waiting"].get(rid)
                if slot is not None:
                    slot["resp"] = data
                    slot["evt"].set()
            return self._send(200, json.dumps({"ok": True}))
        if p == "/relay":                             # phone -> daemon (request)
            rid = self._room_id()
            if not rid:
                return self._send(400, json.dumps({"error": "room required"}))
            room = _room(rid)
            if time.time() - room["last_pull"] > PULL_TIMEOUT + 15:
                return self._send(503, json.dumps({"error": "no daemon connected for this room"}))
            try:
                data = json.loads(self._body() or b"{}")
            except ValueError:
                return self._send(400, json.dumps({"error": "bad json"}))
            if not data.get("cipher") or not data.get("pub"):
                return self._send(400, json.dumps({"error": "pub + cipher required"}))
            fid = uuid.uuid4().hex
            frame = {"id": fid, "pub": data["pub"], "cipher": data["cipher"]}
            evt = threading.Event()
            slot = {"evt": evt, "resp": None}
            with room["cv"]:
                room["waiting"][fid] = slot
                room["q"].append(frame)
                room["cv"].notify()
            got = evt.wait(REPLY_TIMEOUT)
            with room["cv"]:
                room["waiting"].pop(fid, None)
            if not got or not slot["resp"]:
                return self._send(504, json.dumps({"error": "daemon offline or slow"}))
            return self._send(200, json.dumps({"cipher": slot["resp"].get("cipher", "")}))
        return self._send(404, json.dumps({"error": "not found"}))


def main():
    print("helmdeck zero-knowledge relay on %s:%d (health: /health)" % (BIND, PORT), flush=True)
    ThreadingHTTPServer((BIND, PORT), H).serve_forever()


if __name__ == "__main__":
    main()
