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
import json, os, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

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
<script>location.replace("helmdeck://pair?c=__C__");</script>"""


def _room(rid):
    with _lock:
        r = _rooms.get(rid)
        if r is None:
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
