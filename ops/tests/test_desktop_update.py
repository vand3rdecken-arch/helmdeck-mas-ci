# -*- coding: utf-8 -*-
# Self-sandboxed check of the desktop OTA (Paseo auto-update for the desktop
# app): fixture web export + desktop.json via the REAL publisher helper
# (ops/deploy/desktop_manifest.py), served by the REAL relay (channel "desktop",
# existing /updates/assets route) on an ephemeral port, consumed by the REAL
# clients - surfaces/desktop/desktop_update.py (tray side) end-to-end, and
# surfaces/desktop/updater.js via node when node is available.
#   py -3.12 ops/tests/test_desktop_update.py
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="hd-desktop-ota-")

sys.path.insert(0, os.path.join(ROOT, "deploy"))
sys.path.insert(0, os.path.join(ROOT, "desktop"))
import desktop_manifest  # noqa: E402
import desktop_update    # noqa: E402

fails = []


def check(name, cond, detail=""):
    if cond:
        print("  ok    " + name)
    else:
        print("  FAIL  " + name + (" - " + str(detail) if detail else ""))
        fails.append(name)


def make_export(d, marker):
    """A tiny fake `expo export --platform web` output, incl. a subdir path."""
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "_expo", "static", "js", "web"), exist_ok=True)
    with open(os.path.join(d, "index.html"), "w") as f:
        f.write("<html>%s</html>" % marker)
    with open(os.path.join(d, "_expo", "static", "js", "web", "entry-%s.js" % marker), "w") as f:
        f.write("console.log('%s')" % marker)
    return desktop_manifest.write(d, "9.9.9-" + marker)


def publish(export_dir):
    """Publish the export as the relay's desktop channel dir (atomic-swap analog)."""
    dest = UPDATES + "-" + desktop_update.CHANNEL
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(export_dir, dest)


# --- relay on an ephemeral port, serving the desktop channel dir -----------
UPDATES = os.path.join(TMP, "updates")
os.makedirs(UPDATES, exist_ok=True)
EXPORT = os.path.join(TMP, "export")
man1 = make_export(EXPORT, "v1")
publish(EXPORT)

os.environ["HELMDECK_UPDATES_DIR"] = UPDATES
sys.path.insert(0, os.path.join(ROOT, "relay"))
import relay  # noqa: E402  (reads env at import)

from http.server import ThreadingHTTPServer  # noqa: E402
srv = ThreadingHTTPServer(("127.0.0.1", 0), relay.H)
BASE = "http://127.0.0.1:%d" % srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

# --- manifest shape ---------------------------------------------------------
check("manifest id is deterministic per content",
      man1["id"] == desktop_manifest.build(EXPORT, "other-version")["id"])
check("manifest lists subdir paths with forward slashes",
      any(f["path"].startswith("_expo/static/") for f in man1["files"]))

# --- python engine: fresh install -> check/stage/verify/apply --------------
APP = os.path.join(TMP, "app-dist")
PEND = APP + ".pending"
os.makedirs(APP)  # a bundled install: content present, no marker yet

got = desktop_update.check(BASE, APP)
check("fresh install (no marker) sees the published bundle as an update",
      got is not None and got["id"] == man1["id"])

r = desktop_update.sync_target(BASE, APP, allow_swap=lambda: True)
check("sync_target applies when the shell is idle", r == "applied", r)
check("applied bundle carries the marker id", desktop_update.installed_id(APP) == man1["id"])
with open(os.path.join(APP, "index.html")) as f:
    check("applied bundle serves the new content", "v1" in f.read())

check("second check is up-to-date",
      desktop_update.check(BASE, APP) is None)

# --- v2 publish -> silent cycle picks it up, v1 kept as .old ----------------
man2 = make_export(EXPORT, "v2")
publish(EXPORT)
check("new publish yields a new id", man2["id"] != man1["id"])
r = desktop_update.sync_target(BASE, APP, allow_swap=lambda: True)
check("next silent cycle applies the new publish", r == "applied", r)
with open(os.path.join(APP, "index.html")) as f:
    check("bundle content moved to v2", "v2" in f.read())
with open(os.path.join(APP + ".old", "index.html")) as f:
    check("previous bundle kept as .old (manual rollback reserve)", "v1" in f.read())

