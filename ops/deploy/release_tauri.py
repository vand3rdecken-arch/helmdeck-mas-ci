# -*- coding: utf-8 -*-
"""Build the signed Tauri desktop installer and (only with --publish) upload it.

    py -3.12 ops/deploy/release_tauri.py --version 0.2.0                # build + sign + latest.json, upload NOTHING
    py -3.12 ops/deploy/release_tauri.py --version 0.2.0 --publish      # ...and upload to helmdeck-release

The update feed is `latest.json` on a FIXED tag, `tauri-feed`, of Tienduyvo/helmdeck-release (the URL baked
into tauri.conf.json). A fixed tag, not "latest": the Electron desktop feed uses the newest release of the
same repo, and a Tauri release must never change which release counts as newest. The installer itself goes
to its own `v<version>` release (not marked latest); `latest.json` is re-uploaded to `tauri-feed` each time.
Feed shape: {version, notes, pub_date, platforms: {"windows-x86_64": {signature, url}}}.
The installer's signature is checked by every installed app against the PUBLIC key in tauri.conf.json.

The PRIVATE key lives OUTSIDE the repo: %USERPROFILE%\\.helmdeck-keys\\updater.key. Its password is a
DPAPI blob next to it (readable only by this Windows account); it is decrypted here, handed to the
build through the environment of the child process, and never printed or written anywhere.
Lose the key or the password and no installed app can update itself again.
"""
import argparse
import ctypes
import ctypes.wintypes as w
import datetime
import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = os.path.join(ROOT, "surfaces", "desktop", "tauri-app")
KEYS = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), ".helmdeck-keys")
REPO = "Tienduyvo/helmdeck-release"
FEED_TAG = "tauri-feed"


def dpapi_unprotect(blob):
    class BLOB(ctypes.Structure):
        _fields_ = [("cb", w.DWORD), ("pb", ctypes.POINTER(ctypes.c_char))]
    inb = BLOB(len(blob), ctypes.cast(ctypes.create_string_buffer(blob, len(blob)), ctypes.POINTER(ctypes.c_char)))
    out = BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(inb), None, None, None, None, 0, ctypes.byref(out)):
        raise SystemExit("the updater key password cannot be decrypted (another Windows account?)")
    return ctypes.string_at(out.pb, out.cb).decode()


def set_version(version):
    p = os.path.join(APP, "tauri.conf.json")
    c = json.load(open(p, encoding="utf-8"))
    c["version"] = version
    json.dump(c, open(p, "w", encoding="utf-8"), indent=2)
    open(p, "a").write("\n")
    toml = os.path.join(APP, "Cargo.toml")
    t = open(toml, encoding="utf-8", newline="").read()
    t = re.sub(r'(?m)^version = "[^"]*"', 'version = "%s"' % version, t, count=1)
    open(toml, "w", encoding="utf-8", newline="").write(t)


def feed(version, notes, installer_name, signature):
    url = "https://github.com/%s/releases/download/v%s/%s" % (REPO, version, installer_name)
    return {
        "version": version,
        "notes": notes,
        "pub_date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": {"windows-x86_64": {"signature": signature, "url": url}},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--notes", default="")
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", a.version):
        sys.exit("--version must be x.y.z")
    key, pw_blob = os.path.join(KEYS, "updater.key"), os.path.join(KEYS, "updater.pass.dpapi")
    if not (os.path.isfile(key) and os.path.isfile(pw_blob)):
        sys.exit("no updater key in %s (see the header of this file)" % KEYS)
    env = dict(os.environ, TAURI_SIGNING_PRIVATE_KEY=open(key, encoding="utf-8").read().strip(), TAURI_SIGNING_PRIVATE_KEY_PASSWORD=dpapi_unprotect(open(pw_blob, "rb").read()))
    set_version(a.version)
    r = subprocess.run(["cargo", "tauri", "build"], cwd=APP, env=env)
    if r.returncode != 0:
        sys.exit("build failed")
    out = os.path.join(APP, "target", "release", "bundle", "nsis")
    exes = [f for f in glob.glob(os.path.join(out, "*-setup.exe")) if a.version in os.path.basename(f)]
    if len(exes) != 1 or not os.path.isfile(exes[0] + ".sig"):
        sys.exit("expected one signed installer for %s in %s, found %s" % (a.version, out, exes))
    exe = exes[0]
    sig = open(exe + ".sig", encoding="utf-8").read().strip()
    latest = os.path.join(out, "latest.json")
    json.dump(feed(a.version, a.notes, os.path.basename(exe), sig), open(latest, "w", encoding="utf-8"), indent=2)
    print("built   ", exe)
    print("signed  ", exe + ".sig")
    print("feed    ", latest)
    if not a.publish:
        print("not published (no --publish)")
        return
    tag = "v" + a.version
    # the installer: its own release, never "latest" (Electron's feed follows the newest release)
    subprocess.run(["gh", "release", "create", tag, "--repo", REPO, "--latest=false", "--title", "HelmDeck (Tauri) " + a.version,
                    "--notes", a.notes or tag, exe, exe + ".sig"], check=True)
    # the feed: a fixed tag, created once, its latest.json replaced on every release
    have = subprocess.run(["gh", "release", "view", FEED_TAG, "--repo", REPO], capture_output=True).returncode == 0
    if not have:
        subprocess.run(["gh", "release", "create", FEED_TAG, "--repo", REPO, "--latest=false", "--title", "Tauri update feed",
                        "--notes", "latest.json for the Tauri desktop updater. Replaced on every release."], check=True)
    subprocess.run(["gh", "release", "upload", FEED_TAG, latest, "--repo", REPO, "--clobber"], check=True)
    print("published", tag)


if __name__ == "__main__":
    main()
