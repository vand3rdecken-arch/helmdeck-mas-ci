# -*- coding: utf-8 -*-
"""HelmDeck desktop OTA client - Paseo's desktop auto-update mechanism ported
to this desktop's actual payload: the exported web bundle (app-dist) that the
Electron shell serves. Stdlib only, so tray.py can import it and the gate can
drive it without extra deps.

The mechanism is taken from the REAL Paseo source (~/Downloads/_paseo_src),
not invented:
  packages/app/src/surfaces/desktop/updates/update-callout-source.tsx
      silent automatic check at app start + every 30 min (CHECK_INTERVAL_MS)
  packages/app/src/surfaces/desktop/updates/desktop-app-updater.ts
      while an update is found but not yet downloaded, re-check every 10 s
      (PENDING_RECHECK_MS); silent-check errors are LOGGED, never surfaced
  packages/surfaces/desktop/src/features/auto-updater.ts
      autoDownload=true (download starts as soon as a check finds an update),
      autoInstallOnAppQuit=false - Paseo revalidates the manifest itself
      before installing on quit, silently, without forcing a relaunch
  packages/surfaces/desktop/src/main.ts
      UPDATE_QUIT_DEADLINE_MS = 5s bound on the quit-time revalidate+install

Feed: the SAME relay that serves the phone's OTA (accepted card
pm-silent-ota-expo-updates). ops/deploy/push_update.sh publishes the web export
plus a desktop.json manifest into the relay channel dir "desktop"
(/opt/helmdeck-updates-desktop); the relay's EXISTING
/updates/assets?path=...&channel=desktop endpoint serves every file - no relay
code change. "Update available" == manifest id differs from the installed
marker (the relay is the source of truth, the same rule the phone follows).

NO MONKEY PATCHES: applied state is derived from verified evidence only -
every file is sha256-checked against the manifest before a staged dir may be
swapped in, and the swap keeps the previous bundle as app-dist.old.
"""
import hashlib
import json
import os
import shutil
import socket
import time
import urllib.request
from urllib.parse import quote

# Paseo's timings (see module docstring for the exact source files).
CHECK_INTERVAL = 30 * 60          # silent check cadence
PENDING_RECHECK = 10              # retry cadence while an update is mid-download
QUIT_DEADLINE = 5                 # bound on the apply-on-quit revalidation

MANIFEST_NAME = "desktop.json"    # published by ops/deploy/push_update.sh
MARKER_NAME = ".hd-update.json"   # the applied/staged manifest, written LAST
CHANNEL = "desktop"
SHELL_PORT = 3300                 # the Electron shell's local UI server


def norm_rel(rel):
    """Manifest paths are attacker-shaped input to the filesystem writes below:
    normalise to forward slashes, refuse traversal/absolute/drive paths."""
    s = os.path.normpath((rel or "").replace("\\", "/")).replace("\\", "/")
    if not s or s == "." or s.startswith("..") or s.startswith("/") or ":" in s:
        return None
    return s


def read_relay_url(feed_path):
    """The feed base is the paired relay, mirrored by the daemon to
    relay_feed.json (spine/storage/events.sync_relay_feed) - NOT settings.json,
    which stopped being written when settings moved into helmdeck.db
    (config-consolidation phase 2, 2026-09-03). No relay configured -> no
    feed -> the updater stays dormant (Paseo's 'auto-update not available'
    dev case)."""
    try:
        with open(feed_path, encoding="utf-8") as f:
            url = (json.load(f).get("url") or "").strip().rstrip("/")
        return url or None
    except Exception:
        return None


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "helmdeck-desktop-update"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _asset_url(base, rel, cache_bust=""):
    # served by the relay's existing /updates/assets route; the channel dir
    # sits beside the phone's updates dir so the two can never clobber each other
    u = "%s/updates/assets?path=%s&channel=%s" % (base.rstrip("/"), quote(rel), CHANNEL)
    return u + ("&v=" + quote(cache_bust) if cache_bust else "")


