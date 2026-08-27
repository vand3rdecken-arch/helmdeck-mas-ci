# -*- coding: utf-8 -*-
"""Write the desktop OTA manifest (desktop.json) for an exported web bundle.

Used by ops/deploy/push_update.sh before publishing surfaces/app/dist-desktop to the relay's
"desktop" channel dir, and by ops/tests/test_desktop_update.py to build fixtures -
one source of truth for the manifest shape the desktop clients
(surfaces/desktop/desktop_update.py, surfaces/desktop/updater.js) consume:

    {"id": "<uuid5 of the content hashes>", "version": "<expo.version>",
     "createdAt": "...Z", "files": [{"path", "sha256", "size"}, ...]}

The id is derived from the sorted per-file hashes, so it is stable per build
(same rule as the relay's Expo manifest id) and any content change - and only
a content change - yields a new id.

    py -3.12 ops/deploy/desktop_manifest.py <export-dir> <version>
"""
import hashlib
import json
import os
import sys
import time
import uuid

MANIFEST_NAME = "desktop.json"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def build(export_dir, version):
    files = []
    for base, dirs, names in os.walk(export_dir):
        dirs.sort()
        for n in sorted(names):
            if n == MANIFEST_NAME:
                continue
            fp = os.path.join(base, n)
            rel = os.path.relpath(fp, export_dir).replace("\\", "/")
            files.append({"path": rel, "sha256": _sha256(fp), "size": os.path.getsize(fp)})
    if not files:
        raise SystemExit("desktop_manifest: %s is empty - nothing to publish" % export_dir)
    files.sort(key=lambda f: f["path"])
    digest = hashlib.sha256(
        "\n".join("%s:%s" % (f["path"], f["sha256"]) for f in files).encode()).hexdigest()
    return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, digest)),
            "version": version,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "files": files}


def write(export_dir, version):
    man = build(export_dir, version)
    with open(os.path.join(export_dir, MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1)
    return man


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: desktop_manifest.py <export-dir> <version>")
    m = write(sys.argv[1], sys.argv[2])
    print("%s %s (%d files)" % (m["id"], m["version"], len(m["files"])))
