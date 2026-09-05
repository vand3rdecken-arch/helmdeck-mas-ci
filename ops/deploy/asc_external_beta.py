"""App Store Connect: EXTERNAL TestFlight test - group, review submit, public link.

Companion to `asc_metadata_draft.py`, which only fills TEXT fields. This one
changes who can install: it creates the external beta group, submits a build to
Apple's Beta App Review, and turns on the public join link. Auth/env/HTTP are
reused from asc_metadata_draft so there is exactly one ASC client in the repo.

Why this exists (owner decision 2026-09-02): iOS was scoped to INTERNAL testing
only (`ops/docs/ios-requirements.md` 7). Internal testing has no public link at
all - it is invite-by-email, capped at team members - which is why the iOS card
on helmdeck.de had nothing to link to and shipped a dead mailto instead. Going
external is what produces a real, linkable join URL.

Order matters, and each step is a separate command on purpose - none of them
runs implicitly:

    show                     # read-only: groups, link, review state
    create-group             # external group, public link still OFF
    submit <build-id>        # -> Apple Beta App Review (24-48h, outward-facing)
    attach <build-id>        # give the group the APPROVED build
    enable-link [--limit N]  # public URL goes live, prints it

`submit` and `enable-link` are the two irreversible-ish ones: the first puts the
app in front of an Apple reviewer, the second publishes a URL anyone can use.
Both refuse to run without --yes.

Needs the same `.env` as asc_metadata_draft.py (ASC_KEY_ID / ASC_ISSUER_ID /
ASC_API_KEY_PATH), see DEPLOY.md 2b.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asc_metadata_draft import APP_ID, _get, _req  # noqa: E402

GROUP_NAME = "Public Beta"


def _groups():
    d = _get("/v1/apps/%s/betaGroups?limit=200" % APP_ID)
    return d.get("data", [])


def _external_group():
    for g in _groups():
        if not g["attributes"].get("isInternalGroup"):
            return g
    return None


def _require_yes(argv, what):
    if "--yes" not in argv:
        print("refusing to %s without --yes" % what)
        sys.exit(2)


def cmd_show(argv):
    print("--- betaGroups ---")
    for g in _groups():
        a = g["attributes"]
        kind = "INTERNAL" if a.get("isInternalGroup") else "EXTERNAL"
        print("  [%s] %r id=%s" % (kind, a.get("name"), g["id"]))
        print("      publicLinkEnabled=%s link=%s limitEnabled=%s limit=%s allBuilds=%s"
              % (a.get("publicLinkEnabled"), a.get("publicLink"),
                 a.get("publicLinkLimitEnabled"), a.get("publicLinkLimit"),
                 a.get("hasAccessToAllBuilds")))

    print("--- builds + review state ---")
    d = _get("/v1/builds?filter[app]=%s&sort=-uploadedDate&limit=5" % APP_ID)
    for b in d.get("data", []):
        a = b["attributes"]
        sub = _get("/v1/builds/%s/betaAppReviewSubmission" % b["id"]).get("data")
        state = sub["attributes"].get("betaReviewState") if sub else "NOT SUBMITTED"
        print("  build %s id=%s state=%s uploaded=%s -> betaReview: %s"
              % (a.get("version"), b["id"], a.get("processingState"), a.get("uploadedDate"), state))


def cmd_create_group(argv):
    existing = _external_group()
    if existing:
        print("external group already exists: %r id=%s"
              % (existing["attributes"].get("name"), existing["id"]))
        return
    # Public link deliberately OFF at creation: a link enabled before a build has
    # passed review is a URL that greets visitors with nothing installable.
    # enable-link is the separate, explicit step once review is green.
    d = _req("POST", "/v1/betaGroups", {
        "data": {
            "type": "betaGroups",
            "attributes": {
                "name": GROUP_NAME,
                "publicLinkEnabled": False,
                "hasAccessToAllBuilds": False,
            },
            "relationships": {"app": {"data": {"type": "apps", "id": APP_ID}}},
        }})
    g = d["data"]
    print("created EXTERNAL group %r id=%s (public link still off)"
          % (g["attributes"].get("name"), g["id"]))


def cmd_submit(argv):
    if not argv or argv[0].startswith("--"):
        print("usage: submit <build-id> --yes")
        sys.exit(2)
    build_id = argv[0]
    _require_yes(argv, "submit a build to Apple Beta App Review")
    existing = _get("/v1/builds/%s/betaAppReviewSubmission" % build_id).get("data")
    if existing:
        print("already submitted: state=%s"
              % existing["attributes"].get("betaReviewState"))
        return
    d = _req("POST", "/v1/betaAppReviewSubmissions", {
        "data": {"type": "betaAppReviewSubmissions",
                 "relationships": {"build": {"data": {"type": "builds", "id": build_id}}}}})
    print("submitted -> state=%s (Apple typically answers in 24-48h)"
          % d["data"]["attributes"].get("betaReviewState"))


def cmd_attach(argv):
    if not argv:
        print("usage: attach <build-id>")
        sys.exit(2)
    build_id = argv[0]
    g = _external_group()
    if not g:
        print("no external group yet - run create-group first")
        sys.exit(2)
    _req("POST", "/v1/betaGroups/%s/relationships/builds" % g["id"],
         {"data": [{"type": "builds", "id": build_id}]})
    print("build %s attached to %r" % (build_id, g["attributes"].get("name")))


def cmd_enable_link(argv):
    _require_yes(argv, "publish a public join URL")
    g = _external_group()
    if not g:
        print("no external group yet - run create-group first")
        sys.exit(2)
    attrs = {"publicLinkEnabled": True}
    if "--limit" in argv:
        attrs["publicLinkLimitEnabled"] = True
        attrs["publicLinkLimit"] = int(argv[argv.index("--limit") + 1])
    d = _req("PATCH", "/v1/betaGroups/%s" % g["id"], {
        "data": {"type": "betaGroups", "id": g["id"], "attributes": attrs}})
    a = d["data"]["attributes"]
    print("public link enabled: %s (limit=%s)"
          % (a.get("publicLink"), a.get("publicLinkLimit")))


CMDS = {"show": cmd_show, "create-group": cmd_create_group, "submit": cmd_submit,
        "attach": cmd_attach, "enable-link": cmd_enable_link}

if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "show"
    if c not in CMDS:
        print(__doc__)
        sys.exit(2)
    CMDS[c](sys.argv[2:])
