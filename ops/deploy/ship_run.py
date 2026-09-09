# -*- coding: utf-8 -*-
"""ops/deploy/ship_run.py - THE ship EXECUTION path (owner decree 2026-09-09,
precision 17:17): "mehr als ein Prozess" - a visible, multi-stage flow, each
stage with its own clear result, never a monolithic agent turn and never a
thin wrapper around ship.sh. `ops/deploy/ship.sh` is demoted to a TOOL these
stages call for the few things that must stay deterministic and code-owned
(version bump, native-fingerprint ref) - it is no longer what the deploy
hook invokes. This is: settings.repo_hooks[<repo>]["deploy"] now points here
(was "bash ops/deploy/ship.sh"; see the migration note in main()'s docstring).

WHAT STAYS UNCHANGED: Henry's ship DECISION (SHIP_KIND=none|ota|native,
cells/copilot/broker/henry_broker.py) happens entirely upstream and is only
READ here, never overridden. `_repo_hook`'s SILENCE watchdog (cells/engineer/
cards/lanemachine.py, default 900s) stays the one ceiling on this whole
process - every stage streams its real work as it happens, exactly as
ship.sh always did, so a healthy 15-20min native build never goes quiet.

THREE STAGES, each with its own header and its own RESULT line (narrated
live via HOOK-NOTE, the same mechanism ship.sh/build_apk.sh already use -
`_repo_hook`'s `_note()` callback logs any HOOK-NOTE-prefixed line to the
actionlog THE MOMENT it's read):

  STAGE 1/3 DIAGNOSE  Read SHIP_KIND, run ops/tools/ship_facts.py fresh, and
                       PREFLIGHT-GATE the resources the chosen kind needs -
                       missing JDK17/keystore/relay stops HERE, before a
                       single minute of build time is spent (PRD verify #4).
  STAGE 2/3 EXECUTE   Runs push_update.sh/build_apk.sh, streamed. A failure
                       is diagnosed (ops/harness/agents/ship-runner.md,
                       narrow read-only tool grant) and retried at most
                       once. The version bump / native-fp ref run through
                       ship.sh's own subcommands (bump / finalize-native /
                       revert-bump) - hard invariants, never agent judgement.
  STAGE 3/3 VERIFY    Re-checks the runtime's OWN signal - the live relay
                       manifest for OTA, the three version numbers (app.json
                       / APK / relay) for native - before calling anything
                       green. A script exiting 0 is not proof; this is (the
                       PRD's "schaerfste Gewinn").

Usage (called BY the deploy hook; runnable by hand for a dry check):
    SHIP_KIND=none|ota|native py -3.12 ops/deploy/ship_run.py
    SHIP_DRY_RUN=1 SHIP_KIND=ota py -3.12 ops/deploy/ship_run.py
Exit 0 = nothing to ship, OR shipped and verified. Exit 1 = red.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

# npm/expo output ships unicode glyphs; a Windows console's default stdout
# codepage (cp1252) is not utf-8 and would raise UnicodeEncodeError mid-
# stream, aborting this orchestrator while the underlying script kept
# running orphaned - a worse failure than the script-only path ever had.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
BRIEF_PATH = os.path.join(ROOT, "ops", "harness", "agents", "ship-runner.md")
SHIP_SH = os.path.join(ROOT, "ops", "deploy", "ship.sh")
LOCK_DIR = os.path.join(ROOT, ".loop", "ship.lock")

# Bounded, never infinite - same spirit as sessions._DEPLOY_FIX_CAP
# elsewhere in this repo. A cap of 2 means: run once, and if it fails, at
# most one diagnosed retry before EXECUTE reports red.
ATTEMPT_CAP = 2


def _bash():
    """Resolve GIT-bash explicitly, never a bare 'bash' - the exact trap
    cells/engineer/cards/lanemachine.py._repo_hook already guards against
    for its OWN subprocess (measured 2026-09-03: the daemon's PATH hydration
    appends the Windows dirs, so a bare 'bash' can resolve to System32's WSL
    bash first). This is a fresh PATH lookup one layer further out, so it
    needs the identical guard: unlike git-bash's /c/... view, WSL mounts
    this repo under /mnt/c/... and chokes on the CRLF this Windows
    checkout's core.autocrlf produces (measured live 2026-09-09)."""
    for cand in (r"C:\Program Files\Git\bin\bash.exe",
                 r"C:\Program Files (x86)\Git\bin\bash.exe"):
        if os.path.exists(cand):
            return cand
    return "bash"


