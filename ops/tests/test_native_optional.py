"""May the CURRENT JS bundle run on the PREVIOUS Android APK? (2026-10-20)

Owner: "keine Brüche mehr für version". A native ship bumps
android.runtimeVersion; the phone still on the previous APK then got NO OTA
at all - not even the screen telling it to install the new APK (measured the
same morning: 1.0.53 phone, "no update available" in red). push_update.sh now
also publishes the current bundle into rt-<previous runtime>, but only when
this check says it is safe:

  every NATIVE package added since the previous APK was built must never be
  imported directly by the app - only through requireOptionalNativeModule
  (null on an APK without it), the data/glasses.ts / _layout useNetworkChange
  pattern. A direct import of such a package would throw at bundle load on the
  older APK = a white screen, which is worse than no update.

The previous APK's source = the oldest commit whose app.json carries that
android runtimeVersion (the native ship's bump). Native = the package ships an
android/ dir or an expo-module.config.json.

Usage:
  py -3.12 ops/tests/test_native_optional.py              # previous runtime, exit 0/1
  py -3.12 ops/tests/test_native_optional.py --runtime X  # a specific older runtime
  py -3.12 ops/tests/test_native_optional.py --print-prev # just print the previous runtime
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = os.path.join(ROOT, "surfaces", "app")
APP_JSON = "surfaces/app/app.json"
PKG_JSON = "surfaces/app/package.json"


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout


def android_rt(doc):
    e = (doc or {}).get("expo") or {}
    return (e.get("android") or {}).get("runtimeVersion") or (
        e.get("runtimeVersion") if isinstance(e.get("runtimeVersion"), str) else None) or e.get("version")


def history():
    """[(commit, android runtimeVersion)] for app.json, newest first."""
    out = []
    for c in git("log", "--format=%H", "--", APP_JSON).split():
        try:
            out.append((c, android_rt(json.loads(git("show", "%s:%s" % (c, APP_JSON))))))
        except ValueError:
            continue
    return out


def current_rt():
    return android_rt(json.load(open(os.path.join(ROOT, APP_JSON), encoding="utf-8")))


def previous_rt():
    cur = current_rt()
    for _c, rt in history():
        if rt and rt != cur:
            return rt
    return None


def build_commit(rt):
    """The OLDEST commit whose app.json has this runtime = the native ship that
    introduced it, i.e. the source that APK was built from."""
    hits = [c for c, r in history() if r == rt]
    return hits[-1] if hits else None


def deps_at(commit):
    try:
        d = json.loads(git("show", "%s:%s" % (commit, PKG_JSON)))
    except ValueError:
        return set()
    return set((d.get("dependencies") or {}).keys())


def is_native(pkg):
    base = os.path.join(APP, "node_modules", *pkg.split("/"))
    return os.path.isdir(os.path.join(base, "android")) or os.path.isfile(os.path.join(base, "expo-module.config.json"))


def direct_imports(pkg):
    pat = re.compile(r"""(from\s+|require\(\s*|import\(\s*)["']%s(/[^"']*)?["']""" % re.escape(pkg))
    hits = []
    for d in [os.path.join(APP, "src")] + [os.path.join(ROOT, "cells", c, "ui") for c in os.listdir(os.path.join(ROOT, "cells"))]:
        for dp, dn, fn in os.walk(d):
            dn[:] = [x for x in dn if x != "node_modules" and not x.startswith(".")]
            for f in fn:
                if f.endswith((".ts", ".tsx", ".js")) and "selftest" not in f:
                    p = os.path.join(dp, f)
                    if pat.search(open(p, encoding="utf-8").read()):
                        hits.append(os.path.relpath(p, ROOT))
    return hits


def check(rt):
    commit = build_commit(rt)
    if not commit:
        print("FAIL no commit carries android runtimeVersion %s - cannot judge" % rt)
        return False
    now = set(json.load(open(os.path.join(ROOT, PKG_JSON), encoding="utf-8")).get("dependencies", {}).keys())
    added = sorted(p for p in now - deps_at(commit) if is_native(p))
    print("previous APK runtime %s built from %s; native packages added since: %s"
          % (rt, commit[:8], ", ".join(added) or "none"))
    ok = True
    for p in added:
        hits = direct_imports(p)
        if hits:
            ok = False
            print("FAIL %s is imported directly (white screen on the %s APK): %s" % (p, rt, ", ".join(hits)))
        else:
            print("ok   %s is only reached optionally" % p)
    return ok


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--print-prev" in a:
        print(previous_rt() or "")
        sys.exit(0)
    rt = a[a.index("--runtime") + 1] if "--runtime" in a else previous_rt()
    if not rt:
        print("no previous android runtime - nothing to check")
        sys.exit(0)
    good = check(rt)
    print("RESULT:", "PASS" if good else "FAIL")
    sys.exit(0 if good else 1)
