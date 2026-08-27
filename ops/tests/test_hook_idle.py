# -*- coding: utf-8 -*-
"""_repo_hook bounds SILENCE, not wall-clock - same law as the turn watchdog
(ops/tests/test_idle_watchdog.py). Pins the regression that left main merged with
nothing shipped: the deploy hook had a fixed 1800s cap, and the NATIVE ship
path (npm ci -> gradle -> emulator smoke -> scp the APK -> two expo exports ->
two uploads) legitimately runs past 30 minutes, so the ceiling fired on a
HEALTHY build. A hook that is still printing is working; only total silence
means wedged.

Also pins the live-narration merge (2026-08-15, superseding the abandoned
ops/tests/test_repo_hook_streaming.py mechanism): any output line prefixed
`HOOK-NOTE:` is logged to the actionlog THE MOMENT it's read, not just
folded into the final tail - so ship.sh/build_apk.sh can narrate their own
long phases instead of the owner watching dead silence for 15-20 min."""
import json, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))

DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp(prefix="hd-hookidle-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from cells.engineer import sessions

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _settings(cmd, **extra):
    s = {"repo_hooks": {SANDBOX: {"deploy": cmd}}}
    s.update(extra)
    with open(events.SET, "w", encoding="utf-8") as f:
        json.dump(s, f)


def _track(name):
    run_dir = os.path.join(SANDBOX, "run-" + name)
    os.makedirs(run_dir, exist_ok=True)
    return {"id": name, "repo": SANDBOX, "run_dir": run_dir}


def _py(body):
    """A hook command that runs `body` in this interpreter."""
    script = os.path.join(SANDBOX, "hook_%d.py" % abs(hash(body)))
    with open(script, "w", encoding="utf-8") as f:
        f.write(body)
    return '"%s" "%s"' % (sys.executable, script)


def _notes(run_dir):
    path = os.path.join(run_dir, "actions.jsonl")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("kind") == "note":
                out.append(d.get("detail") or "")
    return out


# 1) PRODUCTIVE hook: prints every 0.4s for ~3.2s with idle=2s. Every line
#    resets the watchdog, so a wall-clock-style cap would kill it and a
#    silence-bounded one must let it finish.
_settings(_py(
    "import sys, time\n"
    "for i in range(8):\n"
    "    print('step %d' % i, flush=True)\n"
    "    time.sleep(0.4)\n"
    "print('BUILD OK', flush=True)\n"
), hook_idle_s=2)
t = _track("productive")
t0 = time.time()
ok = sessions._repo_hook(t, "deploy")
dur = time.time() - t0
tail = (t.get("deploy_hook") or {}).get("tail", "")
check(ok is True, "productive hook survived past the idle window (ok=%r)" % ok)
check(dur > 3.0, "it really ran the full ~3.2s, not cut short (%.1fs)" % dur)
check("BUILD OK" in tail, "the hook ran to completion (tail has the final line)")
check("killed" not in tail, "not reported as killed")

# 2) WEDGED hook: one line, then total silence. idle=2s -> killed.
_settings(_py(
    "import time\n"
    "print('starting', flush=True)\n"
    "time.sleep(120)\n"
), hook_idle_s=2)
t2 = _track("wedged")
t0 = time.time()
ok2 = sessions._repo_hook(t2, "deploy")
dur2 = time.time() - t0
tail2 = (t2.get("deploy_hook") or {}).get("tail", "")
check(ok2 is False, "wedged hook reported as failed")
check("no output for" in tail2, "killed for SILENCE, with the reason on the card (%r)" % tail2[-60:])
check(2.0 <= dur2 < 20.0, "killed near the idle window, not a 30-min wait (%.1fs)" % dur2)

# 3) The optional absolute ceiling still exists for a hook that dribbles
#    forever - off by default, honoured when set.
_settings(_py(
    "import time\n"
    "while True:\n"
    "    print('tick', flush=True)\n"
    "    time.sleep(0.2)\n"
), hook_idle_s=60, hook_max_s=2)
t3 = _track("dribble")
t0 = time.time()
ok3 = sessions._repo_hook(t3, "deploy")
dur3 = time.time() - t0
tail3 = (t3.get("deploy_hook") or {}).get("tail", "")
check(ok3 is False, "dribbling hook stopped by the optional hard cap")
check("hard cap" in tail3, "hard-cap reason recorded (%r)" % tail3[-60:])
check(dur3 < 20.0, "hard cap fired promptly (%.1fs)" % dur3)

# 4) No hook configured for this repo -> None (unchanged contract).
_settings("")
check(sessions._repo_hook(_track("nohook"), "deploy") is None, "no hook configured -> None")

# 5) HOOK-NOTE: lines are logged to the actionlog LIVE (as their own "note"
#    entries the moment they're read), not just folded into the final tail -
#    this is what lets ship.sh/build_apk.sh narrate long phases instead of
#    the owner watching dead silence.
_settings(_py(
    "import time\n"
    "print('HOOK-NOTE: native change -> APK build laeuft (~10-15 Min)', flush=True)\n"
    "time.sleep(0.05)\n"
    "print('some other build chatter line', flush=True)\n"
    "print('HOOK-NOTE: done, uploading', flush=True)\n"
), hook_idle_s=30)
t5 = _track("hooknote")
ok5 = sessions._repo_hook(t5, "deploy")
notes = _notes(t5["run_dir"])
# the live-streamed notes are everything except the opening "DEPLOY HOOK:"
# announcement and the closing "DEPLOY HOOK OK/FAILED:" summary (which
# legitimately repeats the whole tail, chatter line included).
live = [n for n in notes if not n.startswith(("DEPLOY HOOK:", "DEPLOY HOOK OK:", "DEPLOY HOOK FAILED:"))]
check(ok5 is True, "the HOOK-NOTE hook still completes normally")
check(live == ["native change -> APK build laeuft (~10-15 Min)", "done, uploading"],
      "HOOK-NOTE lines are logged live as their own notes, in order, prefix stripped (%r)" % live)
check("some other build chatter line" not in live,
      "non-prefixed chatter does NOT get its own live note (only the final tail summary)")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("hook-idle: all pinned - PASS")
