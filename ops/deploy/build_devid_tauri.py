# -*- coding: utf-8 -*-
"""Build the Developer-ID signed, notarized, stapled DMG of the TAURI desktop shell (direct download, not
the Mac App Store). macOS only. Builds only - never publishes (ops/deploy/release_tauri_mac.py does that).

    python3 ops/deploy/build_devid_tauri.py --version 0.2.32

The twin of build_mas_tauri.py (same payload, same universal .app), differently dressed: identifier
work.21stgen.helmdeck, hardened runtime without the App Sandbox (entitlements.devid.plist), no provisioning
profile. Standard Tauri shape: `cargo tauri build` signs the .app with APPLE_SIGNING_IDENTITY and notarizes +
staples it when APPLE_API_ISSUER / APPLE_API_KEY / APPLE_API_KEY_PATH are set; the DMG is then signed,
notarized and stapled here with codesign/notarytool/stapler, and `spctl --assess` is the proof printed to the log.
The updater payload (the .app.tar.gz of the stapled .app) is made here but NOT signed with the updater
key: that key lives only on the owner's PC (release_tauri_mac.py signs it there).

Env: APPLE_SIGNING_IDENTITY (the "Developer ID Application: ..." name), APPLE_API_KEY (key id),
APPLE_API_ISSUER, APPLE_API_KEY_PATH (the .p8). Output: surfaces/desktop/tauri-app/target/devid/.
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


def sh(*cmd, **kw):
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    a = ap.parse_args()
    if sys.platform != "darwin":
        sys.exit("build_devid_tauri.py must run on macOS - codesign/notarytool exist nowhere else")
    if not re.fullmatch(r"\d+\.\d+\.\d+", a.version):
        sys.exit("--version must be x.y.z")
    need = ("APPLE_SIGNING_IDENTITY", "APPLE_API_KEY", "APPLE_API_ISSUER", "APPLE_API_KEY_PATH")
    missing = [k for k in need if not os.environ.get(k)]
    if missing:
        sys.exit("missing env: " + ", ".join(missing))
    ident = os.environ["APPLE_SIGNING_IDENTITY"]

    spec = importlib.util.spec_from_file_location("bmas", os.path.join(ROOT, "ops", "deploy", "build_mas_tauri.py"))
    bmas = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bmas)
    bmas.stage_payload()

    # Overlay on top of tauri.conf.json + tauri.macos.conf.json (the MAS dress): a JSON merge patch, null deletes.
    overlay = {
        "version": a.version,
        "identifier": "work.21stgen.helmdeck",
        "bundle": {"createUpdaterArtifacts": False, "targets": ["app", "dmg"],
                   "macOS": {"entitlements": "entitlements.devid.plist", "files": {"embedded.provisionprofile": None}}},
    }
    conf = os.path.join(APP, "target", "tauri.devid.conf.json")
    os.makedirs(os.path.dirname(conf), exist_ok=True)
    json.dump(overlay, open(conf, "w", encoding="utf-8"))
    # Cargo.toml carries the version too (release_tauri.set_version does both)
    toml = os.path.join(APP, "Cargo.toml")
    t = open(toml, encoding="utf-8", newline="").read()
    open(toml, "w", encoding="utf-8", newline="").write(re.sub(r'(?m)^version = "[^"]*"', 'version = "%s"' % a.version, t, count=1))

    sh("cargo", "tauri", "build", "--target", "universal-apple-darwin", "--bundles", "app,dmg", "--config", conf, cwd=APP)
    bundle = os.path.join(APP, "target", "universal-apple-darwin", "release", "bundle")
    apps = glob.glob(os.path.join(bundle, "macos", "*.app"))
    dmgs = glob.glob(os.path.join(bundle, "dmg", "*.dmg"))
    if len(apps) != 1 or len(dmgs) != 1:
        sys.exit("expected one .app and one .dmg, found %s %s" % (apps, dmgs))
    app, dmg = apps[0], dmgs[0]

    out = os.path.join(APP, "target", "devid")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    final_dmg = os.path.join(out, "HelmDeck_%s_universal.dmg" % a.version)
    shutil.copy2(dmg, final_dmg)

    # the .app was notarized + stapled by tauri; the DMG container gets the same treatment
    sh("codesign", "--force", "--timestamp", "--sign", ident, final_dmg)
    sh("xcrun", "notarytool", "submit", final_dmg, "--key", os.environ["APPLE_API_KEY_PATH"],
       "--key-id", os.environ["APPLE_API_KEY"], "--issuer", os.environ["APPLE_API_ISSUER"], "--wait")
    sh("xcrun", "stapler", "staple", final_dmg)

    # updater payload: tauri's own shape (a tarball holding HelmDeck.app), made from the STAPLED app
    tgz = os.path.join(out, "HelmDeck_%s_universal.app.tar.gz" % a.version)
    sh("tar", "-czf", tgz, "-C", os.path.dirname(app), os.path.basename(app))

    # the proof, in the log
    print("=== PROOF ===", flush=True)
    sh("codesign", "--verify", "--deep", "--strict", "--verbose=2", app)
    sh("xcrun", "stapler", "validate", app)
    sh("xcrun", "stapler", "validate", final_dmg)
    sh("spctl", "--assess", "--type", "execute", "-vv", app)
    sh("spctl", "--assess", "--type", "open", "--context", "context:primary-signature", "-vv", final_dmg)
    ent = subprocess.run(["codesign", "-d", "--entitlements", ":-", app], capture_output=True, text=True).stdout
    if "app-sandbox" in ent:
        sys.exit("the Developer-ID app carries the App Sandbox entitlement - wrong config merged")
    if not os.path.isfile(os.path.join(app, "Contents", "Resources", "daemon", "swarm.py")):
        sys.exit("the daemon sources are not in Contents/Resources")
    for f in sorted(os.listdir(out)):
        print("artifact: %s (%.1f MB)" % (f, os.path.getsize(os.path.join(out, f)) / 1e6))


if __name__ == "__main__":
    main()
