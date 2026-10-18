# -*- coding: utf-8 -*-
"""Build the Mac App Store package (.pkg) of the TAURI desktop shell. macOS only. Builds only - never uploads.

    python3 ops/deploy/build_mas_tauri.py --version 0.3.0

Runs on a Mac (the CI runner of .github/workflows/desktop-mac-mas-tauri.yml): codesign, productbuild and
Tauri's macOS bundler exist nowhere else. Expects in the login/CI keychain:
  * an "Apple Distribution" (or "3rd Party Mac Developer Application") identity   -> signs the .app
  * a  "3rd Party Mac Developer Installer" (or "Mac Installer Distribution") one  -> signs the .pkg
and surfaces/desktop/build/embedded.provisionprofile (the MAC_APP_STORE profile; mac_credentials.py).

What goes into the .app (Contents/Resources): the web app (exported fresh, see build_msix_tauri.build_web)
and the daemon sources - the SAME allowlist and secret scan as the Windows packages. No tray, no relay bridge:
both are Windows-only; on a Mac the window starts the daemon itself and the relay stays in the daemon.

Upload to App Store Connect stays a separate, deliberate step (ops/deploy/asc_mac_build_upload.py or
Transporter) - this script never talks to Apple.
"""
import argparse
import glob
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = os.path.join(ROOT, "surfaces", "desktop", "tauri-app")
PROFILE = os.path.join(ROOT, "surfaces", "desktop", "build", "embedded.provisionprofile")


def identity(*names):
    out = subprocess.run(["security", "find-identity", "-v"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        m = re.search(r'"([^"]+)"', line)
        if m and any(m.group(1).startswith(n) for n in names):
            return m.group(1)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    a = ap.parse_args()
    if sys.platform != "darwin":
        sys.exit("build_mas_tauri.py must run on macOS - codesign/productbuild exist nowhere else")
    if not re.fullmatch(r"\d+\.\d+\.\d+", a.version):
        sys.exit("--version must be x.y.z")
    if not os.path.isfile(PROFILE):
        sys.exit("missing " + PROFILE + " (the MAC_APP_STORE provisioning profile)")
    app_id = identity("Apple Distribution", "3rd Party Mac Developer Application")
    pkg_id = identity("3rd Party Mac Developer Installer", "Mac Installer Distribution")
    if not (app_id and pkg_id):
        sys.exit("signing identities missing in the keychain (app: %s, installer: %s)" % (app_id, pkg_id))

    # the payload: same allowlist + secret scan + fresh web export as the Windows packages
    spec = importlib.util.spec_from_file_location("bmt", os.path.join(ROOT, "ops", "deploy", "build_msix_tauri.py"))
    bmt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bmt)
    payload = os.path.join(APP, "target", "payload")
    shutil.rmtree(payload, ignore_errors=True)
    os.makedirs(payload)
    bmt.STAGE = payload
    n = bmt.copy_allowlist()
    bmt.build_web()
    shutil.copytree(bmt.WEB_DIST, os.path.join(payload, "app-dist"))
    hits = bmt.scan_for_secrets()
    if hits:
        sys.exit("REFUSING to build - secret-shaped files in the payload:\n  " + "\n  ".join(hits))
    print("payload: %d source files + web app" % n)

    conf = os.path.join(APP, "tauri.conf.json")
    c = json.load(open(conf, encoding="utf-8"))
    c["version"] = a.version
    json.dump(c, open(conf, "w", encoding="utf-8"), indent=2)

    env = dict(os.environ, APPLE_SIGNING_IDENTITY=app_id)
    subprocess.run(["cargo", "tauri", "build", "--target", "universal-apple-darwin", "--bundles", "app"], cwd=APP, env=env, check=True)
    apps = glob.glob(os.path.join(APP, "target", "universal-apple-darwin", "release", "bundle", "macos", "*.app"))
    if len(apps) != 1:
        sys.exit("expected one .app, found %s" % apps)
    app = apps[0]
    # verify what Apple will verify: a valid signature with the sandbox entitlement and the profile inside
    subprocess.run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app], check=True)
    ent = subprocess.run(["codesign", "-d", "--entitlements", ":-", app], capture_output=True, text=True).stdout
    if "com.apple.security.app-sandbox" not in ent:
        sys.exit("the signed .app carries no App Sandbox entitlement - the Mac App Store would reject it")
    if not os.path.isfile(os.path.join(app, "Contents", "embedded.provisionprofile")):
        sys.exit("embedded.provisionprofile is not inside the .app")
    if not os.path.isfile(os.path.join(app, "Contents", "Resources", "daemon", "swarm.py")):
        sys.exit("the daemon sources are not in Contents/Resources")

    out = os.path.join(APP, "target", "mas", "HelmDeck-%s-universal.pkg" % a.version)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run(["productbuild", "--component", app, "/Applications", "--sign", pkg_id, out], check=True)
    print("package: %s (%.1f MB) - upload with asc_mac_build_upload.py / Transporter" % (out, os.path.getsize(out) / 1e6))


if __name__ == "__main__":
    main()
