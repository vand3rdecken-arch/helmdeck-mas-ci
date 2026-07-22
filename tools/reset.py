# -*- coding: utf-8 -*-
"""Reset the board to a clean slate for testing - backup first, then wipe.

A card is a DB row plus, if it ever started, a git branch + worktree (+commits
on that branch, never on main) + a recording. This removes all of that. By
default it KEEPS your login, settings, process templates and connectors, so you
can log in and file fresh cards immediately. main is never touched.

  py tools/reset.py --yes                 cards + audit + chat (keep config)
  py tools/reset.py --yes --connectors    also clear connector import state
  py tools/reset.py --yes --factory       also wipe users + settings (blank)

Run with the daemon STOPPED (it holds the SQLite db). A timestamped backup of
the db + a git bundle of every branch is written under backups/ first, so a
reset is reversible: restore the db files and `git bundle unbundle` to recover.
"""
import argparse, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DAEMON = os.path.join(ROOT, "daemon")
sys.path.insert(0, DAEMON)


def backup():
    ts = time.strftime("%Y%m%d-%H%M%S")
    bdir = os.path.join(ROOT, "backups", "reset-" + ts)
    os.makedirs(bdir, exist_ok=True)
    for f in ("swarmdeck.db", "swarmdeck.db-wal", "swarmdeck.db-shm"):
        p = os.path.join(DAEMON, f)
        if os.path.exists(p):
            shutil.copy2(p, bdir)
    # every branch + commit, so even deleted card branches are recoverable
    subprocess.run(["git", "-C", ROOT, "bundle", "create",
                    os.path.join(bdir, "branches.bundle"), "--all"],
                   capture_output=True, text=True)
    for f in ("users.json", "settings.json", "processes.json",
              "copilot_log.json", "copilot_sessions.json"):
        p = os.path.join(DAEMON, f)
        if os.path.exists(p):
            shutil.copy2(p, bdir)
    return bdir


def wipe_cards():
    import sessions
    ts = sessions.list_tracks()
    ok = 0
    for t in ts:
        try:
            sessions.delete_track(t["id"])   # removes worktree + branch + row
            ok += 1
        except Exception as e:
            print("  ! could not delete %s: %s" % (t.get("branch"), str(e)[:80]))
    # prune any now-detached worktrees just in case
    subprocess.run(["git", "-C", ROOT, "worktree", "prune"], capture_output=True, text=True)
    return ok, len(ts)


def clear_events():
    import db
    with db.conn() as c:
        c.execute("DELETE FROM events")
    db.bump()
    ej = os.path.join(ROOT, "events.jsonl")
    if os.path.exists(ej):
        os.remove(ej)


def clear_recordings():
    import sessions
    rec = sessions.REC
    if os.path.isdir(rec):
        for n in os.listdir(rec):
            p = os.path.join(rec, n)
            shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)


def clear_chat():
    for f in ("copilot_log.json", "copilot_sessions.json"):
        p = os.path.join(DAEMON, f)
        if os.path.exists(p):
            os.remove(p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="required - actually do it")
    ap.add_argument("--connectors", action="store_true", help="also reset connector import state")
    ap.add_argument("--factory", action="store_true", help="also wipe users + settings")
    a = ap.parse_args()
    if not a.yes:
        print("refusing without --yes (this is destructive; a backup is made first).")
        return 1

    bdir = backup()
    print("backup ->", bdir)
    ok, total = wipe_cards()
    print("deleted %d/%d cards (worktrees + branches removed)" % (ok, total))
    clear_events(); print("cleared events (economics/audit)")
    clear_recordings(); print("cleared recordings")
    clear_chat(); print("cleared copilot chat history")

    if a.connectors:
        import connectors
        st = os.path.join(os.path.dirname(connectors.STATE), "_state.json")
        if os.path.exists(st):
            os.remove(st); print("cleared connector import state (they'll re-pull fresh)")
    if a.factory:
        for f in ("users.json", "settings.json"):
            p = os.path.join(DAEMON, f)
            if os.path.exists(p):
                os.remove(p)
        print("wiped users + settings - you'll re-create the owner login on next launch")

    print("\ndone. kept: %s. restart the daemon."
          % ("nothing (factory)" if a.factory else "login, settings, processes, connectors"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
