# -*- coding: utf-8 -*-
"""Publish the notarized Mac DMG + updater payload of the Tauri desktop (built by desktop-mac-tauri.yml).

    py -3.12 ops/deploy/release_tauri_mac.py --version 0.2.32 --run 12345            # sign + stage, upload NOTHING
    py -3.12 ops/deploy/release_tauri_mac.py --version 0.2.32 --run 12345 --publish

Runs on the owner's PC, not in CI: the updater signing key (see release_tauri.py) exists only here. It downloads
the workflow artifact, signs the .app.tar.gz with that key, attaches DMG + tarball + signature to the release
v<version> (created by release_tauri.py for Windows) and ADDS the darwin platforms to latest.json on the fixed
`tauri-feed` tag, keeping the Windows entry. One universal build serves both mac architectures.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_tauri as rt  # noqa: E402  (key location, dpapi, REPO, FEED_TAG)

CI_REPO = "vand3rdecken-arch/helmdeck-mas-ci"


def gh(*args, **kw):
    return subprocess.run(["gh", *args], check=True, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--run", required=True, help="desktop-mac-tauri workflow run id on " + CI_REPO)
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", a.version):
        sys.exit("--version must be x.y.z")
    key, pw_blob = os.path.join(rt.KEYS, "updater.key"), os.path.join(rt.KEYS, "updater.pass.dpapi")
    if not (os.path.isfile(key) and os.path.isfile(pw_blob)):
        sys.exit("no updater key in %s (see release_tauri.py)" % rt.KEYS)
    env = dict(os.environ, TAURI_SIGNING_PRIVATE_KEY=open(key, encoding="utf-8").read().strip(),
               TAURI_SIGNING_PRIVATE_KEY_PASSWORD=rt.dpapi_unprotect(open(pw_blob, "rb").read()))
    d = tempfile.mkdtemp(prefix="hd-mac-")
    gh("run", "download", a.run, "--repo", CI_REPO, "-n", "helmdeck-macos-tauri", "-D", d)
    dmg = glob.glob(os.path.join(d, "*_%s_universal.dmg" % a.version))
    tgz = glob.glob(os.path.join(d, "*_%s_universal.app.tar.gz" % a.version))
    if len(dmg) != 1 or len(tgz) != 1:
        sys.exit("run %s holds no DMG/tarball for %s: %s" % (a.run, a.version, os.listdir(d)))
    dmg, tgz = dmg[0], tgz[0]
    subprocess.run(["cargo", "tauri", "signer", "sign", tgz], env=env, check=True)
    sig = open(tgz + ".sig", encoding="utf-8").read().strip()

    feed_p = os.path.join(d, "latest.json")
    gh("release", "download", rt.FEED_TAG, "--repo", rt.REPO, "-p", "latest.json", "-O", feed_p, "--clobber")
    feed = json.load(open(feed_p, encoding="utf-8"))
    if feed.get("version") != a.version:
        sys.exit("tauri-feed is at %s, not %s: publish the Windows release first (release_tauri.py)" % (feed.get("version"), a.version))
    url = "https://github.com/%s/releases/download/v%s/%s" % (rt.REPO, a.version, os.path.basename(tgz))
    for plat in ("darwin-aarch64", "darwin-x86_64"):
        feed["platforms"][plat] = {"signature": sig, "url": url}
    json.dump(feed, open(feed_p, "w", encoding="utf-8"), indent=2)
    print("dmg     ", dmg)
    print("updater ", tgz, "+ .sig")
    print("feed    ", sorted(feed["platforms"]))
    if not a.publish:
        print("not published (no --publish)")
        return
    gh("release", "upload", "v" + a.version, dmg, tgz, tgz + ".sig", "--repo", rt.REPO, "--clobber")
    gh("release", "upload", rt.FEED_TAG, feed_p, "--repo", rt.REPO, "--clobber")
    print("published", a.version)


if __name__ == "__main__":
    main()
