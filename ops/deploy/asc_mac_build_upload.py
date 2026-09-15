# -*- coding: utf-8 -*-
"""Push an already-signed macOS .pkg (built + signed on the GitHub Actions Mac
runner via desktop-mac-mas.yml, downloaded with `gh run download`) to App
Store Connect over the App Store Connect API's BuildUpload resource
(shipped in API 4.1, Oct 2025) - no Transporter/Xcode/altool, no Mac needed
for the transport. Same ASC_KEY_ID/ASC_ISSUER_ID/ASC_API_KEY_PATH key as
asc_metadata_draft.py / asc_mac_screenshots.py.

This uploads a BUILD. It does NOT attach it to an appStoreVersion (that is
`_req("PATCH", "/v1/appStoreVersions/{id}/relationships/build", ...)`, see
asc_store_release.py cmd_attach) and it does NOT submit for review (that is
POST /v1/appStoreVersionSubmissions, asc_store_release.py cmd_submit) -
both stay separate, deliberate, human-triggered steps.

  py -3.12 ops/deploy/asc_mac_build_upload.py show
  py -3.12 ops/deploy/asc_mac_build_upload.py apply --yes <path-to.pkg> [<path-to.pkg> ...]

Needs `.env` (ASC_KEY_ID / ASC_ISSUER_ID / ASC_API_KEY_PATH) - same as its
siblings. Run from the main box.
"""
import hashlib
import os
import sys
import time
import urllib.request

from asc_metadata_draft import _get, _req, APP_ID  # noqa: E402

PLATFORM = "MAC_OS"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_show():
    d = _get("/v1/apps/%s/buildUploads?limit=20" % APP_ID)
    rows = d.get("data", [])
    if not rows:
        print("no buildUploads yet")
        return
    for r in rows:
        a = r["attributes"]
        st = (a.get("state") or {}).get("state")
        print(r["id"], a.get("platform"), a.get("cfBundleShortVersionString"),
              a.get("cfBundleVersion"), st, a.get("createdDate"))
        for kind in ("errors", "warnings"):
            for e in (a.get("state") or {}).get(kind, []):
                print("   %s: %s - %s" % (kind, e.get("code"), e.get("description")))


def _create_build_upload(short_version, build_version):
    body = {"data": {"type": "buildUploads",
             "attributes": {"cfBundleVersion": build_version, "cfBundleShortVersionString": short_version,
                             "platform": PLATFORM},
             "relationships": {"app": {"data": {"type": "apps", "id": APP_ID}}}}}
    return _req("POST", "/v1/buildUploads", body)["data"]


def _create_build_upload_file(build_upload_id, path):
    name = os.path.basename(path)
    size = os.path.getsize(path)
    body = {"data": {"type": "buildUploadFiles",
             "attributes": {"fileName": name, "fileSize": size, "uti": "com.apple.pkg", "assetType": "ASSET"},
             "relationships": {"buildUpload": {"data": {"type": "buildUploads", "id": build_upload_id}}}}}
    return _req("POST", "/v1/buildUploadFiles", body)["data"]


def _upload_bytes(row, path):
    ops = row["attributes"]["uploadOperations"]
    with open(path, "rb") as f:
        raw = f.read()
    for op in ops:
        chunk = raw[op["offset"]:op["offset"] + op["length"]]
        headers = {h["name"]: h["value"] for h in op.get("requestHeaders", [])}
        req = urllib.request.Request(op["url"], data=chunk, headers=headers, method=op.get("method", "PUT"))
        with urllib.request.urlopen(req, timeout=120) as r:
            r.read()


def _mark_uploaded(file_id):
    _req("PATCH", "/v1/buildUploadFiles/%s" % file_id,
         {"data": {"type": "buildUploadFiles", "id": file_id, "attributes": {"uploaded": True}}})


def _poll_state(build_upload_id, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = _get("/v1/buildUploads/%s" % build_upload_id)
        a = d["data"]["attributes"]
        st = (a.get("state") or {}).get("state")
        print("  state:", st)
        if st in ("COMPLETE", "FAILED"):
            for kind in ("errors", "warnings", "infos"):
                for e in (a.get("state") or {}).get(kind, []):
                    print("   %s: %s - %s" % (kind, e.get("code"), e.get("description")))
            return st
        time.sleep(5)
    return "TIMEOUT"


def upload_one(path, short_version, build_version):
    print("=== %s (version %s, build %s) ===" % (os.path.basename(path), short_version, build_version))
    bu = _create_build_upload(short_version, build_version)
    print("buildUpload:", bu["id"])
    buf = _create_build_upload_file(bu["id"], path)
    print("buildUploadFile:", buf["id"])
    _upload_bytes(buf, path)
    print("bytes uploaded, sha256=%s" % _sha256(path))
    _mark_uploaded(buf["id"])
    return _poll_state(bu["id"])


def cmd_apply(argv):
    files = [a for a in argv if a != "--yes"]
    if "--yes" not in argv:
        print("dry run - pass --yes to actually upload. Files:")
        for f in files:
            print("  ", f)
        return
    if not files:
        print("usage: apply --yes <path-to.pkg> [<path-to.pkg> ...]")
        sys.exit(2)
    # Apple requires cfBundleVersion to strictly increase per upload, even for
    # a second architecture-specific .pkg of the SAME marketing version (a
    # real 409 ENTITY_ERROR.ATTRIBUTE.INVALID.DUPLICATE, not a guess) - so a
    # second file for a version already seen this run gets a disambiguating
    # ".N" suffix on the BUILD number only; cfBundleShortVersionString (the
    # marketing version shown in ASC) stays the real one.
    seen = {}
    for path in files:
        # HelmDeck-0.2.18-arm64.pkg -> 0.2.18
        base = os.path.basename(path)
        short_version = base.split("-")[1] if base.startswith("HelmDeck-") else None
        if not short_version:
            print("cannot infer version from filename %s - skipping" % base)
            continue
        n = seen.get(short_version, 0)
        seen[short_version] = n + 1
        build_version = short_version if n == 0 else "%s.%d" % (short_version, n)
        state = upload_one(path, short_version, build_version)
        print("%s -> %s" % (base, state))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "show":
        cmd_show()
    elif cmd == "apply":
        cmd_apply(sys.argv[2:])
    else:
        print("usage: asc_mac_build_upload.py show|apply [--yes <path.pkg> ...]")
        sys.exit(2)
