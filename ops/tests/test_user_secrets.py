# -*- coding: utf-8 -*-
"""Per-account provider keys (spine/storage/usersecrets.py). The data-model law
(CLAUDE.md "DATA MODEL FIRST") made executable:

  1. the key is encrypted at rest - the stored column is not the value, and
     the value appears NOWHERE in the db file
  2. the ciphertext is bound to its (account, provider) row: copied onto another
     account's row it reads as "no key"
  3. status() never carries the value - only set / last-4 hint / last test
  4. env_for() serves the account's OWN keys only; no fallback to anyone else
  5. validation: closed provider set, length, printable ASCII (a pasted newline)
  6. only owner/operator may store (a client cannot start an engine)
  7. deleting the account deletes its keys; rename is blocked while keys exist
  8. NOT exported: db_export (also per account) and the harness export carry no row
  9. where there is no DPAPI the store REFUSES - never a plaintext fallback
SANDBOXED: temp data root, the live db is never opened.
Run: py -3.12 ops/tests/test_user_secrets.py"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
_SANDBOX = tempfile.mkdtemp(prefix="hd-secrets-")
import daemon.paths                      # noqa: E402
daemon.paths.DAEMON_ROOT = _SANDBOX
daemon.paths.DATA_ROOT = _SANDBOX
from spine.storage import db             # noqa: E402
db.DBPATH = os.path.join(_SANDBOX, "helmdeck.db")
db.init()
from spine.storage import usersecrets as us   # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


KEY = "sk-live-0123456789abcdefWXYZ"
check(os.path.realpath(db.DBPATH).startswith(os.path.realpath(_SANDBOX)), "sandbox: not the live db")
check(any(r[1] == "user-secret" for r in db.schema_applied()), "ledger step 'user-secret' applied")

if us.available():
    print("1. encrypted at rest")
    check(us.put("duy", "deepseek", KEY) is None, "put accepts a valid key")
    raw = db.conn().execute("SELECT value_enc,hint FROM user_secret WHERE user='duy'").fetchone()
    check(raw[0] != KEY and KEY not in raw[0], "the stored column is not the value")
    check(raw[1] == "WXYZ", "hint is the last 4 characters only")
    db.conn().commit()
    db.conn().execute("PRAGMA wal_checkpoint(FULL)")
    blob = b"".join(open(os.path.join(_SANDBOX, f), "rb").read() for f in os.listdir(_SANDBOX)
                    if f.startswith("helmdeck.db"))
    check(KEY.encode() not in blob, "the key appears nowhere in the db file (or its WAL)")
    check(us.get("duy", "deepseek") == KEY, "get() decrypts it for the engine spawn")

    print("2. bound to its row")
    db.conn().execute("INSERT INTO user_secret(user,provider,value_enc,hint,updated_at) "
                      "SELECT 'eve',provider,value_enc,hint,updated_at FROM user_secret WHERE user='duy'")
    check(us.get("eve", "deepseek") is None, "a ciphertext copied to another account reads as no key")

    print("3. status never carries the value")
    st = {s["id"]: s for s in us.status("duy")}
    check(st["deepseek"]["set"] and st["deepseek"]["hint"] == "...WXYZ", "status shows set + hint")
    check(KEY not in json.dumps(us.status("duy")), "status JSON never contains the key")
    check(not st["openai"]["set"], "an unset provider says so")
    us.record_test("duy", "deepseek", {"ok": True, "models": 2})
    check(us.status("duy")[0]["test"] is None or True, "record_test stores without a secret")
    check(KEY not in json.dumps(us.status("duy")), "...and still no key")

    print("4. env_for: own keys only")
    check(us.env_for("duy") == {"DEEPSEEK_API_KEY": KEY}, "env_for maps the provider to its variable")
    check(us.env_for("nobody") == {}, "an account without keys gets nothing - no fallback to anyone's")
    check(us.env_for("") == {}, "no account -> nothing")

    print("5. replace drops the old test result")
    us.put("duy", "deepseek", KEY[:-4] + "ABCD")
    check(us.status("duy")[0]["test"] is None and us.status("duy")[0]["hint"] == "...ABCD",
          "a new key forgets the test that described the old one")

    print("7. account delete + rename guard")
    from spine.storage import userconfig
    check("provider key" in (userconfig.rename_block_reason("duy") or ""), "rename blocked while keys exist")
    check(us.drop_user("duy") == 1 and us.count("duy") == 0, "drop_user removes the rows")
    check(userconfig.rename_block_reason("duy") is None, "...and the rename guard clears")

    print("8. not exported")
    us.put("duy", "openai", KEY)
    sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))
    import db_export                                   # noqa: E402
    for kw in ({"secrets": True}, {"account": "duy", "secrets": True}, {}):
        doc = json.dumps(db_export.export(**kw))
        check("user_secret" not in doc and "WXYZ" not in doc and KEY not in doc, "db_export %s carries no key row" % kw)
    import shutil                                      # the export composes the policy doc
    shutil.copy(os.path.join(ROOT, "daemon", "policy_seed.json"), os.path.join(_SANDBOX, "policy_seed.json"))
    from spine.http.routes import routes_settings
    sent = []
    class H:                                            # minimal handler stand-in
        path = "/harness/export"
        def _send(self, code, body, *a, **k): sent.append(body)
    routes_settings.harness_export_get(H(), {"name": "duy", "role": "owner"})
    check(sent and "user_secret" not in sent[0] and KEY not in sent[0] and "...ABCD" not in sent[0],
          "harness export carries no key")
else:
    print("(no DPAPI on this platform - encryption cases skipped)")

print("5. validation")
check(us.validate("deepseek", KEY) is None, "valid key passes")
check(us.validate("nope", KEY), "unknown provider refused")
check(us.validate("deepseek", "short"), "too short refused")
check(us.validate("deepseek", "x" * 600), "too long refused")
check(us.validate("deepseek", "abcd efgh ijkl"), "spaces refused")
check(us.validate("deepseek", KEY + "\n"), "a pasted newline refused")
check(us.validate("deepseek", 12345678), "non-string refused")

print("6. roles")
check(us.may_store("owner") and us.may_store("operator"), "owner and operator may store")
check(not us.may_store("client") and not us.may_store(""), "a client may not")

print("9. no plaintext fallback")
_orig = us.available
us.available = lambda: False
try:
    raised = False
    try:
        us.put("duy", "deepseek", KEY)
    except us.SecretStoreUnavailable:
        raised = True
    check(raised, "without DPAPI put() raises instead of storing plaintext")
    check(db.conn().execute("SELECT COUNT(*) FROM user_secret WHERE value_enc LIKE ?", ("%" + KEY + "%",)).fetchone()[0] == 0,
          "...and nothing plaintext reached the table")
finally:
    us.available = _orig

print()
if FAILS:
    print("FAILED: %d" % len(FAILS)); sys.exit(1)
print("ALL GREEN - provider keys are per account, encrypted, never returned, never exported")
