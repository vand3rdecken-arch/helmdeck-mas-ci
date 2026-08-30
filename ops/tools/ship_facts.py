# -*- coding: utf-8 -*-
"""SHIP EVIDENCE - what is true right now about shipping, with NO decision taken.

WHY THIS EXISTS (owner decree 2026-08-30): the ship decision was a fixed script.
`ops/deploy/ship.sh` hashes the native-relevant files, compares that hash to a
STORED file (ops/deploy/.native_fp), and branches OTA-vs-APK on the result. Two
things are wrong with that and both are written in the repo's own comments:

  - It is a stored flag, which the NO MONKEY PATCHES decree forbids outright
    ("never assumed from a stored flag ... never adopted without evidence").
  - It has been wrong in BOTH directions, repeatedly, and each fix bolted
    another exclusion onto the hash: a GlassVoiceService.kt change shipped as
    "JS-only" (2026-08-23, livemic almost never shipped); three straight
    accepts misread as native until app.json's ios/extra were excluded; and
    ops/tools/loop_state.py's hand-mirrored copy of the same hash DRIFTED and
    produced a phantom BUILD nag (its own comment at line ~303 says so).

An agent cannot reason about an opaque hash - same-or-different is the only
question it can answer, and it answers it wrongly. It CAN reason about "these
files changed, this is what they mean, this is what I have to work with". So
this module produces EVIDENCE and stops there.

THE LINE THIS MODULE DOES NOT CROSS: it reports facts, it never decides. No
"should_ship", no "kind": "native". That judgement belongs to the agent reading
this (same split as Henry - the engineer cell reports facts, never decides;
hard invariants stay in code, judgement stays with the reader). The legacy
fingerprint verdict IS reported, but as one observation among many and clearly
labelled as what the old heuristic thinks - a fact ABOUT the heuristic, not a
decision by it.

Everything here is read-only and best-effort: a probe that cannot answer says
so ("unknown" + why) instead of guessing or raising. An unreachable relay is a
FACT worth reporting, not a crash.

  py -3.12 ops/tools/ship_facts.py            # human-readable
  py -3.12 ops/tools/ship_facts.py --json     # for an agent / a card brief
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
APK_REL = "surfaces/app/android/app/build/outputs/apk/release/app-release.apk"
NATIVE_FP = "ops/deploy/.native_fp"


def _run(cmd, timeout=20, cwd=None):
    """Best-effort subprocess -> (rc, stdout). Never raises: a probe that cannot
    run is an 'unknown' fact, never an exception that kills the whole report."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=cwd or ROOT, errors="replace")
        return p.returncode, (p.stdout or "").strip()
    except Exception as e:
        return -1, "probe failed: %s" % str(e)[:120]


# --------------------------------------------------------------- what changed
# Path -> meaning. Ordered: FIRST match wins, so the specific native-source
# patterns beat the broad surfaces/app one. This is the half the hash threw
# away - an agent needs to know WHICH files moved and what they compile into,
# not that some opaque digest differs.
_CLASSES = [
    ("native-source", r"^surfaces/app/(plugins|modules)/.*\.(kt|java)$",
     "compiled INTO the APK - cannot reach a phone via OTA"),
    ("native-plugin", r"^surfaces/app/plugins/.*\.js$",
     "patches the android tree at prebuild time - only takes effect in a fresh APK"),
    ("native-config", r"^surfaces/app/app\.json$",
     "may be native (permissions/plugins/icons) or inert (version/ios/extra) - read the diff"),
    ("native-asset", r"^surfaces/app/assets/(images/(icon|splash|adaptive|android-icon)|expo\.icon/)",
     "baked into the APK by expo prebuild - OTA cannot replace it"),
    ("js-app", r"^surfaces/app/.*\.(ts|tsx|js|jsx)$", "ships fine over OTA"),
    ("js-asset", r"^surfaces/app/assets/", "ships fine over OTA"),
    ("cell-ui", r"^cells/.*/ui/", "app code - ships fine over OTA"),
    ("daemon-python", r"^(daemon|spine|cells)/.*\.py$",
     "runs on THIS box, not the phone - no app ship needed"),
    ("desktop", r"^surfaces/desktop/", "desktop surface - separate release path"),
    ("ops-tooling", r"^ops/", "build/test/deploy tooling - changes HOW we ship, not what ships"),
    ("docs", r"(^.*\.md$|^CLAUDE\.md$|^DEPLOY\.md$)", "no user-facing artifact"),
]


