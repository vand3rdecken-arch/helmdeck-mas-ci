# -*- coding: utf-8 -*-
"""One-shot: create the App Store Connect encryption declaration for HelmDeck
and attach it to a build. HelmDeck's E2E crypto (surfaces/app/package.json)
is tweetnacl - the standard, published NaCl construction (Curve25519/
XSalsa20-Poly1305, IETF RFC 7748), not proprietary/unpublished algorithms -
so this declares containsProprietaryCryptography=False,
containsThirdPartyCryptography=True (tweetnacl is a third-party library).
Owner decision 2026-09-15: standard-crypto exemption, not "no encryption".

  py -3.12 ops/deploy/asc_mac_encryption_declaration.py <build-id>

Needs `.env` (ASC_KEY_ID / ASC_ISSUER_ID / ASC_API_KEY_PATH), same as its
siblings.
"""
import sys

from asc_metadata_draft import _req, APP_ID  # noqa: E402

# App Store Connect caps this field at 300 characters (measured 2026-09-15).
DESCRIPTION = (
    "HelmDeck connects to the user's own self-hosted server. App-to-server "
    "content is end-to-end encrypted using the standard, published NaCl "
    "construction (Curve25519/XSalsa20-Poly1305, IETF RFC 7748) via the "
    "open-source tweetnacl library - no proprietary or unpublished "
    "cryptography."
)


def main():
    if len(sys.argv) < 2:
        print("usage: asc_mac_encryption_declaration.py <build-id> [existing-declaration-id]")
        sys.exit(2)
    build_id = sys.argv[1]
    if len(sys.argv) > 2:
        attach(sys.argv[2], build_id)
        return

    body = {"data": {"type": "appEncryptionDeclarations",
             "attributes": {
                 "appDescription": DESCRIPTION,
                 "containsProprietaryCryptography": False,
                 "containsThirdPartyCryptography": True,
                 "availableOnFrenchStore": True,
             },
             "relationships": {"app": {"data": {"type": "apps", "id": APP_ID}}}}}
    d = _req("POST", "/v1/appEncryptionDeclarations", body)
    decl_id = d["data"]["id"]
    print("created appEncryptionDeclaration:", decl_id)
    attach(decl_id, build_id)


def attach(decl_id, build_id):
    # Both directions exist in the spec; the builds-relationship side (a
    # to-many on the declaration) is the one that actually took, measured
    # 2026-09-15 - PATCHing FROM the build's own (to-one, computed) side
    # silently no-op'd, still read back null afterwards.
    _req("POST", "/v1/appEncryptionDeclarations/%s/relationships/builds" % decl_id,
         {"data": [{"type": "builds", "id": build_id}]})
    print("attached build", build_id, "to declaration", decl_id)


if __name__ == "__main__":
    main()