BASH = _bash()
SCRIPTS = {"ota": [BASH, "ops/deploy/push_update.sh"],
           "native": [BASH, "ops/deploy/build_apk.sh"]}


# --------------------------------------------------------------------- lock
# The SAME singleton ship.sh always used (.loop/ship.lock, mkdir-atomic,
# LIVE-PID staleness, never a stored flag) - held for this whole process's
# EXECUTE stage. cells/copilot/broker/henry_broker.py's board snapshot
# (_ship_lock_pid) and boot-time stale-lock check (check_stale_ship_lock)
# both read this exact directory and pid-file shape, so this must match
# byte for byte, not just behave similarly.
def _lock_holder():
    try:
        lines = [l.strip() for l in
                open(os.path.join(LOCK_DIR, "pid"), encoding="utf-8").read().splitlines() if l.strip()]
    except OSError:
        return None
    return lines[1] if len(lines) > 1 else (lines[0] if lines else None)


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _acquire_lock():
    os.makedirs(os.path.join(ROOT, ".loop"), exist_ok=True)
    while True:
        try:
            os.mkdir(LOCK_DIR)
            break
        except FileExistsError:
            holder = _lock_holder()
            if holder and _pid_alive(holder):
                print("[ship-run] another ship is running (pid %s) - waiting to join" % holder, flush=True)
                time.sleep(15)
            else:
                print("[ship-run] stale ship lock (pid %s dead) - taking over" % (holder or "?"), flush=True)
                shutil.rmtree(LOCK_DIR, ignore_errors=True)
    # A real python.exe on Windows: os.getpid() IS the true Windows PID
    # already - no MSYS/WSL translation needed (ship.sh's bash equivalent
    # needed two lines and a /proc/$$/winpid read for exactly this reason).
    pid = str(os.getpid())
    with open(os.path.join(LOCK_DIR, "pid"), "w", encoding="utf-8") as f:
        f.write(pid + "\n" + pid + "\n")


def _release_lock():
    shutil.rmtree(LOCK_DIR, ignore_errors=True)


# ------------------------------------------------------------------- tools
def _ship_tool(*args):
    """Call ops/deploy/ship.sh's subcommand form - the hard-invariant tool
    (bump / finalize-native / revert-bump / kt-start). Never takes the lock
    itself; this orchestrator already holds it for the whole EXECUTE stage."""
    r = subprocess.run([BASH, SHIP_SH] + list(args), cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def _ship_facts_tool():
    """Import ops/tools/ship_facts.py by path - the SAME evidence module the
    decision side (ship-advisor/Henry) already reads, so execution never
    hand-maintains a second copy of version/resource probing."""
    sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))
    import ship_facts
    return ship_facts


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
    lost args through `cmd /s /c` (repo memory: cmd-shim-ate---resume)."""
    sys.path.insert(0, ROOT)
    from spine.agent.agentcli import CLAUDE, _cmd_line
    return _cmd_line([CLAUDE])


def _run_streamed(cmd):
    """Run the real work, printing every line AS IT ARRIVES (flushed) so the
    caller's own stdout - which _repo_hook's silence watchdog is timing -
    never goes quiet during a real 15-20min native build."""
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
        # never leave the real work orphaned in the background because THIS
        # process died - a worse failure mode than the script-only path,
        # where the shell itself was the only process in the chain.
        proc.kill()
        proc.wait()
        raise
    return proc.returncode, "".join(lines)


def _diagnose(mode, tail, attempt):
    """One bounded, read-only turn: classify the failure, decide retry|stop.
    Never touches gradlew/surfaces/app/android/Edit/Write (structurally, via
    --disallowedTools) - it can only look and decide; the retry it grants is
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
        "%s\n\n---\nMODE: %s ship, attempt %d/%d just FAILED (this is the EXECUTE "
        "stage of a staged ship - DIAGNOSE already ran and gated resources; VERIFY "
        "runs after a success).\nTAIL (last output of the failed run):\n```\n%s\n```\n"
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


