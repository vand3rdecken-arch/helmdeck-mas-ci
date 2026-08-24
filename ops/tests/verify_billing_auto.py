# -*- coding: utf-8 -*-
"""Proves the auto billing mode: the system CHOOSES flat vs metered itself.

The claim under test is events.plan_effective(): with settings.pm.plan="auto"
(the new default) the billing mode comes from the CLI's real auth - the same
signal Paseo's usage tab keys off (the Claude Code login in
~/.claude/.credentials.json) - not from an owner-maintained switch. Explicit
plan values stay overrides. usage.login_method itself is proven against fake
creds files + env, so nothing here touches the real login, network or daemon.
"""
import json
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "daemon"))
import events                                                    # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else " -> got %r, want %r" % (got, want)))
    if not ok:
        FAILED.append(name)


def fake_login(method, subscription=None):
    m = types.ModuleType("usage")
    m.login_method = lambda: {"method": method, "subscription": subscription,
                              "plan": subscription and subscription.capitalize()}
    sys.modules["usage"] = m


def settings(plan="auto"):
    return {"pm": {"plan": plan}}


print("plan_effective - the explicit setting stays the override")
fake_login("oauth", "max")
check("plan=max wins over any detection", events.plan_effective(settings("max")), ("max", "setting"))
fake_login("oauth", "max")
check("plan=api wins over a Max login", events.plan_effective(settings("api")), ("api", "setting"))
check("plan=mixed passes through", events.plan_effective(settings("mixed")), ("mixed", "setting"))

print("plan_effective - auto detects from the real auth")
fake_login("oauth", "max")
check("Max login -> flat quota", events.plan_effective(settings()), ("max", "oauth:max"))
check("...and ai_billing renders it flat", events.ai_billing(settings()), "flat")
fake_login("oauth", "pro")
check("Pro login -> flat quota", events.plan_effective(settings()), ("max", "oauth:pro"))
fake_login("oauth", None)
check("Console login (no subscriptionType) -> metered",
      events.plan_effective(settings()), ("api", "oauth:console"))
fake_login("api_key")
check("ANTHROPIC_API_KEY -> metered", events.plan_effective(settings()), ("api", "api_key"))
check("...and ai_billing renders it metered", events.ai_billing(settings()), "metered")
fake_login(None)
check("no auth at all -> old flat default, never invented $",
      events.plan_effective(settings()), ("max", "default"))
sys.modules["usage"] = types.ModuleType("usage")          # no login_method at all
check("usage module broken -> flat default, no crash",
      events.plan_effective(settings()), ("max", "default"))
check("missing plan key behaves like auto",
      events.plan_effective({"pm": {}}), ("max", "default"))

print("usage.login_method - reads the same file Paseo's usage tab does")
sys.modules.pop("usage", None)
import usage as real_usage                                        # noqa: E402
tmp = tempfile.mkdtemp()
os.environ["CLAUDE_HOME"] = tmp                                   # sandbox: never the real login
os.environ.pop("ANTHROPIC_API_KEY", None)


def write_creds(oauth):
    with open(os.path.join(tmp, ".credentials.json"), "w", encoding="utf-8") as f:
        json.dump({"claudeAiOauth": oauth}, f)


check("no creds + no key -> method None", real_usage.login_method()["method"], None)
os.environ["ANTHROPIC_API_KEY"] = "sk-test"
check("env key alone -> api_key", real_usage.login_method()["method"], "api_key")
write_creds({"accessToken": "tok", "subscriptionType": "max", "rateLimitTier": "max_20x"})
lm = real_usage.login_method()
check("stored login WINS over the env key (Claude Code precedence)", lm["method"], "oauth")
check("subscriptionType carried", lm["subscription"], "max")
check("human plan label built", lm["plan"], "Max 20x")
write_creds({"accessToken": "tok"})                               # Console-style login
check("login without subscriptionType -> no subscription",
      real_usage.login_method()["subscription"], None)
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("CLAUDE_HOME", None)

print("pm.economics - the planner thinks in the RESOLVED plan")
fake_login_mod = types.ModuleType("usage")
fake_login_mod.login_method = lambda: {"method": "oauth", "subscription": "max", "plan": "Max 20x"}
fake_login_mod.cached = lambda refresh=True: None
sys.modules["usage"] = fake_login_mod
import pm                                                         # noqa: E402
check("PM default is auto", pm.PM_DEFAULTS["plan"], "auto")
fake_sessions = types.ModuleType("sessions")
fake_sessions.list_tracks = lambda: []
sys.modules["sessions"] = fake_sessions
fake_procs = types.ModuleType("processes")
fake_procs.list_processes = lambda: []
sys.modules["processes"] = fake_procs
_orig_settings, _orig_read = events.settings, events.read_events
events.settings = lambda: {"pm": {"plan": "auto"}, "capacity": {"tariff": {}, "wip_limit": 3, "touch_budget_day": 40},
                           "prices": {"default": {"in": 3.0, "out": 15.0}}, "currency": "EUR"}
events.read_events = lambda: []
try:
    econ = pm.economics()
    check("economics.plan is resolved, not 'auto'", econ["plan"], "max")
    check("economics names the evidence", econ["plan_source"], "oauth:max")
    check("raw setting still visible", econ["plan_setting"], "auto")
finally:
    events.settings, events.read_events = _orig_settings, _orig_read
    sys.modules.pop("usage", None)
    sys.modules.pop("sessions", None)

print("")
if FAILED:
    print("FAILED: " + ", ".join(FAILED))
    sys.exit(1)
print("ALL AUTO-BILLING CHECKS PASSED")
