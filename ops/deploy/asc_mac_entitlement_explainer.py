# -*- coding: utf-8 -*-
"""One-shot: append the network.server entitlement explanation (Apple's
Resolution Center flagged it as having no apparent functionality) to the
macOS appStoreReviewDetail notes field, in English, factual - matches
surfaces/desktop/build/entitlements.mas.plist's own comment.

  py -3.12 ops/deploy/asc_mac_entitlement_explainer.py <review-detail-id>
"""
import sys

from asc_metadata_draft import _get, _req  # noqa: E402

EXPLANATION = (
    "Re: com.apple.security.network.server entitlement (Resolution Center, "
    "submission for build 0.2.18) - HelmDeck bundles a local control daemon "
    "and a small UI server that the app's own Electron renderer talks to. "
    "Both listen exclusively on loopback (127.0.0.1:8140 for the control "
    "API, 127.0.0.1:3300 for the UI), reachable only from processes on the "
    "same Mac - there is no public-facing listener. Under App Sandbox, "
    "network.server is required for the app to accept these purely local, "
    "in-app connections, even though they never leave the device. "
    "network.client separately covers the daemon's outbound connections to "
    "the user's own paired HelmDeck relay (relay.helmdeck.de). Neither "
    "entitlement is used to expose any externally reachable service."
)


def main():
    if len(sys.argv) < 2:
        print("usage: asc_mac_entitlement_explainer.py <review-detail-id>")
        sys.exit(2)
    rid = sys.argv[1]
    cur = _get("/v1/appStoreReviewDetails/%s" % rid)["data"]["attributes"]
    notes = (cur.get("notes") or "").rstrip()
    if EXPLANATION in notes:
        print("already present, skipping")
        return
    new_notes = notes + "\n\n" + EXPLANATION
    _req("PATCH", "/v1/appStoreReviewDetails/%s" % rid,
         {"data": {"type": "appStoreReviewDetails", "id": rid, "attributes": {"notes": new_notes}}})
    print("notes updated, new length:", len(new_notes))


if __name__ == "__main__":
    main()
