# -*- coding: utf-8 -*-
"""Print a device token for <user> with <label>, reusing an existing one so the
desktop doesn't pile up a new token every launch. Used by desktop/main.js to let
the served Expo web UI authenticate to the local daemon with a Bearer token (the
same auth the phone uses) - no daemon-auth weakening, no cookie coupling.

    py -3.12 mint_token.py owner desktop
"""
import json
import os
import sys

import auth

HERE = os.path.dirname(os.path.abspath(__file__))
USERS = os.path.join(HERE, "users.json")


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "owner"
    label = sys.argv[2] if len(sys.argv) > 2 else "desktop"
    try:
        with open(USERS, encoding="utf-8") as f:
            data = json.load(f)
        users = data if isinstance(data, list) else data.get("users", [])
        for u in users:
            if u.get("name") == name:
                for tk in u.get("tokens", []):
                    if tk.get("label") == label:
                        sys.stdout.write(tk["token"])   # reuse
                        return
    except (OSError, ValueError):
        pass
    sys.stdout.write(auth.issue_token(name, label))     # mint fresh


if __name__ == "__main__":
    main()
