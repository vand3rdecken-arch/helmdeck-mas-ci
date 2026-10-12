# -*- coding: utf-8 -*-
"""The account's provider keys reach OpenCode - and ONLY OpenCode.
  1. opencode_driver._env(cfg, account) carries that account's keys, wins over a
     plaintext `env` row, and carries nothing for an account without keys
  2. another account's keys never appear (no fallback)
  3. spawnenv._card_env (the overlay EVERY engine gets) never carries a provider
     variable: a claude process seeing ANTHROPIC_API_KEY would leave the plan for
     API billing
  4. the session remembers who dispatched the card; the chat path names its account
SANDBOXED. Run: py -3.12 ops/tests/test_provider_env.py"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
_SANDBOX = tempfile.mkdtemp(prefix="hd-provenv-")
import daemon.paths
daemon.paths.DAEMON_ROOT = _SANDBOX
daemon.paths.DATA_ROOT = _SANDBOX
from spine.storage import db                      # noqa: E402
db.DBPATH = os.path.join(_SANDBOX, "helmdeck.db")
db.init()
from spine.storage import usersecrets as us       # noqa: E402
from spine.agent import opencode_driver as ocd, spawnenv   # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


KEY_A, KEY_B = "sk-aaaa-0123456789abcdefAAAA", "sk-bbbb-0123456789abcdefBBBB"
if us.available():
    us.put("ada", "deepseek", KEY_A)
    us.put("bob", "deepseek", KEY_B)
    us.put("ada", "anthropic", KEY_A)
    print("1. the dispatching account's keys")
    env = ocd._env({}, "ada")
    check(env.get("DEEPSEEK_API_KEY") == KEY_A and env.get("ANTHROPIC_API_KEY") == KEY_A, "ada's keys are in the env")
    check(ocd._env({"env": {"DEEPSEEK_API_KEY": "plaintext-row-value"}}, "ada")["DEEPSEEK_API_KEY"] == KEY_A,
          "the account's key wins over a plaintext env row")
    check(ocd._env({"env": {"DEEPSEEK_API_KEY": "plaintext-row-value"}}, "nobody")["DEEPSEEK_API_KEY"] == "plaintext-row-value",
          "an account without keys leaves the existing env row alone (additive)")
    print("2. no fallback")
    check(ocd._env({}, "bob")["DEEPSEEK_API_KEY"] == KEY_B and ocd._env({}, "bob").get("ANTHROPIC_API_KEY") != KEY_A,
          "bob gets bob's key and never ada's")
    base = {k for k in os.environ if k in {m["env"] for m in us.PROVIDERS.values()}}
    check({m["env"] for m in us.PROVIDERS.values()} - base - set(ocd._env({}, "").keys()) ==
          {m["env"] for m in us.PROVIDERS.values()} - base, "no account -> no provider variable added")

print("3. other engines never see a provider variable")
card_env = spawnenv._card_env({"id": "c1", "worktree": "C:/x", "dispatched_by": "ada"})
check(not ({m["env"] for m in us.PROVIDERS.values()} & set(card_env)), "spawnenv._card_env carries none")

print("4. the session knows its account")
import inspect
src = inspect.getsource(ocd._OpenCodeSession.__init__) + inspect.getsource(ocd._OpenCodeSession._spawn)
check('t.get("dispatched_by")' in src and "_env(self.cfg, self.account)" in src, "session stores dispatched_by and passes it to _env")
from cells.copilot.chat import copilot
check('"dispatched_by": user' in inspect.getsource(copilot._engine_opencode), "board chat via OpenCode names its account")

print()
if FAILS:
    print("FAILED: %d" % len(FAILS)); sys.exit(1)
print("ALL GREEN - provider keys go to OpenCode only, for the account that dispatched")
