# -*- coding: utf-8 -*-
"""One language, sharply - the behaviour, not just the lint.

tools/i18n_lint.py proves no untranslated literal is LEFT; this proves the
switch actually WORKS: flipping settings.policy.lang changes what the daemon
says to the owner, in chat and in push, and never leaves a blank or a raw key.

The audit trail is deliberately NOT under test here because it is deliberately
not translated (daemon/i18n.py explains why): the event log, gate output and git
messages stay English in every workspace.

Self-sandboxing: settings are faked in-process, no daemon, no network."""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(HERE)
sys.path.insert(0, DAEMON)

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


# fake settings so no settings.json (a secret) is needed
LANG = {"v": "de"}
fake_events = types.ModuleType("spine.storage.events")
fake_events.settings = lambda: {"policy": {"lang": LANG["v"]}}
sys.modules["spine.storage.events"] = fake_events

from spine.registry import i18n

print("i18n behaviour")

# -- 1. both languages complete -------------------------------------------
missing = [k for k, e in i18n.MESSAGES.items()
           if not (e.get("de") or "").strip() or not (e.get("en") or "").strip()]
check(not missing, "every daemon message has BOTH languages (%d keys)%s"
      % (len(i18n.MESSAGES), "" if not missing else " missing: %s" % missing[:5]))

# -- 2. the switch actually switches --------------------------------------
LANG["v"] = "de"
de = i18n.t("say.landed.merged")
LANG["v"] = "en"
en = i18n.t("say.landed.merged")
check(de != en, "flipping policy.lang changes the message (%r -> %r)" % (de, en))
check("gemergt" in de and "merged into main" in en, "each side is really in its own language")

# -- 3. no message ever comes out blank or as a raw key -------------------
for lang in ("de", "en"):
    LANG["v"] = lang
    blanks = [k for k in i18n.MESSAGES if not i18n.t(k).strip()]
    raw = [k for k in i18n.MESSAGES if i18n.t(k) == k]
    check(not blanks, "[%s] no message renders blank" % lang)
    check(not raw, "[%s] no message renders as its own key" % lang)

# -- 4. interpolation survives both languages -----------------------------
for lang in ("de", "en"):
    LANG["v"] = lang
    s = i18n.t("say.cannotLand", kind="conflict", detail="branch X")
    check("conflict" in s and "branch X" in s, "[%s] placeholders are filled" % lang)
    s2 = i18n.t("pm.planned", n=3)
    check("3" in s2, "[%s] numeric placeholder is filled" % lang)

# -- 5. it never explodes on bad input ------------------------------------
check(i18n.t("does.not.exist") == "does.not.exist",
      "an unknown key returns itself - visible and greppable, never blank")
check(isinstance(i18n.t("say.cannotLand"), str),
      "a missing placeholder does not raise (a message must not break the work)")

LANG["v"] = "klingon"
check(i18n.t("push.done") == i18n.MESSAGES["push.done"]["de"],
      "an unknown language falls back to German rather than failing")

# -- 6. the policy default exists -----------------------------------------
del sys.modules["spine.storage.events"]
import importlib
real_events = importlib.import_module("spine.storage.events")
check((real_events.DEFAULTS.get("policy") or {}).get("lang") in i18n.LANGS,
      "policy.lang ships as a real default (%r)"
      % (real_events.DEFAULTS.get("policy") or {}).get("lang"))

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("all i18n behaviour checks passed")
