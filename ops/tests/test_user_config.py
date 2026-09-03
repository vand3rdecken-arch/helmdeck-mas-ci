# -*- coding: utf-8 -*-
"""accounts-boards-prd phase 1: the account owns the config.

Drives the PRD section 7 row-1 acceptance directly:
  - two accounts hold DIFFERENT languages at the same time,
  - a fresh device hydrates the account's config on login (there is no device
    state in the answer - /me resolves it from the db),
  - a legacy device with local-only prefs pushes them up EXACTLY ONCE.

SELF-SANDBOXING, and not as a formality. `spine/storage/db.py` binds its DBPATH
from daemon.paths.DAEMON_ROOT at IMPORT time, so this file repoints that
constant at a temp dir BEFORE the first import of db/events - the same
discipline the recordings-wipe incident bought (a test that ran reset logic
against the live daemon root). Nothing here touches the real helmdeck.db,
settings.json or events.jsonl; assert it by reading DBPATH below.

Not part of run_gate.py (the gate is LIGHT by decree - parse + wire only).
Run it by hand: py -3.12 ops/tests/test_user_config.py
"""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

_SANDBOX = tempfile.mkdtemp(prefix="hd-userconfig-")
import daemon.paths
daemon.paths.DAEMON_ROOT = _SANDBOX

from spine.storage import db, events, userconfig      # noqa: E402  (after the repoint)

assert db.DBPATH.startswith(_SANDBOX), \
    "REFUSING TO RUN: db points at %s, not the sandbox" % db.DBPATH
assert events.SET.startswith(_SANDBOX), \
    "REFUSING TO RUN: settings point at %s, not the sandbox" % events.SET

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def workspace(**settings):
    db.workspace_config_replace(settings)


db.init()


# -- 1. two accounts, two devices, two languages -----------------------------
def test_two_accounts_hold_different_languages():
    workspace(policy={"lang": "de"})
    check(userconfig.resolve("ada")["lang"] == "de",
          "an account with no rows inherits the workspace language "
          "(shipping this feature resets nobody)")

    w, s, err = userconfig.write("ada", {"lang": "en"}, actor="ada")
    check(err is None and w == ["lang"], "ada saves English to her account")
    w, s, err = userconfig.write("bob", {"lang": "de"}, actor="bob")
    check(err is None and w == ["lang"], "bob saves German to his account")

    check(userconfig.resolve("ada")["lang"] == "en"
          and userconfig.resolve("bob")["lang"] == "de",
          "two accounts hold DIFFERENT languages at the same time (PRD 7.1)")

    # the workspace default moves; the accounts that CHOSE do not follow it
    workspace(policy={"lang": "en"})
    check(userconfig.resolve("bob")["lang"] == "de",
          "an owner changing the workspace language does not overwrite an "
          "account that picked one")
    check(userconfig.resolve("carol")["lang"] == "en",
          "...but an account that never picked one does follow it")


# -- 2. a fresh device hydrates from the account -----------------------------
def test_fresh_device_hydrates():
    # There is no device in this test AT ALL, which is the point: the answer a
    # new phone gets on login is a pure function of the account's rows plus the
    # workspace defaults, so a second device cannot render anything else.
    workspace(policy={"lang": "de"}, appearance={"backdrop": "mesh"})
    userconfig.write("dave", {"appearance": {"backdrop": "ember"}}, actor="dave")
    fresh = userconfig.resolve("dave")
    check(fresh == {"lang": "de", "appearance": {"backdrop": "ember"}},
          "a fresh device resolves the account's stored appearance over the "
          "workspace defaults")
    check(userconfig.stored("dave") == {"appearance": {"backdrop": "ember"}},
          "profile_keys reports only what the account CHOSE - the first-login "
          "language step keys off this, not off the resolved value")


# -- 3. the legacy device pushes up exactly once -----------------------------
def test_legacy_device_pushes_up_once():
    workspace(policy={"lang": "de"})
    check(userconfig.stored("erin") == {}, "erin's account starts empty")

    w, s, err = userconfig.write("erin", {"lang": "en"}, actor="erin", migrate=True)
    check(err is None and w == ["lang"],
          "a legacy device with a local English preference pushes it up")
    check(userconfig.resolve("erin")["lang"] == "en", "...and it lands")

    # the SAME device does it again (a reinstall, a second login, a retry)
    w, s, err = userconfig.write("erin", {"lang": "de"}, actor="erin", migrate=True)
    check(err is None and w == [] and s == ["lang"],
          "a second migration writes NOTHING and reports the key as skipped - "
          "'exactly once' is derived from the account having rows, not from a "
          "flag the device could lose or lie about")
    check(userconfig.resolve("erin")["lang"] == "en",
          "...and the value the user actually chose survives it")

    # a DIFFERENT legacy device with different local prefs, same account
    w, s, err = userconfig.write("erin", {"appearance": {"backdrop": "forest"}},
                                 actor="erin", migrate=True)
    check(w == [] and s == ["appearance"],
          "an account that already has a profile is never partially "
          "back-filled from another device (PRD 4.3: 'nobody's setup resets')")

    # ...while a NORMAL write (the user actually choosing) still goes through
    w, s, err = userconfig.write("erin", {"appearance": {"backdrop": "forest"}},
                                 actor="erin")
    check(w == ["appearance"], "an explicit write is not a migration and lands")


