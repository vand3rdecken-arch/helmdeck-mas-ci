# -*- coding: utf-8 -*-
"""Pins: a native ship whose APK DISTRIBUTION fails must fail hard.

Measured 2026-10-07 (.loop/ship.log): build_apk.sh built 1.0.52 (95), the upload
(push_relay.sh -> SSH to the dead trooper VM) failed, `|| echo WARN` swallowed it,
build_apk exited 0 and ship.sh pushed the matching OTA as if the APK existed.

Runs the REAL ship.sh + push_apk.sh in a throwaway git repo. Sandboxed: build_apk.sh
and push_update.sh are stubs (the latter records that it was called), `gh` is a fake
first on PATH - nothing real is built, uploaded or published.

  failure  -> ship exits != 0, NO OTA, app.json bump reverted, no version.json
  success  -> ship exits 0, OTA pushed, version.json staged

Run: py -3.12 ops/tests/test_native_ship_distribution.py
"""
import hashlib, json, os, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASH = r"C:\Program Files\Git\bin\bash.exe"

FAKE_GH = r"""#!/usr/bin/env bash
case "$1 $2" in
  "release view")
    case "$*" in
      *tagName*) echo v-test ;;
      *assets*)  echo "$FAKE_SIZE sha256:$FAKE_SHA" ;;
    esac ;;
  "release upload") [ -n "$FAKE_GH_FAIL" ] && { echo "gh: upload failed" >&2; exit 1; }; exit 0 ;;
  *) exit 1 ;;
esac
"""


def run(args, cwd, env):
    return subprocess.run([BASH] + args, cwd=cwd, env=env, capture_output=True, text=True)


def scenario(fail):
    root = tempfile.mkdtemp(prefix="hd-ship-dist-")
    try:
        os.makedirs(os.path.join(root, "ops", "deploy"))
        os.makedirs(os.path.join(root, "surfaces", "app"))
        for f in ("ship.sh", "push_apk.sh"):
            shutil.copy(os.path.join(REPO, "ops", "deploy", f), os.path.join(root, "ops", "deploy", f))
        stub = lambda name, body: open(os.path.join(root, "ops", "deploy", name), "w", newline="\n").write(
            "#!/usr/bin/env bash\n" + body)
        stub("build_apk.sh", "exit 0\n")                       # the build itself succeeded
        stub("push_update.sh", 'touch "$(dirname "$0")/OTA_PUSHED"\nexit 0\n')
        app_json = os.path.join(root, "surfaces", "app", "app.json")
        orig = json.dumps({"expo": {"version": "1.0.51", "android": {"versionCode": 94}}}, indent=2) + "\n"
        open(app_json, "w", newline="\n").write(orig)
        apk = os.path.join(root, "app-release.apk")
        open(apk, "wb").write(b"fake-apk-bytes")
        gh_dir = os.path.join(root, "fakebin"); os.makedirs(gh_dir)
        open(os.path.join(gh_dir, "gh"), "w", newline="\n").write(FAKE_GH)
        apk_dir = os.path.join(root, "apkdir")
        for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"]):
            subprocess.run(["git"] + cmd, cwd=root, check=True, capture_output=True)
        env = dict(os.environ, SHIP_KIND="native", HELMDECK_APK_FILE=apk, HELMDECK_APK_DIR=apk_dir,
                   FAKE_SIZE=str(os.path.getsize(apk)), FAKE_SHA=hashlib.sha256(open(apk, "rb").read()).hexdigest(),
                   PATH=gh_dir + os.pathsep + os.environ["PATH"])
        env["FAKE_GH_FAIL"] = "1" if fail else ""
        # app.json must be tracked + clean before the ship, as in the real repo
        p = run(["ops/deploy/ship.sh"], root, env)
        return dict(rc=p.returncode, out=p.stdout + p.stderr,
                    ota=os.path.exists(os.path.join(root, "ops", "deploy", "OTA_PUSHED")),
                    version_json=os.path.exists(os.path.join(apk_dir, "version.json")),
                    app_json=open(app_json).read(), orig=orig,
                    vj=open(os.path.join(apk_dir, "version.json")).read() if os.path.exists(os.path.join(apk_dir, "version.json")) else "")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    bad = scenario(fail=True)
    assert bad["rc"] != 0, "failed distribution must fail the native ship\n" + bad["out"]
    assert not bad["ota"], "no OTA may be pushed after a failed APK distribution\n" + bad["out"]
    assert not bad["version_json"], "version.json must not advertise an undistributed APK"
    assert bad["app_json"] == bad["orig"], "version bump must be reverted\n" + bad["app_json"]
    ok = scenario(fail=False)
    assert ok["rc"] == 0, "healthy distribution must ship\n" + ok["out"]
    assert ok["ota"] and ok["version_json"], ok["out"]
    vj = json.loads(ok["vj"])
    assert vj["versionName"] == "1.0.52" and vj["versionCode"] == 95, vj
    print("OK: distribution failure aborts the native ship (rc=%d, no OTA, bump reverted); success ships" % bad["rc"])


if __name__ == "__main__":
    main()
