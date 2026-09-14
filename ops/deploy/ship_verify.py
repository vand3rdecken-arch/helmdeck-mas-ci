# -*- coding: utf-8 -*-
"""Read the runtime's OWN signal before calling a ship green - the PRD's
sharpest finding (ops/docs/backlog/agent-driven-ship/README.md SS7c): a
script/build exiting 0 is not proof anything actually reached anyone.
`push_relay.sh`'s sha256 round-trip and `push_site.sh`'s origin probe
already do this for their own paths; this is the same discipline made
callable for the ship-worker card (cells/engineer/harness/agents/
ship-worker.md), which runs it as its own Bash tool call as the last step
of every ship.

    py -3.12 ops/deploy/ship_verify.py ota      # fetch the live relay
                                                 # manifest, confirm it
                                                 # references the bundle
                                                 # just exported
    py -3.12 ops/deploy/ship_verify.py native   # cross-check app.json /
                                                 # built APK / relay's three
                                                 # version numbers agree

Prints `VERIFY: OK`/`VERIFY: FAILED` + why, exits 0/1.
"""
import json
import os
import sys
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def _ship_facts():
    sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))
    import ship_facts
    return ship_facts


def verify_ota():
    """Fetch the LIVE manifest and confirm it references the exact bundle
    just exported (its content-hashed filename) - the same round-trip
    discipline push_relay.sh's sha256 compare already uses for the APK
    channel. Every phone platform push_update.sh publishes (android AND ios)
    is checked - an iOS-only miss must not read green."""
    meta_path = os.path.join(ROOT, "surfaces", "app", "dist-ota", "metadata.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            fm = json.load(f)["fileMetadata"]
        bundles = {p: fm[p]["bundle"] for p in ("android", "ios")}
    except Exception as e:
        return False, "could not read the just-exported metadata.json to know what to verify against (%s)" % e
    sf = _ship_facts()
    dom, err = sf._relay_domain()
    if not dom:
        return False, "no relay domain resolvable to verify against (%s)" % err
    rtv = (sf._read_app_json() or {}).get("version") or "1.0.0"
    url = "https://%s/updates/manifest" % dom
    for platform, bundle in bundles.items():
        req = urllib.request.Request(url, headers={
            "expo-platform": platform, "expo-runtime-version": rtv,
            "expo-protocol-version": "1"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                body = r.read().decode("utf-8", "replace")
        except Exception as e:
            return False, "relay %s manifest fetch failed post-publish: %s" % (platform, e)
        bundle_name = os.path.basename(bundle)
        if bundle_name not in body:
            return False, ("published %s bundle %s but the live manifest at %s does "
                           "not reference it - stale cache, wrong channel, or a "
                           "publish that did not actually land" % (platform, bundle_name, url))
    return True, "live manifest at %s references the just-published android+ios bundles" % url


def verify_native():
    """A native ship must not be called green on exit 0 alone. Cross-check
    the three numbers that are supposed to agree - app.json, the built APK
    (via aapt2), and what the relay actually serves - and report a
    disagreement as the headline, not an average."""
    sf = _ship_facts()
    v = sf.live_versions()
    aj, apk, rl = v["app_json"], (v["apk"] or {}), (v["relay"] or {})
    if apk.get("state") != "present":
        return False, "no APK found on disk after a native build reported success"
    apk_vc = apk.get("versionCode")
    if apk_vc is not None and apk_vc != aj.get("versionCode"):
        return False, ("app.json versionCode %s != built APK versionCode %s - "
                       "the artifact does not match the source it claims to "
                       "be built from" % (aj.get("versionCode"), apk_vc))
    if rl.get("state") != "reachable":
        return False, ("relay /apk/version.json is not reachable post-ship (%s) "
                       "- cannot confirm the APK actually reached distribution"
                       % rl.get("why"))
    rl_vc = rl.get("versionCode")
    if rl_vc is not None and rl_vc != aj.get("versionCode"):
        return False, ("relay serves versionCode %s but app.json/the APK say "
                       "%s - push_relay.sh ran but the relay's channel is "
                       "still stale" % (rl_vc, aj.get("versionCode")))
    return True, "app.json / APK / relay all agree on versionCode %s" % aj.get("versionCode")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("ota", "native"):
        print("usage: ship_verify.py ota|native", file=sys.stderr)
        sys.exit(2)
    try:
        ok, why = (verify_ota() if mode == "ota" else verify_native())
    except Exception as e:
        ok, why = False, "verification crashed (%s) - treating as unverified, not green" % e
    print("VERIFY: %s" % ("OK" if ok else "FAILED"))
    print("WHY: %s" % why)
    sys.exit(0 if ok else 1)
