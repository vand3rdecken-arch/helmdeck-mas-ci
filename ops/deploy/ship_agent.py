# -*- coding: utf-8 -*-
"""SHIP EXECUTION, agent-led (owner decree 2026-09-09): "Ship soll kein Skript
mehr sein, sondern eine Agent-Action - weil ship sich nicht korrigieren
kann." Implements the accepted PRD ops/docs/backlog/agent-driven-ship/README.md.

WHAT STAYS UNCHANGED (the decree is explicit about this): Henry's ship
DECISION (none|ota|native, riding into ship.sh as SHIP_KIND) happens entirely
upstream of this file and is not touched by it. `_repo_hook`'s SILENCE
watchdog (cells/engineer/cards/lanemachine.py, default 900s) stays the one
ceiling on the whole `bash ops/deploy/ship.sh` call - this script never adds
a second, competing wall-clock timeout; it stays quiet-free by streaming
every line of the real work AS IT HAPPENS, exactly like ship.sh always did.
ship.sh itself keeps owning the version bump and the native-fingerprint git
ref, both exactly-once, deterministic, code-owned - this script has no path
to either.

WHAT CHANGES: `ship.sh` used to call `push_update.sh`/`build_apk.sh` directly
and go hard-red on the first non-zero exit - a dead SSH host, a misresolved
path, a transient EPERM, a real compile error and "green but nothing actually
reached a phone" all looked identical: one exit code. This module runs the
same scripts, streamed and unchanged, but on a FAILURE it hands the tail to a
bounded, read-only diagnosis turn (the ship-runner brief,
ops/harness/agents/ship-runner.md) that classifies the failure and decides
retry-or-stop - the thing a script cannot do (PRD SS2, SS7). And it never
calls a run "green" on exit 0 alone: it reads the runtime's OWN signal after
the fact (the live relay manifest for OTA, the three version numbers for
native) before saying so - the PRD's "schaerfste Gewinn" (SS7c), the same
principle push_relay.sh's sha256 round-trip and push_site.sh's origin probe
already use.

SECURITY BOUNDARY (PRD SS5): the diagnosis turn gets a narrow --allowedTools
grant (ship_facts.py + read-only git) and an explicit --disallowedTools deny
on gradlew/surfaces/app/android/Edit/Write - it can look, it can decide
retry-or-stop, it can never act with elevated hands. The retry itself is
always the SAME pre-approved command (push_update.sh/build_apk.sh) this
script already runs directly; the model never gets to invent a different one.

Called BY ship.sh (not meant to be run standalone, though it can be for a
dry diagnosis check):
    py -3.12 ops/deploy/ship_agent.py ota
    py -3.12 ops/deploy/ship_agent.py native
Exit 0 = shipped AND verified. Exit 1 = red; the last lines explain why.
"""
import json
import os
import re
import subprocess
import sys as _sys

# npm/expo output ships unicode glyphs; a Windows console's default stdout
# codepage (cp1252) is not utf-8 and raised UnicodeEncodeError mid-stream,
# aborting THIS wrapper while the underlying script kept running orphaned -
# a worse failure than the script-only path this replaces ever had. Match
# every subprocess call below (errors="replace") instead of crashing on a
# glyph we don't need to render exactly.
for _stream in (_sys.stdout, _sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import sys
import time
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
BRIEF_PATH = os.path.join(ROOT, "ops", "harness", "agents", "ship-runner.md")

# Bounded, never infinite - same spirit as sessions._DEPLOY_FIX_CAP elsewhere
# in this repo. A cap of 2 means: run once, and if it fails, at most one
# diagnosed retry before this reports red and the escalation ladder above
# (Henry's 2-attempt give-up, then the owner) takes over.
ATTEMPT_CAP = 2

def _bash():
    """Resolve GIT-bash explicitly, never a bare 'bash' - the exact trap
    cells/engineer/cards/lanemachine.py._repo_hook already guards against
    (measured 2026-09-03: the daemon's PATH hydration appends the Windows
    dirs, so a bare 'bash' can resolve to System32's WSL bash first). This
    subprocess call is a fresh PATH lookup one layer further out than
    _repo_hook's own cmd-string rewrite, so it needs the identical guard:
    unlike git-bash's /c/... view, WSL mounts this repo under /mnt/c/... and
    chokes on the CRLF this Windows checkout's core.autocrlf produces."""
    for cand in (r"C:\Program Files\Git\bin\bash.exe",
                 r"C:\Program Files (x86)\Git\bin\bash.exe"):
        if os.path.exists(cand):
            return cand
    return "bash"


SCRIPTS = {
    "ota": [_bash(), "ops/deploy/push_update.sh"],
    "native": [_bash(), "ops/deploy/build_apk.sh"],
}


def _brief():
    try:
        with open(BRIEF_PATH, encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return "(ship-runner.md missing - diagnosing from the tail alone)"
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            raw = raw[end + 4:]
    return raw.strip()


def _claude_argv():
    """The real claude executable, never the npm .cmd shim - --allowedTools
    below is a paren-heavy quoted argument, exactly the shape that silently
    lost args through `cmd /s /c` (repo memory: cmd-shim-ate---resume). Reuse
    the daemon's own hardened resolution instead of a second copy of it."""
    sys.path.insert(0, ROOT)
    from spine.agent.agentcli import CLAUDE, _cmd_line
    return _cmd_line([CLAUDE])


def _ship_facts_tool():
    """Import ops/tools/ship_facts.py by path - same evidence module the
    decision side (ship-advisor/Henry) already reads, so the execution side
    never hand-maintains a second copy of version/resource probing."""
    sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))
    import ship_facts
    return ship_facts


