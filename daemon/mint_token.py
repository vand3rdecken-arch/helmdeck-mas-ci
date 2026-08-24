# -*- coding: utf-8 -*-
"""Print a NEW device token for <user> with <label>.

Operator tool. desktop/main.js used to call this at every launch and inject the
result into the UI, which made opening the desktop app an owner login with no
credential; it does not any more. What remains is a legitimate way to provision
a device by hand.

It no longer reuses an existing token, because it CANNOT: tokens are hashed at
rest (auth._token_record), so the plaintext exists only in the moment it is
minted. Each run therefore issues a fresh one - revoke the old entry in the
Users panel if it is no longer wanted.

    py -3.12 -m daemon.mint_token owner desktop
"""
import sys

from daemon.spine.auth import auth


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "owner"
    label = sys.argv[2] if len(sys.argv) > 2 else "desktop"
    # actor="cli:mint_token" and not the user: nobody authenticated here, so the
    # audit line must not read as if <name> logged in and asked for a token.
    sys.stdout.write(auth.issue_token(name, label, actor="cli:mint_token"))


if __name__ == "__main__":
    main()
