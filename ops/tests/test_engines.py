# -*- coding: utf-8 -*-
"""spine/agent/engines.py - the engine registry + availability snapshot
(Paseo provider-snapshot shape). What this proves, against the code path
the daemon and the New-Request picker really use:
  - every builtin engine is KNOWN without a settings.drivers entry (the bug:
    settings.drivers named only claude/claude-desktop, so omp/codex/... were
    'unknown driver' and never appeared in the picker)
  - config() prefers settings.drivers and falls back to the builtin type
  - status is DERIVED from the binary answering --version, not a stored flag:
    a fake CLI that answers -> ready+version; a missing one -> unavailable
    with the reason; one that exits non-zero -> unavailable
  - check_selectable: unknown refused, known-but-missing non-claude refused,
    claude never refused for availability (its spawn path reports itself)
  - update_track accepts a builtin engine with no settings entry (the old
    code raised 'unknown driver')
Self-sandboxing: temp sqlite DB + settings.json, PATH replaced by a temp dir
holding fake CLIs - no daemon, no board state, no real engine spawned."""
import os, sys, stat, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp()
BIN = os.path.join(SANDBOX, "bin")
os.makedirs(BIN)

from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.agent import engines
from cells.engineer.cards import sessions

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _fake_cli(name, version="9.9.9", rc=0):
    """A CLI on the sandbox PATH that answers --version (Windows: .cmd, else sh)."""
    if os.name == "nt":
        p = os.path.join(BIN, name + ".cmd")
        with open(p, "w") as f:
            f.write("@echo off\r\necho %s %s\r\nexit /b %d\r\n" % (name, version, rc))
    else:
        p = os.path.join(BIN, name)
        with open(p, "w") as f:
            f.write("#!/bin/sh\necho %s %s\nexit %d\n" % (name, version, rc))
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
    return p


os.environ["PATH"] = BIN
engines._FALLBACK_PATHS.clear()      # no off-PATH rescue in the sandbox
engines.invalidate()


def test_builtins_known_without_settings():
    k = engines.known()
    for n in ("claude", "claude-desktop", "omp", "codex", "opencode", "pi"):
        check(n in k, "builtin '%s' is a known driver with no settings entry" % n)
    check(engines.config("omp") == {"type": "omp"}, "config('omp') falls back to the builtin type")
    check(engines.config("nope") is None, "config() of an unknown name is None")


def test_settings_entry_wins():
    events.save_settings({"drivers": {"omp": {"type": "omp", "exe": r"C:\x\omp.exe"},
                                      "mybot": {"type": "cmd", "cmd": "echo"}}})
    engines.invalidate()
    check(engines.config("omp").get("exe") == r"C:\x\omp.exe", "settings.drivers wins over the builtin default")
    check("mybot" in engines.known(), "a settings-only driver is known too")
    ids = [e["id"] for e in engines.snapshot()]
    check(ids[:6] == ["claude", "claude-desktop", "omp", "codex", "opencode", "pi"] and "mybot" in ids,
          "snapshot lists builtins in order, then settings-only drivers (%s)" % ids)
    # save_settings merges one level deep, so `{"drivers": {}}` would keep the
    # rows - restore the code defaults row explicitly.
    db.workspace_config_put({"drivers": events.DEFAULTS["drivers"]})
    engines.invalidate()
    check(engines.config("omp") == {"type": "omp"}, "drivers row restored to defaults")


def test_status_is_derived_from_the_binary():
    engines.invalidate()
    e = engines.entry("codex")
    check(e["status"] == "unavailable" and "not installed" in e["error"],
          "missing CLI -> unavailable with reason (%r)" % e["error"])
    _fake_cli("codex", "0.42.0")
    engines.invalidate()
    e = engines.entry("codex")
    check(e["status"] == "ready" and "0.42.0" in e["version"],
          "CLI answering --version -> ready + version (%r)" % e["version"])
    check(e["verified"] is False, "codex driver is flagged unverified (never ran a real turn)")
    _fake_cli("pi", rc=3)
    engines.invalidate()
    e = engines.entry("pi")
    check(e["status"] == "unavailable" and "exited 3" in e["error"],
          "CLI exiting non-zero -> unavailable (%r)" % e["error"])


def test_cache_hit_vs_miss():
    engines.invalidate()
    engines.entry("opencode")            # miss, cached for PROBE_MISS_TTL
    _fake_cli("opencode")
    e = engines.entry("opencode")
    check(e["status"] == "unavailable", "a miss stays cached until its TTL (install mid-session)")
    e = engines.entry("opencode", refresh=True)
    check(e["status"] == "ready", "refresh=True re-probes and sees the new install")


def test_check_selectable():
    engines.invalidate()
    check("unknown driver" in (engines.check_selectable("nope") or ""), "unknown name refused")
    os.remove(os.path.join(BIN, "codex.cmd" if os.name == "nt" else "codex"))
    engines.invalidate()
    check("not available" in (engines.check_selectable("codex") or ""),
          "known engine with no CLI refused at filing")
    check(engines.check_selectable("claude") is None,
          "claude is never refused for availability (its own spawn reports)")
    _fake_cli("omp")
    engines.invalidate()
    check(engines.check_selectable("omp") is None, "installed engine accepted")


def test_enabled_toggle_and_config_roundtrip():
    """Paseo's provider switch: enabled=False hides + refuses; the snapshot
    exposes the editable row so the settings editor can send it back whole."""
    events.save_settings({"drivers": {"omp": {"type": "omp", "enabled": False,
                                              "env": {"FOO": "1"}}}})
    engines.invalidate()
    e = engines.entry("omp")
    check(e["enabled"] is False, "enabled=False in the settings row -> entry.enabled False")
    check(e["config"] == {"enabled": False, "env": {"FOO": "1"}}, "editable row exposed (%r)" % e["config"])
    check("switched off" in (engines.check_selectable("omp") or ""), "a switched-off engine is refused at filing")
    db.workspace_config_put({"drivers": events.DEFAULTS["drivers"]})
    engines.invalidate()
    check(engines.entry("omp")["enabled"] is True, "no row -> enabled by default")


def test_update_track_accepts_builtin_engine():
    run_dir = os.path.join(SANDBOX, "t-omp")
    os.makedirs(run_dir, exist_ok=True)
    db.track_put({"id": "t-omp", "status": "needs_you", "lane": "working", "task": "t",
                  "branch": "t-omp", "run_dir": run_dir, "driver": "claude",
                  "turns": 1, "updated": "2026-09-13 00:00:00"})
    t = sessions.update_track("t-omp", {"driver": "omp"})
    check(t["driver"] == "omp", "update_track switches to a builtin engine with no settings entry")
    try:
        sessions.update_track("t-omp", {"driver": "codex"})
        check(False, "switch to a not-installed engine should raise")
    except ValueError as e:
        check("not available" in str(e), "switch to a not-installed engine refused (%r)" % str(e))


if __name__ == "__main__":
    for fn in [test_builtins_known_without_settings, test_settings_entry_wins,
               test_status_is_derived_from_the_binary, test_cache_hit_vs_miss,
               test_check_selectable, test_enabled_toggle_and_config_roundtrip,
               test_update_track_accepts_builtin_engine]:
        print(fn.__name__)
        fn()
    print("\n%s" % ("ALL PASS" if not _fails else "FAILED: %d" % len(_fails)))
    sys.exit(1 if _fails else 0)