def _run_streamed(cmd):
    """Run the real work, printing every line AS IT ARRIVES (flushed) so the
    caller's own stdout - which _repo_hook's silence watchdog is timing -
    never goes quiet during a real 15-20min native build. Identical
    discipline to ship.sh's own streaming; just one layer further out."""
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", bufsize=1)
    lines = []
    try:
        for line in proc.stdout:
            print(line, end="", flush=True)
            lines.append(line)
        proc.wait()
    except BaseException:
        # never leave the real work (a 15-20min gradle build, an expo
        # export) orphaned in the background because THIS wrapper died -
        # that would be a worse failure mode than the script-only path ever
        # had, where the shell itself was the only process in the chain.
        proc.kill()
        proc.wait()
        raise
    return proc.returncode, "".join(lines)


def _diagnose(mode, tail, attempt):
    """One bounded, read-only turn: classify the failure, decide retry|stop.
    Never touches gradlew/surfaces/app/android/Edit/Write (structurally, via
    --disallowedTools) - it can only look and decide, the retry it grants is
    always the SAME pre-approved command this module already runs directly.
    A failure of the diagnosis call itself is not a reason to guess: default
    to stop, exactly like an unanswered ship-decision escalation does."""
    try:
        argv = _claude_argv() + [
            "-p", "--output-format", "text",
            "--permission-mode", "default",
            "--allowedTools", "Bash(py -3.12 ops/tools/ship_facts.py*)",
                              "Bash(git log*)", "Bash(git diff*)", "Bash(git show*)",
            "--disallowedTools", "Bash(*gradlew*)", "Bash(*surfaces/app/android*)",
                                 "Edit", "Write", "NotebookEdit",
        ]
    except Exception as e:
        return {"classification": "unknown", "action": "stop",
                "reason": "could not resolve the claude CLI to diagnose with (%s) - stopping, not guessing" % e}
    prompt = (
        "%s\n\n---\nMODE: %s ship, attempt %d/%d just FAILED.\n"
        "TAIL (last output of the failed run):\n```\n%s\n```\n"
        "Run `py -3.12 ops/tools/ship_facts.py` yourself for fresh evidence "
        "before deciding - do not trust the tail alone.\n"
        "Answer in EXACTLY this shape, nothing else:\n"
        "CLASSIFICATION: transient | resource-missing | collision | code-error | contradiction | unknown\n"
        "ACTION: retry | stop\n"
        "REASON: <one or two sentences, citing the actual tail or ship_facts.py output>\n"
    ) % (_brief(), mode, attempt, ATTEMPT_CAP, tail[-4000:])
    try:
        r = subprocess.run(argv, cwd=ROOT, input=prompt, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=180)
        out = r.stdout or ""
    except Exception as e:
        return {"classification": "unknown", "action": "stop",
                "reason": "diagnosis call itself failed (%s) - stopping, not guessing" % e}
    cls = re.search(r"CLASSIFICATION:\s*(\S+)", out)
    act = re.search(r"ACTION:\s*(\S+)", out)
    why = re.search(r"REASON:\s*(.+)", out)
    action = act.group(1).lower() if act else "stop"
    if action not in ("retry", "stop"):
        action = "stop"
    return {"classification": cls.group(1) if cls else "unknown",
            "action": action,
            "reason": (why.group(1).strip() if why else out.strip())[:600] or "(no reason given)"}


