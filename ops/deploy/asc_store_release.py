# -*- coding: utf-8 -*-
"""App Store Connect: the one step `eas metadata` does not cover - submit the
App Store version for the real App Review.

Division of labor for the Store release (owner decision 2026-09-05: submit
directly, same as the already-live Play Store listing):

  surfaces/app/store.config.json + `eas metadata:push`  - version, listing
      text (subtitle/description/keywords/promo text/URLs), category, age
      rating (advisory), copyright, review contact/demo notes. This is
      Expo's own tool (already a project dependency, eas-cli 23.2.0+) and it
      creates the appStoreVersion itself if none exists yet - no need to
      reinvent that here. Run `npx eas-cli metadata:lint` to validate the
      config offline (works without ASC credentials); `metadata:push` needs
      the same `.env`-free `submit.production.ios` block already in
      surfaces/app/eas.json.

  this script                                            - the two things
      `eas metadata` does not do: attaching an already-processed build to
      the appStoreVersion, and the actual "submit for App Review" call
      (POST appStoreVersionSubmissions - `eas submit` only uploads a binary,
      it never puts a Store listing in the review queue).

Reuses auth/env/HTTP from asc_metadata_draft so there stays exactly one raw
ASC JSON:API client in the repo; asc_external_beta.py is the TestFlight
sibling of this file.

    show                 # read-only: appInfo, appStoreVersions, submission state
    attach <build-id>    # attach an Apple-processed build to the editable version
    submit --yes         # -> real App Review (not Beta App Review)

submit refuses without --yes: it puts the actual Store listing in front of a
real Apple reviewer, not a beta one. This script does not call submit on its
own initiative under any circumstance - that is a human decision, made after
reading `show`'s output on the main box, never inferred from a card/prompt.

Field/endpoint mapping is the best-known shape of the ASC API - run `show`
first; a 404 there means something drifted, fix it before `attach`/`submit`,
this script does not swallow HTTP errors.

Needs the same .env as asc_metadata_draft.py (ASC_KEY_ID / ASC_ISSUER_ID /
ASC_API_KEY_PATH), see DEPLOY.md 2b. Not present in an isolated card
worktree by design; run this from the main box.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asc_metadata_draft import APP_ID, _get, _req  # noqa: E402

# appStoreState values that mean "still ours to edit" rather than "in Apple's hands"
EDITABLE_VERSION_STATES = (
    "PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED",
    "METADATA_REJECTED", "WAITING_FOR_REVIEW", "INVALID_BINARY",
)


def _app_infos():
    return _get("/v1/apps/%s/appInfos" % APP_ID).get("data", [])


def _versions():
    return _get("/v1/apps/%s/appStoreVersions?limit=50&filter[platform]=IOS" % APP_ID).get("data", [])


def _editable_version():
    for v in _versions():
        if v["attributes"].get("appStoreState") in EDITABLE_VERSION_STATES:
            return v
    return None


def cmd_show(argv):
    print("--- appInfos ---")
    for info in _app_infos():
        print("  id=%s appStoreState=%s" % (info["id"], info["attributes"].get("appStoreState")))

    print("--- appStoreVersions (IOS) ---")
    for v in _versions():
        a = v["attributes"]
        build = _get("/v1/appStoreVersions/%s/build" % v["id"]).get("data")
        print("  id=%s version=%s state=%s copyright=%r build=%s" % (
            v["id"], a.get("versionString"), a.get("appStoreState"), a.get("copyright"),
            build["id"] if build else None))

    ev = _editable_version()
    if not ev:
        print("no editable appStoreVersion yet - run `eas metadata:push` first "
              "(surfaces/app/store.config.json)")
        return
    sub = _get("/v1/appStoreVersions/%s/appStoreVersionSubmission" % ev["id"]).get("data")
    print("submission on editable version %s: %s" % (
        ev["id"], sub["attributes"] if sub else "NOT SUBMITTED"))


def cmd_attach(argv):
    if not argv:
        print("usage: attach <build-id>")
        sys.exit(2)
    build_id = argv[0]
    ev = _editable_version()
    if not ev:
        print("no editable appStoreVersion - run `eas metadata:push` first")
        sys.exit(2)
    _req("PATCH", "/v1/appStoreVersions/%s/relationships/build" % ev["id"],
         {"data": {"type": "builds", "id": build_id}})
    print("build %s attached to appStoreVersion %s" % (build_id, ev["id"]))


def cmd_submit(argv):
    if "--yes" not in argv:
        print("refusing to submit without --yes (this puts the actual Store listing in "
              "front of a real Apple App Review, not the Beta App Review)")
        sys.exit(2)
    ev = _editable_version()
    if not ev:
        print("no editable appStoreVersion - run `eas metadata:push` first")
        sys.exit(2)
    existing = _get("/v1/appStoreVersions/%s/appStoreVersionSubmission" % ev["id"]).get("data")
    if existing:
        print("already submitted: id=%s" % existing["id"])
        return
    d = _req("POST", "/v1/appStoreVersionSubmissions", {
        "data": {"type": "appStoreVersionSubmissions",
                 "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": ev["id"]}}}}})
    print("submitted for App Review: id=%s (Apple typically answers in 24-48h, can take longer)"
          % d["data"]["id"])


CMDS = {"show": cmd_show, "attach": cmd_attach, "submit": cmd_submit}

if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "show"
    if c not in CMDS:
        print(__doc__)
        sys.exit(2)
    CMDS[c](sys.argv[2:])
