# -*- coding: utf-8 -*-
"""Reset the board to a clean slate for testing - backup first, then wipe.

A card is a DB row plus, if it ever started, a git branch + worktree (+commits
on that branch, never on main) + a recording. This removes all of that, plus the
multi-step process templates. By default it KEEPS your login, settings and
connectors, so you can log in and file fresh cards immediately. main is never
touched.

  py tools/reset.py --yes                 cards + audit + chat + processes
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
sys.path.insert(0, ROOT)


def backup():
    ts = time.strftime("%Y%m%d-%H%M%S")
    bdir = os.path.join(ROOT, "backups", "reset-" + ts)
    os.makedirs(bdir, exist_ok=True)
    for f in ("helmdeck.db", "helmdeck.db-wal", "helmdeck.db-shm"):
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
    from cells.engineer import sessions
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
    from spine.storage import db
    with db.conn() as c:
        c.execute("DELETE FROM events")
    db.bump()
    ej = os.path.join(ROOT, "events.jsonl")
    if os.path.exists(ej):
        os.remove(ej)


def log_reset(bdir, removed, total, a):
    """Append-only record that a reset happened, in a file clear_events() never
    touches - so there is a permanent trail of the erasure even though its
    CONTENT is gone. Without this, tools/reset.py could make the append-only
    events log disappear and leave no trace that it ever did.

    os_user is the OS account running the script, not a HelmDeck login: reset.py
    runs with the daemon stopped by design, so there is no authenticated
    HelmDeck actor to name here."""
    import getpass, json
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "op": "reset", "os_user": getpass.getuser(), "backup": bdir,
           "cards_removed": removed, "cards_total": total,
           "connectors": bool(a.connectors), "factory": bool(a.factory)}
    logdir = os.path.join(ROOT, "backups")
    os.makedirs(logdir, exist_ok=True)
    with open(os.path.join(logdir, "reset-log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def clear_recordings():
    from cells.engineer import sessions
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


def clear_processes():
    """Remove the multi-step workflow templates - board content, not config,
    so a clean slate drops them too."""
    p = os.path.join(DAEMON, "processes.json")
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

    # GxP: refuse the WHOLE reset, before backup() even runs, while the mode is
    # active anywhere in this installation. Two things this tool would destroy
    # with no in-band record: signed approvals (they live ON the track row,
    # spine/auth/signatures.py) via wipe_cards(), and the append-only
    # event log itself via clear_events() - "append-only audit/events" is a
    # fixed law of this repo (CLAUDE.md), not a default reset.py may override
    # for convenience. Gated on gxp.active() as a whole, not per-repo scope:
    # global events (auth, signatures, reconfig) are not tied to one repo, so a
    # regulated installation cannot have its evidence wiped by touching an
    # unrelated card.
    from spine.auth import gxp
    if gxp.active():
        print("refusing: GxP mode is active for this installation.\n"
              "Cards can carry signed approvals and the event log is "
              "append-only by policy while the mode is on - wiping either "
              "here would destroy that evidence with no record it happened.\n"
              "To reset anyway, turn the mode off first (edit/remove "
              "daemon/gxp.lock and restart the daemon) - a deliberate act, "
              "not a side effect of --yes. See docs/gxp-mode-design.md 2.7.")
        return 1

    bdir = backup()
    print("backup ->", bdir)
    ok, total = wipe_cards()
    print("deleted %d/%d cards (worktrees + branches removed)" % (ok, total))
    clear_events(); print("cleared events (economics/audit)")
    clear_recordings(); print("cleared recordings")
    clear_chat(); print("cleared copilot chat history")
    clear_processes(); print("cleared process templates")
    log_reset(bdir, ok, total, a)

    if a.connectors:
        from cells.connectors import connectors
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
          % ("nothing (factory)" if a.factory else "login, settings, connectors"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
