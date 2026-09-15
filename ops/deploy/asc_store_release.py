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
      (reviewSubmissions + reviewSubmissionItems - `eas submit` only uploads
      a binary, it never puts a Store listing in the review queue).

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


def _versions(platform="IOS"):
    return _get("/v1/apps/%s/appStoreVersions?limit=50&filter[platform]=%s" % (APP_ID, platform)).get("data", [])


def _editable_version(platform="IOS"):
    for v in _versions(platform):
        if v["attributes"].get("appStoreState") in EDITABLE_VERSION_STATES:
            return v
    return None


def _platform_arg(argv):
    """--platform MAC_OS anywhere in argv, default IOS - same knob for
    show/attach/submit so a macOS release uses this exact script, not a
    parallel copy that could drift from it."""
    if "--platform" in argv:
        i = argv.index("--platform")
        return argv[i + 1], argv[:i] + argv[i + 2:]
    return "IOS", argv


def cmd_show(argv):
    platform, argv = _platform_arg(argv)
    print("--- appInfos ---")
    for info in _app_infos():
        print("  id=%s appStoreState=%s" % (info["id"], info["attributes"].get("appStoreState")))

    print("--- appStoreVersions (%s) ---" % platform)
    for v in _versions(platform):
        a = v["attributes"]
        build = _get("/v1/appStoreVersions/%s/build" % v["id"]).get("data")
        print("  id=%s version=%s state=%s copyright=%r build=%s" % (
            v["id"], a.get("versionString"), a.get("appStoreState"), a.get("copyright"),
            build["id"] if build else None))

    ev = _editable_version(platform)
    if not ev:
        print("no editable appStoreVersion yet - run `eas metadata:push` first "
              "(surfaces/app/store.config.json)")
        return
    subs = _get("/v1/reviewSubmissions?filter[app]=%s&filter[platform]=%s" % (APP_ID, platform)).get("data", [])
    if not subs:
        print("reviewSubmissions (%s): NONE" % platform)
    for rs in subs:
        a = rs["attributes"]
        print("reviewSubmission %s state=%s submittedDate=%s" % (rs["id"], a.get("state"), a.get("submittedDate")))


def cmd_attach(argv):
    platform, argv = _platform_arg(argv)
    if not argv:
        print("usage: attach <build-id> [--platform MAC_OS]")
        sys.exit(2)
    build_id = argv[0]
    ev = _editable_version(platform)
    if not ev:
        print("no editable appStoreVersion - run `eas metadata:push` first")
        sys.exit(2)
    _req("PATCH", "/v1/appStoreVersions/%s/relationships/build" % ev["id"],
         {"data": {"type": "builds", "id": build_id}})
    print("build %s attached to appStoreVersion %s" % (build_id, ev["id"]))


def cmd_submit(argv):
    platform, argv = _platform_arg(argv)
    if "--yes" not in argv:
        print("refusing to submit without --yes (this puts the actual Store listing in "
              "front of a real Apple App Review, not the Beta App Review)")
        sys.exit(2)
    ev = _editable_version(platform)
    if not ev:
        print("no editable appStoreVersion - run `eas metadata:push` first")
        sys.exit(2)
    # appStoreVersionSubmissions is retired - the API now only allows DELETE on
    # it (403 "does not allow CREATE", measured 2026-09-15). Submission is
    # reviewSubmissions: open one per platform (or reuse a draft the web UI
    # already opened), add the version as an item, then flip submitted=true.
    q = "/v1/reviewSubmissions?filter[app]=%s&filter[platform]=%s" % (APP_ID, platform)
    for rs in _get(q).get("data", []):
        state = rs["attributes"].get("state")
        if state in ("WAITING_FOR_REVIEW", "IN_REVIEW"):
            print("already submitted: reviewSubmission %s state=%s" % (rs["id"], state))
            return
    draft = next((rs for rs in _get(q + "&filter[state]=READY_FOR_REVIEW").get("data", [])), None)
    if draft:
        rs_id = draft["id"]
        print("reusing draft reviewSubmission", rs_id)
    else:
        rs_id = _req("POST", "/v1/reviewSubmissions", {
            "data": {"type": "reviewSubmissions", "attributes": {"platform": platform},
                     "relationships": {"app": {"data": {"type": "apps", "id": APP_ID}}}}})["data"]["id"]
        print("created reviewSubmission", rs_id)
    items = _get("/v1/reviewSubmissions/%s/items?include=appStoreVersion" % rs_id).get("data", [])
    has_version = any(((it.get("relationships", {}).get("appStoreVersion") or {}).get("data") or {}).get("id") == ev["id"]
                      for it in items)
    if not has_version:
        _req("POST", "/v1/reviewSubmissionItems", {
            "data": {"type": "reviewSubmissionItems",
                     "relationships": {"reviewSubmission": {"data": {"type": "reviewSubmissions", "id": rs_id}},
                                       "appStoreVersion": {"data": {"type": "appStoreVersions", "id": ev["id"]}}}}})
        print("added appStoreVersion %s to the submission" % ev["id"])
    d = _req("PATCH", "/v1/reviewSubmissions/%s" % rs_id, {
        "data": {"type": "reviewSubmissions", "id": rs_id, "attributes": {"submitted": True}}})
    print("submitted for App Review: reviewSubmission %s state=%s (Apple typically answers in 24-48h)"
          % (rs_id, d["data"]["attributes"].get("state")))


CMDS = {"show": cmd_show, "attach": cmd_attach, "submit": cmd_submit}

if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "show"
    if c not in CMDS:
        print(__doc__)
        sys.exit(2)
    CMDS[c](sys.argv[2:])