def fetch_manifest(base, timeout=10):
    """The desktop.json manifest: {id, version, createdAt, files:[{path,sha256,size}]}."""
    raw = _get(_asset_url(base, MANIFEST_NAME, cache_bust=str(int(time.time()))), timeout)
    man = json.loads(raw.decode("utf-8"))
    if not man.get("id") or not isinstance(man.get("files"), list):
        raise ValueError("malformed desktop manifest")
    return man


def _read_marker(dirpath):
    try:
        with open(os.path.join(dirpath, MARKER_NAME), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def installed_id(app_dist):
    """The id of the bundle actually in place. None for a fresh/bundled install
    that predates the marker - then the next published manifest counts as an
    update and the state converges (the phone behaves the same way)."""
    m = _read_marker(app_dist)
    return (m or {}).get("id")


def check(base, app_dist, timeout=10):
    """Paseo checkForAppUpdate: fetch the feed, compare with what is installed.
    Returns the manifest when an update is available, else None."""
    man = fetch_manifest(base, timeout)
    return man if man["id"] != installed_id(app_dist) else None


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def stage(base, manifest, pending):
    """Download every manifest file into `pending`, verifying each sha256
    (Paseo: autoDownload - the download follows the check immediately). The
    marker is written LAST, so a torn/partial dir is never swappable. A pending
    dir already staged for this id is kept as-is."""
    if (_read_marker(pending) or {}).get("id") == manifest["id"] and verify_staged(pending):
        return
    shutil.rmtree(pending, ignore_errors=True)
    os.makedirs(pending, exist_ok=True)
    for spec in manifest["files"]:
        rel = norm_rel(spec.get("path"))
        if not rel:
            raise ValueError("manifest path rejected: %r" % (spec.get("path"),))
        blob = _get(_asset_url(base, rel, cache_bust=manifest["id"][:13]))
        if hashlib.sha256(blob).hexdigest() != spec.get("sha256"):
            raise ValueError("sha256 mismatch for %s" % rel)
        dst = os.path.join(pending, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(blob)
    with open(os.path.join(pending, MARKER_NAME), "w", encoding="utf-8") as f:
        json.dump(manifest, f)


def verify_staged(pending):
    """A staged dir may only be swapped in when the evidence still holds:
    marker present and every listed file hashes to its manifest sha256."""
    man = _read_marker(pending)
    if not man or not man.get("id"):
        return False
    try:
        for spec in man.get("files") or []:
            rel = norm_rel(spec.get("path"))
            if not rel:
                return False
            fp = os.path.join(pending, *rel.split("/"))
            if not os.path.isfile(fp) or _sha256(fp) != spec.get("sha256"):
                return False
    except OSError:
        return False
    return bool(man.get("files"))


def apply_staged(app_dist, pending):
    """Swap the verified staged bundle in, keeping the previous one as .old
    (Paseo ships no automatic rollback - allowDowngrade=false only - so the
    .old dir is the manual recovery reserve)."""
    if not verify_staged(pending):
        raise ValueError("staged dir failed verification - not applying")
    old = app_dist + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.isdir(app_dist):
        os.rename(app_dist, old)
    os.rename(pending, app_dist)


def shell_busy(port=SHELL_PORT):
    """Is the Electron shell serving its UI right now? While it is, the tray
    must not swap under it - the shell applies on its own quit, exactly
    Paseo's silent install-on-quit."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def sync_target(base, app_dist, allow_swap):
    """One full silent cycle for one target (Paseo's automatic intent):
    check -> download+verify -> apply when allowed. Returns a short status
    string; raising is reserved for callers that want the error."""
    pending = app_dist + ".pending"
    man = check(base, app_dist)
    if man is None:
        # a stale staged dir for the now-installed id is dead weight
        if (_read_marker(pending) or {}).get("id") == installed_id(app_dist):
            shutil.rmtree(pending, ignore_errors=True)
        return "up-to-date"
    stage(base, man, pending)
    if not allow_swap():
        return "staged"
    apply_staged(app_dist, pending)
    return "applied"