def _verify_ota():
    """Read the runtime's OWN signal, not the exit code: fetch the LIVE
    manifest and confirm it references the exact bundle we just exported
    (its content-hashed filename), the same round-trip discipline
    push_relay.sh's sha256 compare already uses for the APK channel."""
    meta_path = os.path.join(ROOT, "surfaces", "app", "dist-ota", "metadata.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            bundle = json.load(f)["fileMetadata"]["android"]["bundle"]
    except Exception as e:
        return False, "could not read the just-exported metadata.json to know what to verify against (%s)" % e
    sf = _ship_facts_tool()
    dom, err = sf._relay_domain()
    if not dom:
        return False, "no relay domain resolvable to verify against (%s)" % err
    rtv = (sf._read_app_json() or {}).get("version") or "1.0.0"
    url = "https://%s/updates/manifest" % dom
    req = urllib.request.Request(url, headers={
        "expo-platform": "android", "expo-runtime-version": rtv,
        "expo-protocol-version": "1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:
        return False, "relay manifest fetch failed post-publish: %s" % e
    bundle_name = os.path.basename(bundle)
    if bundle_name not in body:
        return False, ("published bundle %s but the live manifest at %s does "
                       "not reference it - stale cache, wrong channel, or a "
                       "publish that did not actually land" % (bundle_name, url))
    return True, "live manifest at %s references the just-published bundle %s" % (url, bundle_name)


def _verify_native():
    """The PRD's own sharpest finding (SS7c): a native ship must not be called
    green on exit 0 alone. Cross-check the three numbers that are supposed to
    agree - app.json, the built APK (via aapt2), and what the relay actually
    serves - and report a disagreement as the headline, not an average."""
    sf = _ship_facts_tool()
    v = sf.live_versions()
    aj, apk, rl = v["app_json"], (v["apk"] or {}), (v["relay"] or {})
    if apk.get("state") != "present":
        return False, "no APK found on disk after a native build reported success"
    apk_vc = apk.get("versionCode")
    if apk_vc is not None and apk_vc != aj.get("versionCode"):
        return False, ("app.json versionCode %s != built APK versionCode %s - "
                       "the artifact does not match the source it claims to "
                       "be built from" % (aj.get("versionCode"), apk_vc))
    if rl.get("state") != "reachable":
        return False, ("relay /apk/version.json is not reachable post-ship (%s) "
                       "- cannot confirm the APK actually reached distribution"
                       % rl.get("why"))
    rl_vc = rl.get("versionCode")
    if rl_vc is not None and rl_vc != aj.get("versionCode"):
        return False, ("relay serves versionCode %s but app.json/the APK say "
                       "%s - push_relay.sh ran but the relay's channel is "
                       "still stale" % (rl_vc, aj.get("versionCode")))
    return True, "app.json / APK / relay all agree on versionCode %s" % aj.get("versionCode")


def ship(mode):
    cmd = SCRIPTS[mode]
    attempt, tail = 0, ""
    while True:
        attempt += 1
        print("[ship-agent] %s attempt %d/%d: %s" % (mode, attempt, ATTEMPT_CAP, " ".join(cmd)), flush=True)
        rc, tail = _run_streamed(cmd)
        if rc == 0:
            break
        if attempt >= ATTEMPT_CAP:
            print("SHIP-AGENT: FAILED")
            print("WHY: %s exited %d on attempt %d/%d - retry cap reached" % (mode, rc, attempt, ATTEMPT_CAP))
            print("TAIL:\n%s" % tail[-1500:])
            return 1
        d = _diagnose(mode, tail, attempt)
        print("[ship-agent] diagnosis: %s -> %s (%s)" % (d["classification"], d["action"], d["reason"]), flush=True)
        if d["action"] != "retry":
            print("SHIP-AGENT: FAILED")
            print("WHY: %s (classification: %s)" % (d["reason"], d["classification"]))
            print("TAIL:\n%s" % tail[-1500:])
            return 1
        print("HOOK-NOTE: ship-agent retrying %s after a diagnosed %s failure" % (mode, d["classification"]), flush=True)
        time.sleep(5)

    try:
        ok, why = (_verify_ota() if mode == "ota" else _verify_native())
    except Exception as e:
        ok, why = False, "post-ship verification crashed (%s) - treating as unverified, not green" % e
    if not ok:
        print("SHIP-AGENT: FAILED")
        print("WHY: %s exited 0 but post-ship verification disagrees: %s" % (mode, why))
        return 1
    print("SHIP-AGENT: OK")
    print("WHY: %s" % why)
    return 0


if __name__ == "__main__":
    _mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if _mode not in SCRIPTS:
        print("usage: ship_agent.py ota|native", file=sys.stderr)
        sys.exit(2)
    sys.exit(ship(_mode))