# --- busy shell: stage only, swap deferred (Paseo install-on-quit) ----------
man3 = make_export(EXPORT, "v3")
publish(EXPORT)
r = desktop_update.sync_target(BASE, APP, allow_swap=lambda: False)
check("busy shell -> staged, not applied", r == "staged", r)
check("running bundle untouched while staged",
      desktop_update.installed_id(APP) == man2["id"])
check("staged dir verified and ready", desktop_update.verify_staged(PEND))
r = desktop_update.sync_target(BASE, APP, allow_swap=lambda: True)
check("staged bundle applies once the shell is idle", r == "applied", r)
check("marker now v3", desktop_update.installed_id(APP) == man3["id"])

# --- tamper: served bytes differ from manifest hash -> refused ---------------
man4 = make_export(EXPORT, "v4")
publish(EXPORT)
with open(os.path.join(UPDATES + "-" + desktop_update.CHANNEL, "index.html"), "w") as f:
    f.write("<html>evil</html>")   # manifest still promises the v4 hash
try:
    desktop_update.sync_target(BASE, APP, allow_swap=lambda: True)
    check("tampered download refused", False, "no error raised")
except ValueError as e:
    check("tampered download refused", "sha256 mismatch" in str(e), e)
check("tamper left the running bundle alone",
      desktop_update.installed_id(APP) == man3["id"])

# --- torn staged dir can never be swapped ------------------------------------
publish(EXPORT)  # heal the channel
desktop_update.stage(BASE, desktop_update.fetch_manifest(BASE), PEND)
os.remove(os.path.join(PEND, "index.html"))
check("torn staged dir fails verification", not desktop_update.verify_staged(PEND))
try:
    desktop_update.apply_staged(APP, PEND)
    check("apply refuses a torn staged dir", False, "no error raised")
except ValueError:
    check("apply refuses a torn staged dir", True)
shutil.rmtree(PEND, ignore_errors=True)

# --- path traversal in a manifest is rejected --------------------------------
check("norm_rel rejects traversal", desktop_update.norm_rel("../evil") is None)
check("norm_rel rejects absolute", desktop_update.norm_rel("/etc/x") is None)
check("norm_rel rejects drive paths", desktop_update.norm_rel("C:/x") is None)
check("norm_rel normalises backslashes",
      desktop_update.norm_rel("_expo\\static\\a.js") == "_expo/static/a.js")

# --- shell_busy sees a listening port ----------------------------------------
probe = socket.socket()
probe.bind(("127.0.0.1", 0))
probe.listen(1)
check("shell_busy true while a shell listens",
      desktop_update.shell_busy(probe.getsockname()[1]))
probe.close()

# --- relay settings reader ----------------------------------------------------
sp = os.path.join(TMP, "settings.json")
with open(sp, "w") as f:
    json.dump({"relay": {"url": "https://relay.example/ ", "room": "r"}}, f)
check("read_relay_url strips + trims", desktop_update.read_relay_url(sp) == "https://relay.example")
check("read_relay_url None without settings",
      desktop_update.read_relay_url(os.path.join(TMP, "nope.json")) is None)

# --- the JS engine (Electron side), when node is around -----------------------
node = shutil.which("node") or (
    os.path.exists(r"C:\Program Files\nodejs\node.exe") and r"C:\Program Files\nodejs\node.exe")
if node:
    APP2 = os.path.join(TMP, "app-dist-js")
    os.makedirs(APP2)
    r = subprocess.run([node, os.path.join(ROOT, "tests", "desktop_updater_harness.cjs"),
                        BASE, APP2], capture_output=True, text=True, timeout=120)
    check("updater.js harness exits clean", r.returncode == 0,
          (r.stdout + r.stderr).strip()[-400:])
    if r.returncode == 0:
        out = json.loads(r.stdout.strip().splitlines()[-1])
        check("updater.js applied the published bundle",
              out["installedId"] == out["manifestId"])
        check("updater.js up-to-date after apply", out["upToDateAfterApply"])
        check("updater.js defers install when the quit revalidation can't reach the feed",
              out["deferredOnDeadFeed"])
else:
    print("  skip  updater.js harness (node not found)")

srv.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
if fails:
    print("FAILED: %d" % len(fails))
    sys.exit(1)
print("desktop OTA: all checks passed")
