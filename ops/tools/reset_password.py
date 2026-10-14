# -*- coding: utf-8 -*-
"""Owner recovery: set a new password for an account FROM THE DAEMON MACHINE.

For the one case the login screen's reset code cannot cover - the owner locked
themselves out, so there is nobody left to mint a code. Same trust model as
Paseo's `paseo daemon set-password`: whoever can run commands on the machine
that holds helmdeck.db is the last authority on it.

THE DAEMON MUST BE STOPPED. The live daemon caches the users table in process
(db._users_gen) and rewrites the whole table on every token touch, so a
password written from outside is invisible to it AND gets clobbered by its next
write. This tool refuses to run while :8140 answers rather than appear to work.

    py -3.12 ops/tools/reset_password.py [NAME]

NAME defaults to the only owner. The password is typed at a hidden prompt (never
an argument: it would sit in the shell history and the process list). The change
goes through auth.set_password - the one owner of accounts - so it is audited
(actor "recovery-cli") like any other password change.
"""
import getpass
import os
import socket
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

PORT = 8140


def daemon_running(port=PORT):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.5):
            return True
    except OSError:
        return False


def main(argv):
    if daemon_running():
        print("The daemon is running on :%d. Stop it first (tray > Quit, or end the "
              "python process), run this again, then start it. A running daemon "
              "would overwrite the change." % PORT)
        return 2
    from spine.auth import auth
    users = auth.list_users()
    if not users:
        print("No accounts in the database - nothing to reset (the app's first-run "
              "screen creates the owner).")
        return 1
    name = argv[0] if argv else None
    if not name:
        owners = [u["name"] for u in users if u["role"] == "owner"]
        if len(owners) != 1:
            print("Which account? Pass its name. Accounts: " + ", ".join(u["name"] for u in users))
            return 1
        name = owners[0]
    if not any(u["name"] == name for u in users):
        print("No such account %r. Accounts: %s" % (name, ", ".join(u["name"] for u in users)))
        return 1
    pw = getpass.getpass("New password for %s (min 8): " % name)
    if pw != getpass.getpass("Again: "):
        print("The two entries differ - nothing changed.")
        return 1
    try:
        auth.set_password(name, pw, actor="recovery-cli")
    except ValueError as e:
        print("Refused: %s" % e)
        return 1
    print("Password for %s set. Start the daemon and sign in." % name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
