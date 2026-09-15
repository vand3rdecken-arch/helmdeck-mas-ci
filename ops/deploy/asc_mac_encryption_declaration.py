# -*- coding: utf-8 -*-
"""Answer a build's export compliance as EXEMPT - the API twin of the
`ITSAppUsesNonExemptEncryption: false` Info.plist key the iOS app already
ships (app.json -> ios.infoPlist). The electron-builder MAS build does not
carry that key, so App Store Connect asks per build.

Owner decision 2026-09-15: standard-crypto exemption (tweetnacl, the
published NaCl construction) - the same answer the iOS build already gives.

Do NOT create an appEncryptionDeclaration for this. A declaration is the
"documentation required" path (non-exempt / French import filing): it expects
an uploaded document, and one created without it shows as "Upload Failed"
in ASC and blocks submission with "the selected export compliance must be
approved" (measured 2026-09-15, declaration 82c8c325 - the API offers no
DELETE for declarations, so a wrong one can only be unlinked, not removed).

  py -3.12 ops/deploy/asc_mac_encryption_declaration.py <build-id>

Needs `.env` (ASC_KEY_ID / ASC_ISSUER_ID / ASC_API_KEY_PATH), same as its
siblings.
"""
import sys

from asc_metadata_draft import _get, _req  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("usage: asc_mac_encryption_declaration.py <build-id>")
        sys.exit(2)
    build_id = sys.argv[1]

    linked = _get("/v1/builds/%s/relationships/appEncryptionDeclaration" % build_id).get("data")
    if linked:
        _req("PATCH", "/v1/builds/%s/relationships/appEncryptionDeclaration" % build_id, {"data": None})
        print("unlinked declaration", linked["id"])

    _req("PATCH", "/v1/builds/%s" % build_id,
         {"data": {"type": "builds", "id": build_id,
                   "attributes": {"usesNonExemptEncryption": False}}})

    b = _get("/v1/builds/%s" % build_id)["data"]["attributes"]
    still = _get("/v1/builds/%s/relationships/appEncryptionDeclaration" % build_id).get("data")
    print("usesNonExemptEncryption =", b.get("usesNonExemptEncryption"))
    print("linked declaration      =", still["id"] if still else None)


if __name__ == "__main__":
    main()
