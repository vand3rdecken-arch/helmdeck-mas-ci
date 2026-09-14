# Self-sandboxed check that ops/deploy/push_update.sh publishes the phone OTA
# for iOS as well as android, and that its verify makes the ship RED when a
# platform gets no update. Runs the REAL script (copied into a temp root) under
# git-bash against a real relay.py on an ephemeral port + temp updates dir;
# only `npx` (fake expo export: writes one bundle per --platform) and the
# https relay URL (rewritten to the local http relay) are stubbed as bash
# functions. Nothing touches the live /c/opt/helmdeck-updates.
# Fails on the pre-2026-09-14 script: it exported android only (ios -> 404)
# and its verify was a `|| true` preview (exit 0 on a missing platform).
#   py -3.12 ops/tests/test_push_update_ios.py
import json, os, shutil, subprocess, sys, tempfile, threading, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="hd-pushupd-")
UPD = os.path.join(TMP, "updates").replace("\\", "/")
os.environ["HELMDECK_UPDATES_DIR"] = UPD
sys.path.insert(0, os.path.join(ROOT, "surfaces", "relay"))
import relay  # noqa: E402  (reads HELMDECK_UPDATES_DIR at import)
from http.server import ThreadingHTTPServer  # noqa: E402

srv = ThreadingHTTPServer(("127.0.0.1", 0), relay.H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

fails = []
def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        fails.append(name)

# temp repo root: the real script + the real app.json
os.makedirs(os.path.join(TMP, "ops", "deploy"))
os.makedirs(os.path.join(TMP, "surfaces", "app"))
shutil.copy(os.path.join(ROOT, "ops", "deploy", "push_update.sh"), os.path.join(TMP, "ops", "deploy"))
shutil.copy(os.path.join(ROOT, "surfaces", "app", "app.json"), os.path.join(TMP, "surfaces", "app"))
with open(os.path.join(ROOT, "surfaces", "app", "app.json"), encoding="utf-8") as f:
    RTV = json.load(f)["expo"]["version"]

STUBS = r'''
npx() {
  local out="" plats=()
  while [ $# -gt 0 ]; do
    case "$1" in --platform|-p) plats+=("$2"); shift ;; --output-dir) out="$2"; shift ;; esac
    shift
  done
  mkdir -p "$out"; local fm="" sep=""
  for p in "${plats[@]}"; do
    mkdir -p "$out/b/$p"; echo "js-$p" > "$out/b/$p/index-$p.hbc"
    fm="$fm$sep\"$p\":{\"bundle\":\"b/$p/index-$p.hbc\",\"assets\":[]}"; sep=","
  done
  printf '{"version":0,"bundler":"metro","fileMetadata":{%s}}' "$fm" > "$out/metadata.json"
}
curl() {
  local a=(); for x in "$@"; do a+=("${x/https:\/\/relay.test/http://127.0.0.1:__PORT__}"); done
  command curl "${a[@]}"
}
export -f npx curl
exec bash ops/deploy/push_update.sh "$@"
'''.replace("__PORT__", str(port))

BASH = r"C:\Program Files\Git\bin\bash.exe"
def run(*args):
    env = dict(os.environ, HELMDECK_RELAY_PORT=str(port), RELAY_DOMAIN="relay.test")
    p = subprocess.run([BASH, "-c", STUBS, "push_update", *args], cwd=TMP, env=env,
                       capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout + p.stderr

def manifest(platform):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/updates/manifest", headers={
        "expo-platform": platform, "expo-runtime-version": RTV, "expo-protocol-version": "1"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

try:
    # (a) a normal publish serves BOTH phone platforms and exits 0
    rc, out = run()
    check("publish exits 0", rc == 0, out[-800:])
    for plat in ("android", "ios"):
        code, body = manifest(plat)
        check(f"{plat} manifest 200 at runtime {RTV}", code == 200, f"{code} {body[:120]}")
        check(f"{plat} manifest points at the {plat} bundle", f"index-{plat}.hbc" in body, body[:200])
    check("verify line reports ios 200", f"ios @ {RTV}: HTTP 200" in out, out[-800:])

    # (b) an export WITHOUT ios must make the ship red, not green
    with open(os.path.join(TMP, "surfaces", "app", "dist-ota", "metadata.json"), "w", encoding="utf-8") as f:
        json.dump({"version": 0, "bundler": "metro", "fileMetadata": {
            "android": {"bundle": "b/android/index-android.hbc", "assets": []}}}, f)
    rc, out = run("--no-build")
    check("android-only bundle -> ios 404 -> nonzero exit", rc != 0, out[-800:])
    check("failure names ios", "VERIFY FAILED for: ios" in out, out[-800:])

    # (c) app.json: iOS follows the global appVersion policy, no frozen literal
    with open(os.path.join(ROOT, "surfaces", "app", "app.json"), encoding="utf-8") as f:
        expo = json.load(f)["expo"]
    check("no ios.runtimeVersion override", "runtimeVersion" not in expo.get("ios", {}),
          str(expo.get("ios", {}).get("runtimeVersion")))
finally:
    srv.shutdown()
    shutil.rmtree(TMP, ignore_errors=True)

print("\n%d failure(s)" % len(fails) if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