def _classify(path):
    for name, pat, why in _CLASSES:
        if re.search(pat, path):
            return name, why
    return "other", "unclassified - judge from the path"


def changed_files():
    """Files changed since the last recorded ship, classified by what they can
    actually reach.

    THE MARKER PROBLEM, reported rather than papered over: only a NATIVE ship
    leaves a trace (ship.sh writes ops/deploy/.native_fp at the end and commits
    a version bump). An OTA ship leaves NOTHING - no marker, no commit. So
    "changed since the last ship" is only answerable for native ships, and for
    OTA the honest answer is that we cannot know. That gap is itself a finding.
    """
    out = {"marker": None, "since": None, "files": [], "by_class": {}, "note": None}
    fp = os.path.join(ROOT, NATIVE_FP)
    if os.path.isfile(fp):
        out["marker"] = NATIVE_FP
        out["since"] = _iso(os.path.getmtime(fp))
    rc, head = _run(["git", "log", "-1", "--format=%H %ad %s", "--date=iso",
                     "--grep=^deploy: bump"])
    base = None
    if rc == 0 and head:
        base = head.split()[0]
        out["last_native_ship_commit"] = head[:120]
    if not base:
        out["note"] = ("no 'deploy: bump' commit found - cannot scope the diff; "
                       "treat every app file as potentially unshipped")
        return out
    rc, names = _run(["git", "diff", "--name-only", "%s..HEAD" % base])
    if rc != 0:
        out["note"] = "git diff failed: %s" % names[:120]
        return out
    files = [f for f in names.splitlines() if f.strip()]
    # Uncommitted work counts too - it is what a ship would carry if it ran now.
    rc2, dirty = _run(["git", "status", "--porcelain"])
    if rc2 == 0:
        for ln in dirty.splitlines():
            f = ln[3:].strip()
            if f and f not in files:
                files.append(f)
    for f in files:
        cls, why = _classify(f)
        out["by_class"].setdefault(cls, {"why": why, "files": []})["files"].append(f)
    out["files"] = files
    out["note"] = ("OTA ships leave no marker at all, so anything shipped by OTA "
                   "since the last NATIVE ship still appears here as 'changed'")
    return out


# ------------------------------------------------------------------ versions
def _read_app_json():
    try:
        with open(os.path.join(ROOT, "surfaces/app/app.json"), encoding="utf-8") as f:
            e = json.load(f)["expo"]
        return {"version": e.get("version"),
                "versionCode": (e.get("android") or {}).get("versionCode"),
                "runtimeVersionPolicy": (e.get("runtimeVersion") if isinstance(
                    e.get("runtimeVersion"), str) else
                    (e.get("runtimeVersion") or {}).get("policy"))}
    except Exception as e:
        return {"error": str(e)[:120]}


