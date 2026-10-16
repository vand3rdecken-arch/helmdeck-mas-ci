# -*- coding: utf-8 -*-
"""The Tauri desktop window (surfaces/desktop/tauri-app) as a REAL window.

A throw-away web app (one index.html) is served by the window's own UI server; the page
calls `window.helmdeckNative` - the bridge the real web app expects from the Electron
preload - and reports what came back to a listener this test owns. Proves, with a real
WebView2 window and no mocks:

  1. the window loads a page from http://localhost:3300 (the UI server serves it);
  2. the `#cfg` hash carries the daemon URL (no token);
  3. window.helmdeckNative exists and answers: app info (win32 / shell version / packaged),
     update status "current", the login-item toggle round-trips through the registry and is
     put back;
  4. a SPA route that does not exist falls back to the shell, and the entry page is not cached.

SAFE: it refuses to run when something already serves port 3300 (it would test that instead),
it touches the registry value HelmDeckDesktop only inside the test and removes it, and it never
opens a native dialog or an external link.

Needs the release build (cd surfaces/desktop/tauri-app && cargo build --release).
Run: py -3.12 ops/tests/test_tauri_desktop_e2e.py
"""
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import winreg
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EXE = os.path.join(ROOT, "surfaces", "desktop", "tauri-app", "target", "release", "helmdeck-desktop.exe")
_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def run_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            return winreg.QueryValueEx(k, "HelmDeckDesktop")[0]
    except OSError:
        return None


PAGE = """<!doctype html><html><body style="background:#0b0f14;color:#fff">bridge test
<script>
(async function () {
  var out = {};
  try {
    var n = window.helmdeckNative;
    out.has = !!n;
    out.hash = location.hash;
    out.info = await n.getAppInfo();
    out.update = await n.getUpdateStatus();
    out.js = await n.getJsUpdateStatus();
    out.login0 = await n.getLoginItem();
    out.login1 = await n.setLoginItem(true);
    out.login2 = await n.setLoginItem(false);
    // least privilege: anything that is not one of the four bridge commands must be refused
    out.denied = {};
    var tries = ["plugin:dialog|open", "plugin:dialog|save", "plugin:window|close", "plugin:webview|create_webview_window",
                 "plugin:event|listen", "plugin:app|app_hide", "some_unknown_command"];
    for (var i = 0; i < tries.length; i++) {
      try { await window.__TAURI_INTERNALS__.invoke(tries[i], {}); out.denied[tries[i]] = "ALLOWED"; }
      catch (e) { out.denied[tries[i]] = "refused"; }
    }
  } catch (e) { out.error = String(e); }
  fetch("http://127.0.0.1:__PORT__/r?d=" + encodeURIComponent(JSON.stringify(out)), { mode: "no-cors" });
})();
</script></body></html>"""


def main():
    if not os.path.isfile(EXE):
        print("SKIP: no release build at", EXE)
        return 0
    s = socket.socket()
    if s.connect_ex(("127.0.0.1", 3300)) == 0:
        s.close()
        print("SKIP: something already serves port 3300 - close the HelmDeck window first")
        return 0
    s.close()
    if run_value() is not None:
        print("ABORT: the login-item registry value already exists; refusing to overwrite it")
        return 1

    got = {}
    done = threading.Event()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            q = urllib.parse.urlparse(self.path)
            if q.path == "/r":
                got["d"] = urllib.parse.parse_qs(q.query).get("d", [""])[0]
                done.set()
            self.send_response(204)
            self.end_headers()

    srv = HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    dist = tempfile.mkdtemp(prefix="hd-tauri-e2e-")
    with open(os.path.join(dist, "index.html"), "w", encoding="utf-8") as f:
        f.write(PAGE.replace("__PORT__", str(port)))

    env = dict(os.environ, HELMDECK_APP_DIST=dist)
    proc = subprocess.Popen([EXE], env=env)
    try:
        check(done.wait(40), "the window loaded the page from its own UI server and the page ran")
        if not done.is_set():
            return 1
        d = got["d"]
        r = json.loads(d) if d.startswith("{") else {"error": d}
        check("error" not in r, "the bridge answered every call without an error%s" % ("" if "error" not in r else " (%s)" % r["error"]))
        check(r.get("has") is True, "window.helmdeckNative exists in the page")
        cfg = r.get("hash", "").split("#cfg=")[-1]
        decoded = base64.b64decode(urllib.parse.unquote(cfg)).decode() if cfg else ""
        check(json.loads(decoded or "{}").get("baseUrl") == "http://localhost:8140", "the #cfg hash hands the page the daemon URL (%s)" % decoded)
        check("token" not in decoded.lower(), "...and no credential")
        info = r.get("info") or {}
        check(info.get("platform") == "win32" and info.get("packaged") is True and info.get("shellVersion"),
              "getAppInfo has the Electron shape: %s" % info)
        check((r.get("update") or {}).get("state") == "current" and (r.get("js") or {}).get("state") == "current",
              "update status answers 'current' (the tray refreshes the bundle)")
        l0, l1, l2 = r.get("login0") or {}, r.get("login1") or {}, r.get("login2") or {}
        check(l0.get("openAtLogin") is False and l1.get("openAtLogin") is True and l2.get("openAtLogin") is False,
              "the login-item toggle round-trips: %s -> %s -> %s" % (l0.get("openAtLogin"), l1.get("openAtLogin"), l2.get("openAtLogin")))
        check(run_value() is None, "...and the registry value is gone again afterwards")
        den = r.get("denied") or {}
        check(den and all(v == "refused" for v in den.values()),
              "least privilege: every other command is refused (%s)" % ", ".join("%s=%s" % (k.split("|")[-1], v) for k, v in den.items()))

        # a route the SPA owns, and caching of the entry page, over real HTTP
        with urllib.request.urlopen("http://localhost:3300/chat/some-card", timeout=5) as resp:
            body = resp.read().decode()
            check("bridge test" in body, "an unknown client-side route falls back to the shell")
            check("no-store" in (resp.headers.get("Cache-Control") or ""), "the entry page is served no-store")
    finally:
        proc.kill()
        srv.shutdown()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, "HelmDeckDesktop")
        except OSError:
            pass
        subprocess.run(["taskkill", "/F", "/IM", "msedgewebview2.exe", "/FI", "STATUS eq RUNNING"], capture_output=True) if False else None
    print()
    if _fails:
        print("=== %d FAILED ===" % len(_fails))
        return 1
    print("tauri-desktop e2e: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