# -- 4. the whitelist and the bound ------------------------------------------
def test_whitelist_and_bounds():
    for bad, why in (
        ({"auto_accept_green": True}, "a workspace policy knob"),
        ({"lane_labels": {"backlog": "x"}}, "a key phase 2 owns, not phase 1"),
        ({"lang": "fr"}, "a language with no dictionary"),
        ({"lang": ["en"]}, "a non-scalar language"),
        ({"appearance": {"backdrop": "neon"}}, "an unknown backdrop"),
        ({"appearance": {"backdrop": "mesh", "evil": 1}}, "an unknown sub-key"),
        ({"appearance": "mesh"}, "appearance as a string"),
        ({}, "an empty write"),
        ("lang=en", "a non-object body"),
    ):
        w, s, err = userconfig.write("mallory", bad, actor="mallory")
        check(bool(err) and w == [], "REJECTED: %s" % why)

    big = {"appearance": {"backdrop": "m" * (userconfig.MAX_VALUE_BYTES + 10)}}
    w, s, err = userconfig.write("mallory", big, actor="mallory")
    check(bool(err) and w == [], "REJECTED: a value past the size bound")

    check(userconfig.stored("mallory") == {},
          "nothing mallory sent was stored - a rejected write is atomic, not "
          "partially applied")

    # a valid key alongside an invalid one fails the WHOLE write
    w, s, err = userconfig.write("mallory", {"lang": "en", "nope": 1}, actor="mallory")
    check(bool(err) and userconfig.stored("mallory") == {},
          "one bad key fails the whole write - a caller is never told 'ok' "
          "about a value that did not land")


# -- 5. audit + the version bump ---------------------------------------------
def test_audit_and_version_bump():
    before = db.current_version()
    userconfig.write("frank", {"lang": "en"}, actor="frank")
    check(db.current_version() > before,
          "a profile write bumps _version so another open device re-renders "
          "on the next SSE tick")

    rows = [e for e in db.events_all() if e.get("kind") == "user_config"]
    check(bool(rows), "every write emits an append-only audit event")
    last = rows[-1]
    check(last.get("user") == "frank" and last.get("keys") == ["lang"],
          "the audit line names WHO and WHICH KEYS")
    check("value" not in json.dumps(last) or "en" not in str(last.get("keys")),
          "the audit line records keys, not the user's values")

    # a write that changes nothing must not manufacture an audit line
    n = len([e for e in db.events_all() if e.get("kind") == "user_config"])
    userconfig.write("frank", {"lang": "de"}, actor="frank", migrate=True)
    check(len([e for e in db.events_all() if e.get("kind") == "user_config"]) == n,
          "a no-op migration emits no audit event")


# -- 6. the name IS the identity (PRD section 8, decided) ---------------------
def test_rename_is_blocked_while_config_exists():
    check(userconfig.rename_block_reason("nobody") is None,
          "an account with no profile could be renamed freely")
    userconfig.write("grace", {"lang": "en"}, actor="grace")
    reason = userconfig.rename_block_reason("grace")
    check(bool(reason) and "grace" in reason,
          "an account WITH a profile is blocked from being renamed, with a "
          "reason a human can act on (PRD 8: a name is an identity)")


# -- 7. deleting an account takes its profile with it ------------------------
def test_delete_drops_the_profile():
    userconfig.write("henry", {"lang": "en"}, actor="henry")
    check(db.user_config_drop_user("henry") == 1, "delete_user drops the rows")
    check(userconfig.stored("henry") == {},
          "a NEW account later created with the same name does not inherit a "
          "stranger's profile")


for fn in (test_two_accounts_hold_different_languages,
           test_fresh_device_hydrates,
           test_legacy_device_pushes_up_once,
           test_whitelist_and_bounds,
           test_audit_and_version_bump,
           test_rename_is_blocked_while_config_exists,
           test_delete_drops_the_profile):
    print(fn.__name__)
    fn()

print(("FAILED: %d" % len(_fails)) if _fails else "all user-config checks passed")
sys.exit(1 if _fails else 0)
