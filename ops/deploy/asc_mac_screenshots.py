# -*- coding: utf-8 -*-
"""Push the macOS App Store screenshots (ops/tools/make_macos_appstore_screenshots.py
-> ops/docs/store/screenshots/appstore/macos-1280x800/) to the existing MAC_OS
App Store Connect version's APP_DESKTOP screenshot set, over the same
ASC_KEY_ID/ASC_ISSUER_ID/ASC_API_KEY_PATH API key as asc_metadata_draft.py -
no Transporter/Xcode/altool involved. Those are only needed for the BUILD
binary itself (the .pkg); a screenshot is a plain multipart-upload JSON:API
resource, reachable from anywhere with the key.

  py -3.12 ops/deploy/asc_mac_screenshots.py show          # read-only, current ASC state
  py -3.12 ops/deploy/asc_mac_screenshots.py apply --yes   # delete the old set, upload the new one, in order

Needs `.env` (ASC_KEY_ID / ASC_ISSUER_ID / ASC_API_KEY_PATH) - same as
ops/deploy/asc_metadata_draft.py. Run from the main box.
"""
import hashlib
import os
import sys
import urllib.request

from asc_metadata_draft import _get, _req, APP_ID  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHOT_DIR = os.path.join(ROOT, "ops", "docs", "store", "screenshots", "appstore", "macos-1280x800")
FILES = ["01-board.png", "02-card-verlauf.png", "03-wartet-auf-dich.png", "04-uebersicht.png"]
LOCALE = "de-DE"


def _mac_version():
    d = _get("/v1/apps/%s/appStoreVersions?limit=50" % APP_ID)
    for v in d.get("data", []):
        if v.get("attributes", {}).get("platform") == "MAC_OS":
            return v
    raise RuntimeError("no MAC_OS appStoreVersion on app %s - create it in the ASC web UI first" % APP_ID)


def _localization(version_id, locale):
    d = _get("/v1/appStoreVersions/%s/appStoreVersionLocalizations" % version_id)
    for l in d.get("data", []):
        if l.get("attributes", {}).get("locale") == locale:
            return l
    raise RuntimeError("no %s localization on version %s" % (locale, version_id))


def _screenshot_set(localization_id):
    d = _get("/v1/appStoreVersionLocalizations/%s/appScreenshotSets" % localization_id)
    for s in d.get("data", []):
        if s.get("attributes", {}).get("screenshotDisplayType") == "APP_DESKTOP":
            return s
    return None


def _existing_shots(set_id):
    d = _get("/v1/appScreenshotSets/%s/appScreenshots" % set_id)
    return d.get("data", [])


def _upload_one(set_id, path):
    name = os.path.basename(path)
    size = os.path.getsize(path)
    created = _req("POST", "/v1/appScreenshots", {
        "data": {"type": "appScreenshots",
                  "attributes": {"fileName": name, "fileSize": size},
                  "relationships": {"appScreenshotSet": {"data": {"type": "appScreenshotSets", "id": set_id}}}}})
    row = created["data"]
    sid = row["id"]
    ops = row["attributes"]["uploadOperations"]
    with open(path, "rb") as f:
        raw = f.read()
    for op in ops:
        chunk = raw[op["offset"]:op["offset"] + op["length"]]
        headers = {h["name"]: h["value"] for h in op.get("requestHeaders", [])}
        req = urllib.request.Request(op["url"], data=chunk, headers=headers, method=op.get("method", "PUT"))
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
    checksum = hashlib.md5(raw).hexdigest()
    _req("PATCH", "/v1/appScreenshots/%s" % sid,
         {"data": {"type": "appScreenshots", "id": sid,
                    "attributes": {"uploaded": True, "sourceFileChecksum": checksum}}})
    print("uploaded %s -> %s (%d bytes)" % (name, sid, size))
    return sid


def cmd_show():
    v = _mac_version()
    print("MAC_OS version:", v["id"], v["attributes"].get("versionString"), v["attributes"].get("appStoreState"))
    loc = _localization(v["id"], LOCALE)
    s = _screenshot_set(loc["id"])
    if not s:
        print("no APP_DESKTOP screenshot set on %s yet" % LOCALE)
        return
    print("set:", s["id"])
    for sh in _existing_shots(s["id"]):
        a = sh.get("attributes", {})
        state = (a.get("assetDeliveryState") or {}).get("state")
        print("  ", sh["id"], a.get("fileName"), state)


def cmd_apply(argv):
    if "--yes" not in argv:
        print("dry run - pass --yes to actually delete + upload. Files that would upload, in order:")
        for f in FILES:
            print("  ", f)
        return
    v = _mac_version()
    loc = _localization(v["id"], LOCALE)
    s = _screenshot_set(loc["id"])
    if not s:
        s = _req("POST", "/v1/appScreenshotSets", {
            "data": {"type": "appScreenshotSets",
                      "attributes": {"screenshotDisplayType": "APP_DESKTOP"},
                      "relationships": {"appStoreVersionLocalization":
                                        {"data": {"type": "appStoreVersionLocalizations", "id": loc["id"]}}}}})["data"]
    for sh in _existing_shots(s["id"]):
        _req("DELETE", "/v1/appScreenshots/%s" % sh["id"])
        print("deleted", sh["id"], sh.get("attributes", {}).get("fileName"))
    ids = []
    for name in FILES:
        path = os.path.join(SHOT_DIR, name)
        ids.append(_upload_one(s["id"], path))
    _req("PATCH", "/v1/appScreenshotSets/%s/relationships/appScreenshots" % s["id"],
         {"data": [{"type": "appScreenshots", "id": i} for i in ids]})
    print("order set:", ids)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "show":
        cmd_show()
    elif cmd == "apply":
        cmd_apply(sys.argv[2:])
    else:
        print("usage: asc_mac_screenshots.py show|apply [--yes]")
        sys.exit(2)