def _relay_domain():
    """Read the PUBLIC relay domain the same way push_relay.sh derives it. Only
    the domain is ever surfaced - never RELAY_SSH_*, never any other .env value.
    Secrets stay where they are; this is a report that lands in a card log."""
    env = {}
    try:
        with open(os.path.join(ROOT, ".env"), encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln and not ln.startswith("#") and "=" in ln:
                    k, v = ln.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        return None, "no .env"
    host = env.get("RELAY_HOST")
    if not host:
        return None, "RELAY_HOST unset in .env"
    return env.get("RELAY_DOMAIN") or ("%s.sslip.io" % host), None


def live_versions():
    """What the LOCAL tree says, what the BUILT APK says, and what the RELAY is
    actually serving. Three numbers that are supposed to agree and historically
    have not: DEPLOY.md records a 52-minute build that produced versionName
    1.0.2 while app.json said 1.0.8. Nothing in the pipeline compares them, so
    nothing ever noticed."""
    out = {"app_json": _read_app_json(), "apk": None, "relay": None}

    apk = os.path.join(ROOT, APK_REL)
    if not os.path.isfile(apk):
        out["apk"] = {"state": "absent", "path": APK_REL}
    else:
        info = {"state": "present", "mtime": _iso(os.path.getmtime(apk)),
                "size_mb": round(os.path.getsize(apk) / 1048576.0, 1)}
        aapts = sorted(glob.glob(os.path.join(
            os.path.expanduser("~"), "AppData/Local/Android/Sdk/build-tools/*/aapt2.exe")),
            reverse=True)
        if aapts:
            rc, o = _run([aapts[0], "dump", "badging", apk], timeout=90)
            if rc == 0:
                m = re.search(r"versionCode='(\d+)'.*?versionName='([^']*)'", o, re.S)
                if m:
                    info["versionCode"], info["versionName"] = int(m.group(1)), m.group(2)
                else:
                    info["note"] = "aapt2 gave no version line"
            else:
                info["note"] = "aapt2 failed: %s" % o[:100]
        else:
            info["note"] = "no aapt2 in the SDK - cannot read the APK's real version"
        out["apk"] = info

    dom, err = _relay_domain()
    if not dom:
        out["relay"] = {"state": "unknown", "why": err}
    else:
        url = "https://%s/apk/version.json" % dom
        try:
            with urllib.request.urlopen(url, timeout=12) as r:
                out["relay"] = dict(json.loads(r.read().decode("utf-8")),
                                    state="reachable", url=url)
        except Exception as e:
            out["relay"] = {"state": "unreachable", "url": url, "why": str(e)[:140]}
    return out


# ----------------------------------------------------------------- resources
def resources():
    """"Wo gibt es Ressourcen" - can this box ship at all, RIGHT NOW. Every one
    of these is a real, measured way a ship has died late and cryptically:
    build_apk.sh dies at line 10 with no JDK, gradle dies at minute 12 with no
    keystore, push_relay.sh dies after a 15-minute build with no RELAY_HOST.
    Knowing before starting is the difference between a 5-second answer and a
    20-minute failure."""
    r = {}

    jdk = sorted(glob.glob("C:/Program Files/Microsoft/jdk-17*"))
    r["jdk17"] = {"ok": bool(jdk), "path": (jdk[0] if jdk else None),
                  "needed_for": "any APK build (RN 0.86/Expo 57 reject Java 8)"}

    sdk = os.environ.get("ANDROID_HOME") or os.path.join(
        os.path.expanduser("~"), "AppData/Local/Android/Sdk")
    r["android_sdk"] = {"ok": os.path.isdir(sdk), "path": sdk}

    ks = glob.glob(os.path.join(ROOT, "daemon/certs/apk-signing/*.jks"))
    r["keystore"] = {"ok": bool(ks),
                     "name": (os.path.basename(ks[0]) if ks else None),
                     "needed_for": "signing the release APK"}

    dom, err = _relay_domain()
    r["relay_creds"] = {"ok": bool(dom), "domain": dom, "why": err,
                        "needed_for": "distributing the APK + OTA"}

    r["node_modules"] = {"ok": os.path.isdir(os.path.join(ROOT, "surfaces/app/node_modules")),
                         "note": "build_apk.sh runs npm ci anyway; absent only means a slower build"}

    try:
        du = shutil.disk_usage(ROOT)
        free = round(du.free / 1073741824.0, 1)
        r["disk"] = {"free_gb": free, "ok": free > 12,
                     "needed_for": "~10GB: gradle caches + a 100MB APK + node_modules"}
    except Exception as e:
        r["disk"] = {"ok": None, "why": str(e)[:80]}

    # "no emulator attached" and "adb is not on PATH" are DIFFERENT facts and
    # must not collapse into one false answer: this python process does not
    # inherit build_apk.sh's PATH (which prepends platform-tools), so probing a
    # bare `adb` reported "no emulator" on a box that has one. Resolve the
    # binary the same way build_apk.sh does before concluding anything.
    adb = shutil.which("adb") or next(
        (p for p in [os.path.join(sdk, "platform-tools", "adb.exe")] if os.path.isfile(p)), None)
    if not adb:
        r["emulator"] = {"ok": None, "state": "unknown",
                         "why": "adb not found on PATH nor in %s/platform-tools" % sdk,
                         "note": "cannot tell whether a device is attached"}
    else:
        rc, st = _run([adb, "get-state"], timeout=15)
        r["emulator"] = {"ok": (rc == 0 and "device" in st),
                         "state": (st if rc == 0 else "no device"),
                         "note": "build_apk.sh's smoke test SILENTLY skips when absent"}

    # The mutex from the same decree - a queued build is healthy, and an agent
    # deciding whether to ship must know it would wait rather than run.
    lock = os.path.join(os.environ.get("HELMDECK_LOCK_DIR") or os.path.join(
        os.path.expanduser("~"), ".helmdeck", "locks"), "android-build")
    held, holder, label = False, None, None
    try:
        pids = [l.strip() for l in open(os.path.join(lock, "pid")).read().splitlines() if l.strip()]
        holder = pids[1] if len(pids) > 1 else (pids[0] if pids else None)
        label = open(os.path.join(lock, "label"), encoding="utf-8").read().strip()
        try:
            os.kill(int(holder), 0)
            held = True
        except (OSError, ValueError):
            held = False
    except OSError:
        pass
    r["android_build_lock"] = {"held": held, "holder_pid": holder, "label": label,
                               "note": ("a build would QUEUE behind this one"
                                        if held else "free - a build would start now")}
    return r


# ---------------------------------------------------------- legacy heuristic
def legacy_fingerprint():
    """What ship.sh's stored-hash heuristic currently believes. Reported as an
    OBSERVATION about the heuristic - never as this module's own verdict. An
    agent should weigh it against the classified file list above, which is the
    evidence the hash discarded."""
    fp = os.path.join(ROOT, NATIVE_FP)
    out = {"marker_file": NATIVE_FP, "exists": os.path.isfile(fp)}
    if not out["exists"]:
        out["verdict"] = "no stored fingerprint - ship.sh would treat this as NATIVE"
        return out
    out["stored_at"] = _iso(os.path.getmtime(fp))
    out["verdict"] = ("ship.sh compares a fresh hash against this file; equal -> OTA, "
                      "different -> full APK build. Recomputing it here would mean "
                      "hand-mirroring ship.sh's hash a THIRD time - loop_state.py "
                      "already did that and drifted, so this module deliberately "
                      "does not. Run ops/deploy/ship.sh to see its own verdict.")
    return out


def _iso(ts):
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def collect():
    return {"changed": changed_files(), "versions": live_versions(),
            "resources": resources(), "legacy_heuristic": legacy_fingerprint()}


def _human(f):
    L = []
    ch = f["changed"]
    L.append("== WAS SICH GEAENDERT HAT (seit %s)" % (ch.get("since") or "unbekannt"))
    if ch.get("last_native_ship_commit"):
        L.append("   letzter nativer Ship: %s" % ch["last_native_ship_commit"])
    if not ch["by_class"]:
        L.append("   (keine Aenderungen gefunden)")
    for cls, d in sorted(ch["by_class"].items()):
        L.append("   %-15s %2d Datei(en) - %s" % (cls, len(d["files"]), d["why"]))
        for p in d["files"][:6]:
            L.append("       %s" % p)
        if len(d["files"]) > 6:
            L.append("       ... +%d weitere" % (len(d["files"]) - 6))
    if ch.get("note"):
        L.append("   ! %s" % ch["note"])

    v = f["versions"]
    L.append("")
    L.append("== VERSIONEN (muessen uebereinstimmen, historisch taten sie es nicht)")
    aj = v["app_json"]
    L.append("   app.json    %s / versionCode %s" % (aj.get("version"), aj.get("versionCode")))
    apk = v["apk"] or {}
    if apk.get("state") == "present":
        L.append("   APK gebaut  %s / versionCode %s  (%s, %s MB)" % (
            apk.get("versionName", "?"), apk.get("versionCode", "?"),
            apk.get("mtime"), apk.get("size_mb")))
        if apk.get("note"):
            L.append("       ! %s" % apk["note"])
    else:
        L.append("   APK gebaut  keiner vorhanden")
    rl = v["relay"] or {}
    if rl.get("state") == "reachable":
        L.append("   Relay live  %s / versionCode %s" % (
            rl.get("versionName", "?"), rl.get("versionCode", "?")))
    else:
        L.append("   Relay live  %s - %s" % (rl.get("state"), rl.get("why", "")[:80]))

    L.append("")
    L.append("== RESSOURCEN")
    for k, d in f["resources"].items():
        if k == "android_build_lock":
            L.append("   %-18s %s" % (k, d["note"]))
            continue
        mark = {True: "ja ", False: "NEIN", None: "?  "}[d.get("ok")]
        extra = d.get("path") or d.get("domain") or d.get("name") or d.get("state") or ""
        if k == "disk":
            extra = "%s GB frei" % d.get("free_gb")
        L.append("   %-18s %s  %s" % (k, mark, str(extra)[:60]))
        if d.get("ok") is False and d.get("needed_for"):
            L.append("       ! blockiert: %s" % d["needed_for"])

    L.append("")
    L.append("== ALTE HEURISTIK")
    L.append("   %s" % f["legacy_heuristic"]["verdict"])
    L.append("")
    L.append("Dies sind FAKTEN, keine Entscheidung. Ob und was geshippt wird,")
    L.append("entscheidet der Agent, der das hier liest.")
    return "\n".join(L)


if __name__ == "__main__":
    facts = collect()
    if "--json" in sys.argv:
        print(json.dumps(facts, indent=2, ensure_ascii=False))
    else:
        print(_human(facts))