def _run_with_retry(mode):
    cmd = SCRIPTS[mode]
    attempt, tail = 0, ""
    while True:
        attempt += 1
        print("[ship-run] %s attempt %d/%d: %s" % (mode, attempt, ATTEMPT_CAP, " ".join(cmd)), flush=True)
        rc, tail = _run_streamed(cmd)
        if rc == 0:
            return True, "exit 0", tail
        if attempt >= ATTEMPT_CAP:
            return False, ("%s exited %d on attempt %d/%d - retry cap reached"
                           % (mode, rc, attempt, ATTEMPT_CAP)), tail
        d = _diagnose(mode, tail, attempt)
        print("[ship-run] diagnosis: %s -> %s (%s)" % (d["classification"], d["action"], d["reason"]), flush=True)
        if d["action"] != "retry":
            return False, "%s (classification: %s)" % (d["reason"], d["classification"]), tail
        print("HOOK-NOTE: ship-run retrying %s after a diagnosed %s failure" % (mode, d["classification"]), flush=True)
        time.sleep(5)


def _verify_ota():
    """Read the runtime's OWN signal, not the exit code: fetch the LIVE
    manifest and confirm it references the exact bundle we just exported
    (its content-hashed filename) - the same round-trip discipline
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
    """The PRD's own sharpest finding: a native ship must not be called
    green on exit 0 alone. Cross-check the three numbers that are supposed
    to agree - app.json, the built APK (via aapt2), and what the relay
    actually serves - and report a disagreement as the headline, not an
    average."""
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


# ------------------------------------------------------------------ stages
def stage_diagnose(kind):
    print("HOOK-NOTE: STAGE 1/3 DIAGNOSE - fresh evidence + resource preflight", flush=True)
    print("=== STAGE 1/3: DIAGNOSE ===", flush=True)
    sf = _ship_facts_tool()
    facts = sf.collect()
    print(sf._human(facts), flush=True)

    if kind == "none":
        print("HOOK-NOTE: DIAGNOSE RESULT - nothing to ship (SHIP_KIND=none)", flush=True)
        return {"go": False, "exit": 0}
    if kind not in ("ota", "native"):
        print("HOOK-NOTE: DIAGNOSE RESULT - SHIP_KIND=%r invalid, refusing to guess" % kind, flush=True)
        return {"go": False, "exit": 1}

    res = facts["resources"]
    missing = []
    if kind == "native":
        for k in ("jdk17", "android_sdk", "keystore", "disk"):
            if res.get(k, {}).get("ok") is False:
                missing.append("%s (%s)" % (k, res[k].get("needed_for") or res[k].get("why") or ""))
    if res.get("relay_creds", {}).get("ok") is False:
        missing.append("relay_creds (%s)" % (res["relay_creds"].get("why") or ""))
    if missing:
        print("HOOK-NOTE: DIAGNOSE RESULT - BLOCKED (%s), missing: %s" % (kind, "; ".join(missing)), flush=True)
        return {"go": False, "exit": 1}

    kt_start = None
    if kind == "native":
        rc, out, err = _ship_tool("kt-start")
        if rc != 0 or not out:
            print("HOOK-NOTE: DIAGNOSE RESULT - BLOCKED, could not read the source fingerprint (%s)" % err, flush=True)
            return {"go": False, "exit": 1}
        kt_start = out

    print("HOOK-NOTE: DIAGNOSE RESULT - GO (%s)" % kind, flush=True)
    return {"go": True, "kind": kind, "kt_start": kt_start}


def stage_execute(kind, kt_start):
    print("HOOK-NOTE: STAGE 2/3 EXECUTE - %s" % (
        "APK build starting (npm ci + gradle + emulator smoke, ~15-20 min)" if kind == "native"
        else "OTA export + publish"), flush=True)
    print("=== STAGE 2/3: EXECUTE ===", flush=True)
    _acquire_lock()
    try:
        bump = None
        if kind == "native":
            rc, out, err = _ship_tool("bump")
            if rc != 0:
                print("HOOK-NOTE: EXECUTE RESULT - FAILED (version bump: %s)" % err, flush=True)
                return {"ok": False, "why": "version bump failed: %s" % err}
            bump = out
            print("[ship-run] version -> %s (new runtimeVersion; old APKs will reject this JS instead of crashing)" % bump, flush=True)

        ok, why, _tail = _run_with_retry(kind)
        if not ok:
            if kind == "native":
                _ship_tool("revert-bump")
                print("[ship-run] reverted the version bump - not recording the fingerprint", flush=True)
            print("HOOK-NOTE: EXECUTE RESULT - FAILED (%s)" % why, flush=True)
            return {"ok": False, "why": why}

        if kind == "native":
            rc, out, err = _ship_tool("finalize-native", kt_start)
            if rc != 0:
                print("HOOK-NOTE: WARN - finalize-native failed (%s), the next accept may re-detect this as native" % err, flush=True)
            print("HOOK-NOTE: APK distributed - pushing the matching OTA bundle", flush=True)
            ok2, why2, _tail2 = _run_with_retry("ota")
            if not ok2:
                print("HOOK-NOTE: EXECUTE RESULT - FAILED (APK built but matching OTA failed: %s - the old relay bundle would revert this APK's JS)" % why2, flush=True)
                return {"ok": False, "why": why2}

        print("HOOK-NOTE: EXECUTE RESULT - OK (%s)" % kind, flush=True)
        return {"ok": True, "bump": bump}
    finally:
        _release_lock()


def stage_verify(kind):
    print("HOOK-NOTE: STAGE 3/3 VERIFY - re-checking the live signal before calling this green", flush=True)
    print("=== STAGE 3/3: VERIFY ===", flush=True)
    try:
        ok, why = (_verify_ota() if kind == "ota" else _verify_native())
    except Exception as e:
        ok, why = False, "verification crashed (%s) - treating as unverified, not green" % e
    print("HOOK-NOTE: VERIFY RESULT - %s (%s)" % ("OK" if ok else "FAILED", why), flush=True)
    return ok, why


def main():
    kind = (os.environ.get("SHIP_KIND") or "").strip()
    dry = os.environ.get("SHIP_DRY_RUN") == "1"

    d = stage_diagnose(kind)
    if not d["go"]:
        return d["exit"]

    if dry:
        print("[ship-run] DRY RUN - stopping after DIAGNOSE (would EXECUTE %s, then VERIFY); nothing changed" % d["kind"], flush=True)
        return 0

    e = stage_execute(d["kind"], d.get("kt_start"))
    if not e["ok"]:
        print("SHIP: FAILED")
        print("WHY: %s" % e["why"])
        return 1

    ok, why = stage_verify(d["kind"])
    if not ok:
        print("SHIP: FAILED")
        print("WHY: EXECUTE succeeded but VERIFY disagrees: %s" % why)
        return 1

    print("HOOK-NOTE: ship done - %s" % ("OTA live" if d["kind"] == "ota" else "APK + matching OTA live"), flush=True)
    print("SHIP: OK")
    print("WHY: %s" % why)
    return 0


if __name__ == "__main__":
    sys.exit(main())
