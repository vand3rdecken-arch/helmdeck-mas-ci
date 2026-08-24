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
# of the HelmDeck release keystore (daemon/certs/apk-signing/swarmdeck-release.jks).
ASSETLINKS = [{
    "relation": ["delegate_permission/common.handle_all_urls"],
    "target": {
        "namespace": "android_app",
        "package_name": "app.helmdeck",
        "sha256_cert_fingerprints": [
            # local upload/sideload key (daemon/certs/apk-signing/swarmdeck-release.jks)
            "75:21:BA:FA:C1:AD:10:08:27:DA:BA:BA:1D:53:75:6A:07:72:B3:95:20:0A:E5:47:D6:6E:63:3C:4F:79:0D:F4",
            # Play App Signing key - Play RE-SIGNS the bundle, so a store install
            # presents THIS fingerprint. Without it App Links stay unverified on
            # store installs and pair links open the browser instead of the app.
            "72:45:C4:C4:C6:0D:3A:8E:3D:F0:C1:B2:F2:F3:48:78:49:98:3F:E2:2F:07:CE:9A:06:3E:5A:09:AE:79:2D:E2",
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

# --- privacy policy (Play Store requirement) -----------------------------
# Served at /privacy (+ /datenschutz). Embedded here because push_relay.sh
# ships ONLY relay.py - a separate html file would never reach the VM. The
# text is derived from the app's ACTUAL data flows (app/src/data/*, this
# relay, daemon/notify.py); keep it in sync when transport behavior changes.
# Play Console -> App content -> Privacy policy:
#   https://relay.helmdeck.de/privacy
PRIVACY_HTML = """<!doctype html><html lang=de><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>HelmDeck – Datenschutzerklärung / Privacy Policy</title>
<style>body{background:#0e0f10;color:#e4e6e6;font:16px/1.6 system-ui,sans-serif;
max-width:720px;margin:0 auto;padding:40px 20px}h1{font-size:26px}h2{font-size:19px;
margin-top:32px}h3{font-size:16px}a{color:#4faee8}hr{border:0;border-top:1px solid #2a2d2f;
margin:40px 0}small,.muted{color:#8b9298}table{border-collapse:collapse;width:100%;
font-size:14px}td,th{border:1px solid #2a2d2f;padding:8px;text-align:left;vertical-align:top}
</style>
<h1>Datenschutzerklärung – HelmDeck</h1>
<p class=muted>Stand: 23. August 2026 · <a href="#en">English version below</a></p>

<p>HelmDeck ist eine Fernbedienung für die eigene HelmDeck-Installation
(„Daemon") auf dem eigenen Rechner. Die App verbindet das Telefon
ausschließlich mit Infrastruktur, die die Nutzerin/der Nutzer selbst
betreibt. Es gibt kein Entwickler-Konto und keinen zentralen Dienst, der
Inhalte speichert, und keine Werbung. Die App enthält ein
Analyse-SDK (Abschnitt 2a) – standardmäßig aus, nur nach ausdrücklicher
Einwilligung aktiv.</p>

<h2>1. Verantwortlicher / Kontakt</h2>
<p>Tien Duy Vo · E-Mail:
<a href="mailto:tienduyvo@googlemail.com">tienduyvo@googlemail.com</a></p>

<h2>2. Welche Daten die App verarbeitet</h2>
<table>
<tr><th>Daten</th><th>Wohin sie gehen</th><th>Zweck</th></tr>
<tr><td>Karten, Chat-Nachrichten, Steueranweisungen</td>
<td>Nur an den eigenen Daemon – direkt (HTTPS/LAN) oder Ende-zu-Ende-verschlüsselt
über das Relay</td><td>Kernfunktion: Board bedienen, Agenten steuern</td></tr>
<tr><td>Anhänge (Fotos, Kamera-Aufnahmen, Dateien – nur auf ausdrückliche
Auswahl)</td><td>Nur an den eigenen Daemon, gleicher verschlüsselter Weg</td>
<td>Anhänge an Karten/Aufträge</td></tr>
<tr><td>Push-Token (Firebase Cloud Messaging, FCM)</td><td>An den eigenen
Daemon; technisch an Google FCM zur Zustellung</td><td>Benachrichtigungen
(z.&nbsp;B. „Antwort da", „bereit zur Abnahme")</td></tr>
<tr><td>Kopplungsdaten (Server-Adresse, Raum-ID, Schlüssel, Geräte-Token)</td>
<td>Bleiben auf dem Gerät (verschlüsselter Speicher, expo-secure-store)</td>
<td>Verbindung halten</td></tr>
<tr><td>E-Mail-Adresse und Vorname – nur wenn bei einer Registrierung
freiwillig angegeben</td><td>Loops (Loops.so), USA – E-Mail-Anbieter für
Willkommens-Nachrichten</td><td>Einführung neuer Nutzer</td></tr>
</table>
<p>Nicht verarbeitet werden: Standort, Kontakte, Werbe-IDs. Die Kamera wird
nur zum Scannen des Kopplungs-QR-Codes und für bewusst aufgenommene
Anhang-Fotos genutzt; es findet keine Hintergrund-Aufnahme statt.</p>

<h2>2a. Analyse (PostHog) – standardmäßig aus</h2>
<p>Unter Mehr → Datenschutz lässt sich „Anonyme Nutzungsstatistiken senden"
einschalten. Bleibt der Schalter unberührt, wird <b>nichts</b> an PostHog
gesendet – die App baut dann keine Verbindung zu PostHog auf. Wird
eingeschaltet, gehen anonyme Ereignisse (App-Start, Karten-Aktionen, Login)
an PostHog (EU-Cloud, Frankfurt). Übertragen werden ausschließlich grobe
Aktionsnamen und kategorische Werte (z.&nbsp;B. eine Spur, ein Modus) – nie
Karten-Inhalte, Chat-Text, Namen oder Karten-Titel. Die Einstellung gilt pro
Gerät und lässt sich jederzeit widerrufen.</p>

<h2>3. Das Relay ist „zero knowledge"</h2>
<p>Wenn Telefon und Rechner nicht im selben Netz sind, laufen Anfragen über
ein Relay. Jede Anfrage und jede Antwort wird auf dem Gerät mit NaCl
(Curve25519 / XSalsa20-Poly1305) versiegelt, bevor sie das Relay erreicht.
Das Relay sieht nur Chiffretext und eine öffentliche Raum-ID, speichert
nichts dauerhaft und führt keine Zugriffs­protokolle über Inhalte. Technisch
bedingt sind Verbindungs-Metadaten (IP-Adresse, Zeitpunkt) für den
Relay-Betreiber kurzzeitig sichtbar – Inhalte nie.</p>

<h2>4. Push-Benachrichtigungen</h2>
<p>Push-Nachrichten werden vom eigenen Daemon an das Telefon geschickt und
sind Ende-zu-Ende-verschlüsselt; Google FCM transportiert nur Chiffretext.
Für die Zustellung verarbeitet Google das Push-Token gemäß der
<a href="https://policies.google.com/privacy">Google-Datenschutzerklärung</a>.
Push ist optional (Systemberechtigung).</p>

<h2>5. Speicherung &amp; Löschung</h2>
<ul>
<li>Inhalte (Karten, Chats, Anhänge) liegen ausschließlich auf dem eigenen
Rechner der Nutzerin/des Nutzers – nicht beim App-Entwickler.</li>
<li>„Entkoppeln" auf dem Desktop widerruft den Zugriff des Telefons sofort
(Schlüssel und Raum werden rotiert) und entfernt das Push-Token.</li>
<li>Deinstallation der App löscht alle lokal gespeicherten Daten
(Kopplungsdaten, Schlüssel, Token).</li>
</ul>

<h2>6. Konten</h2>
<p>Es gibt keine beim Entwickler geführten Konten. Zugangsdaten existieren
nur gegenüber der eigenen HelmDeck-Installation; ihre Verwaltung (Anlegen,
Löschen) liegt vollständig bei deren Betreiber.</p>

<h2>7. Rechtsgrundlage (DSGVO)</h2>
<p>Die Kernfunktion (Board, Steuerung, Kopplung, Push) erfolgt zur
Vertragserfüllung bzw. auf Grundlage des berechtigten Interesses an der
Bereitstellung der selbst betriebenen Funktion (Art.&nbsp;6 Abs.&nbsp;1
lit.&nbsp;b/f DSGVO). Die Analyse unter 2a beruht auf Einwilligung
(Art.&nbsp;6 Abs.&nbsp;1 lit.&nbsp;a DSGVO) und läuft ausschließlich, solange
der Schalter aktiv ist. Die optionale Weitergabe an Loops unter 2 beruht auf
der freiwilligen Angabe bei der Registrierung. Betroffenenrechte (Auskunft,
Löschung, Berichtigung, Widerruf) richten sich an den Kontakt oben; für
Inhalte auf der eigenen Installation an deren Betreiber.</p>

<hr>
<h1 id=en>Privacy Policy – HelmDeck</h1>
<p class=muted>Last updated: August 23, 2026</p>

<p>HelmDeck is a remote control for your own HelmDeck installation
(“daemon”) on your own machine. The app connects your phone exclusively to
infrastructure you operate yourself. There is no developer-hosted account,
no central service storing your content, and no ads. The app does include
one analytics SDK (see below) – off by default, active only after explicit
consent.</p>

<h2>Controller / contact</h2>
<p>Tien Duy Vo · e-mail:
<a href="mailto:tienduyvo@googlemail.com">tienduyvo@googlemail.com</a></p>

<h2>Data the app processes</h2>
<ul>
<li><b>Cards, chat messages, steering commands</b> – sent only to your own
daemon, either directly (HTTPS/LAN) or end-to-end encrypted through the
relay.</li>
<li><b>Attachments</b> (photos, camera shots, files – only when you
explicitly pick them) – same encrypted path to your own daemon.</li>
<li><b>Push token</b> (Firebase Cloud Messaging) – registered with your own
daemon; Google FCM transports delivery. Push payloads are end-to-end
encrypted; FCM only ever carries ciphertext.</li>
<li><b>Pairing data</b> (server address, room id, keys, device token) –
stays on the device in encrypted storage (expo-secure-store).</li>
<li><b>E-mail and first name</b> – only if you voluntarily provide them when
registering – go to Loops (Loops.so, USA), our e-mail provider, to send a
welcome message to new users.</li>
</ul>
<p>Not processed: location, contacts, advertising IDs. The camera is used
only to scan the pairing QR code and for photos you deliberately attach.</p>

<h2>Analytics (PostHog) – off by default</h2>
<p>"Send anonymous usage analytics" under More → Privacy is off unless you
turn it on. Leave it untouched and <b>nothing</b> is sent to PostHog – the
app never connects to it. Turned on, anonymous events (app open, card
actions, login) go to PostHog (EU cloud, Frankfurt). Only coarse action names
and categorical values are transmitted (e.g. a lane, a mode) – never card
content, chat text, names or card titles. The setting is per device and can
be revoked at any time.</p>

<h2>Zero-knowledge relay</h2>
<p>When phone and computer are not on the same network, requests travel via
a relay. Every request/response is sealed on-device with NaCl
(Curve25519 / XSalsa20-Poly1305) before it reaches the relay. The relay sees
only ciphertext and a public room id, persists nothing, and keeps no content
logs. Connection metadata (IP address, timing) is transiently visible to the
relay operator as with any internet service – content never is.</p>

<h2>Storage &amp; deletion</h2>
<p>Your content lives solely on your own machine, not with the app
developer. Unpairing on the desktop revokes the phone's access immediately
(keys and room are rotated) and removes the push token. Uninstalling the app
deletes all locally stored data. There are no developer-hosted accounts.</p>

<h2>Legal basis (GDPR)</h2>
<p>Core functionality (board, steering, pairing, push) runs on contract
performance or the legitimate interest in providing the self-hosted function
(Art. 6(1)(b)/(f) GDPR). Analytics above runs on consent (Art. 6(1)(a) GDPR)
and only while the switch is on. Sharing with Loops is based on the
information you voluntarily provide at registration. Data subject rights
(access, erasure, rectification, withdrawal) go to the contact above; for
content on your own installation, to whoever operates it.</p>
</html>"""

# --- OTA self-hosted Expo Updates (Paseo-style silent updates) ----------
# `expo export --platform android` output lives here (metadata.json + the .hbc
# bundle + assets). We serve it as an Expo Updates v1 manifest so the app pulls
# JS/asset updates on launch - no reinstall. Unsigned application/json manifest
# (code signing is optional per the spec). Publish a new build by replacing this
# dir (deploy/push_update.sh); the manifest is rebuilt from disk each request.
#
# Channels: the build embeds `expo-channel-name` (app.json updates.requestHeaders)
# and sends it on every manifest/asset request. A channel named C is served from
# UPDATES_DIR-C when that dir exists (push_update.sh --channel C); anything else
# - including "production" - falls back to UPDATES_DIR. Channel dirs sit BESIDE
# the root dir, never inside it, so the root atomic swap can't take them along.
#
# Rollback: a `rollback.json` marker in the served dir (deploy/rollback_update.sh
# --embedded) turns the manifest response into a rollBackToEmbedded directive -
# clients revert to the APK's embedded bundle on their next silent check. The
# marker dies naturally with the next push_update.sh (dir swap).
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

def _channel_dir(channel):
    """Resolve a channel to its updates dir. Strict allow-list on the name (it
    comes from a request header) and existence check; everything else serves
    the root dir, so an unknown/typo'd channel degrades to production."""
    c = (channel or "").strip()
    if c and c != "production" and all(ch.isalnum() or ch in "._-" for ch in c) and len(c) <= 64:
        d = UPDATES_DIR + "-" + c
        if os.path.isdir(d):
            return d, c
    return UPDATES_DIR, ""

def _update_file(rel, base_dir=None):
    n = _norm(rel)
    if not n:
        return None
    fp = os.path.join(base_dir or UPDATES_DIR, *n.split("/"))
    return fp if os.path.isfile(fp) else None

def _rollback_directive(base_dir):
    """rollback.json marker -> rollBackToEmbedded directive (or None). The
    client only honours a commitTime newer than the last one it applied, so the
    deploy script stamps publish time; fall back to the marker's mtime."""
    p = os.path.join(base_dir, "rollback.json")
    if not os.path.isfile(p):
        return None
    ct = None
    try:
        with open(p, encoding="utf-8") as f:
            ct = (json.load(f) or {}).get("commitTime")
    except Exception:
        pass
    if not ct:
        ct = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(os.path.getmtime(p)))
    return {"type": "rollBackToEmbedded", "parameters": {"commitTime": ct}}

def _bundle_rtv(base_dir):
    """The runtimeVersion the bundle in base_dir was actually EXPORTED for (written
    by deploy/push_update.sh as a `runtimeVersion` file). None for a legacy bundle
    that predates the marker - the caller then falls back to the old echo behaviour
    so an already-published bundle keeps serving after this relay is deployed."""
    try:
        with open(os.path.join(base_dir or UPDATES_DIR, "runtimeVersion"), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _build_manifest(platform, base_url, runtime_version, base_dir=None, channel=""):
    base_dir = base_dir or UPDATES_DIR
    meta_path = os.path.join(base_dir, "metadata.json")
    if not os.path.isfile(meta_path):
        return None
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    fm = (meta.get("fileMetadata") or {}).get(platform)
    if not fm or not fm.get("bundle"):
        return None

    def asset(rel, ext):
        fp = _update_file(rel, base_dir)
        if not fp:
            return None
        n = _norm(rel)
        a = {"key": n, "contentType": _CT.get((ext or "").lower().lstrip("."), "application/octet-stream"),
             "url": base_url + "/updates/assets?path=" + quote(n)
                  + ("&channel=" + quote(channel) if channel else ""),
             "hash": _b64url_sha256(fp)}
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
        if p in ("/privacy", "/datenschutz"):
            body = PRIVACY_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if p == "/updates/manifest":
            # Expo Updates v1 manifest for the self-hosted OTA channel. Unsigned
            # JSON is valid per the spec (code signing optional).
            q = parse_qs(urlparse(self.path).query)
            platform = (self.headers.get("expo-platform") or (q.get("platform") or ["android"])[0])
            rtv = (self.headers.get("expo-runtime-version") or (q.get("runtime-version") or ["1.0.0"])[0])
            base_dir, channel = _channel_dir(self.headers.get("expo-channel-name")
                                             or (q.get("channel") or [""])[0])
            directive = _rollback_directive(base_dir)
            if directive is not None:
                # Directives only exist in multipart responses (the plain-JSON
                # form of the spec carries a manifest and nothing else).
                boundary = "helmdeck-" + uuid.uuid4().hex
                inner = json.dumps(directive).encode("utf-8")
                body = (b"--" + boundary.encode() + b"\r\n"
                        b"content-type: application/json\r\n"
                        b'content-disposition: form-data; name="directive"\r\n\r\n'
                        + inner + b"\r\n--" + boundary.encode() + b"--\r\n")
                self.send_response(200)
                self.send_header("expo-protocol-version", "1")
                self.send_header("expo-sfv-version", "0")
                self.send_header("cache-control", "private, max-age=0")
                self.send_header("content-type", "multipart/mixed; boundary=" + boundary)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            host = self.headers.get("host") or ""
            # VALIDATE the runtimeVersion instead of echoing it. The bundle carries
            # the rtv it was exported for; if the client's native APK is on a
            # different rtv, serving this JS would crash it on a native module the
            # APK doesn't ship (the exact case runtimeVersion exists to prevent).
            # The old code passed the CLIENT's rtv into the manifest, so the client's
            # check (embedded rtv == manifest rtv) ALWAYS passed - the protection
            # never fired. Report "no update" on a real mismatch; use the bundle's
            # true rtv in the manifest. No marker (legacy bundle) -> serve as before.
            real = _bundle_rtv(base_dir)
            if real and real != rtv:
                return self._send(404, json.dumps({"error": "no update for this runtimeVersion"}))
            man = _build_manifest(platform, "https://" + host, real or rtv, base_dir, channel)
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
            base_dir, _ = _channel_dir((q.get("channel") or [""])[0]
                                       or self.headers.get("expo-channel-name"))
            fp = _update_file((q.get("path") or [""])[0], base_dir)
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
            # Read the body FIRST, before any early return. protocol_version is
            # HTTP/1.1 (keep-alive): an early 400/503 that skips an unread POST
            # body leaves those bytes sitting in the socket, and the NEXT request
            # parsed off the same reused connection gets its request line
            # corrupted by that leftover JSON (seen live: a GET /health came back
            # as "Unsupported method" with a prior push's cipher payload spliced
            # into it). nginx used to mask this - it always buffers the full
            # request before proxying - but Cloudflare Tunnel connects directly.
            raw_body = self._body()
            rid = self._room_id()
            if not rid:
                return self._send(400, json.dumps({"error": "room required"}))
            room = _room(rid)
            if time.time() - room["last_pull"] > PULL_TIMEOUT + 15:
                return self._send(503, json.dumps({"error": "no daemon connected for this room"}))
            try:
                data = json.loads(raw_body or b"{}")
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
