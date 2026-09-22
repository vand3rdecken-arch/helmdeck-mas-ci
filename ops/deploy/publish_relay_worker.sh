#!/usr/bin/env bash
# Publish the HelmDeck relay worker (surfaces/relay/worker) to Cloudflare.
#
# One command = relay code + every OTA channel currently published. The OTA
# bundles are shipped as static assets of the worker, so "deploy the worker"
# is also "publish the updates" - there is no separate upload step and no
# server directory to sync any more (2026-09-22: relay moved off the owner's
# PC; see surfaces/relay/worker/wrangler.jsonc).
#
#   bash ops/deploy/publish_relay_worker.sh                # sync channels from SRC, deploy
#   bash ops/deploy/publish_relay_worker.sh --dry-run      # build public/, print the plan
#   bash ops/deploy/publish_relay_worker.sh --apk-url URL  # where /apk/helmdeck.apk redirects
#
# SRC (env HELMDECK_UPDATES_SRC, default /c/opt): the directories push_update.sh
# already writes - helmdeck-updates (production), helmdeck-updates-<channel>,
# helmdeck-apk/version.json. Each channel gets a _index.json with per-file
# sha256 (base64url, what the Expo manifest carries), the runtimeVersion
# marker, createdAt (metadata.json mtime - keeps manifest ids stable across the
# migration) and the rollback marker, so the worker computes nothing at request
# time. *.old directories are skipped.
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
export PATH="/c/Program Files/nodejs:$PATH"
PY="${HELMDECK_PY:-py -3.12}"
SRC="${HELMDECK_UPDATES_SRC:-/c/opt}"
W="surfaces/relay/worker"
DRY=0; APK_URL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --apk-url) APK_URL="${2:-}"; shift ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac; shift
done

echo "==> static pages from relay.py"
$PY "$W/gen_static.py" || exit 1

echo "==> OTA channels from $SRC -> $W/public/ota"
rm -rf "$W/public"; mkdir -p "$W/public/ota" "$W/public/apk"
$PY - "$SRC" "$W/public" <<'PYEOF' || exit 1
import base64, hashlib, io, json, os, shutil, sys, time
src, pub = sys.argv[1], sys.argv[2]
def b64url_sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""): h.update(chunk)
    return base64.urlsafe_b64encode(h.digest()).decode().rstrip("=")
n_ch = 0
for name in sorted(os.listdir(src)):
    if not name.startswith("helmdeck-updates") or name.endswith(".old"): continue
    d = os.path.join(src, name)
    if not os.path.isdir(d): continue
    channel = "production" if name == "helmdeck-updates" else name[len("helmdeck-updates-"):]
    dst = os.path.join(pub, "ota", channel)
    shutil.copytree(d, dst)
    idx = {"channel": channel, "hashes": {}, "runtimeVersion": None, "createdAt": None, "rollback": None, "metadata": None}
    for base, _, files in os.walk(dst):
        for f in files:
            fp = os.path.join(base, f)
            rel = os.path.relpath(fp, dst).replace("\\", "/")
            if rel == "_index.json": continue
            if os.path.getsize(fp) > 25 * 1024 * 1024:
                sys.exit("asset over the 25 MB static-asset limit: %s" % fp)
            idx["hashes"][rel] = b64url_sha256(fp)
    m = os.path.join(dst, "metadata.json")
    if os.path.isfile(m):
        idx["metadata"] = json.load(io.open(m, encoding="utf-8"))
        idx["createdAt"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(os.path.getmtime(m)))
    r = os.path.join(dst, "runtimeVersion")
    if os.path.isfile(r): idx["runtimeVersion"] = io.open(r, encoding="utf-8").read().strip() or None
    rb = os.path.join(dst, "rollback.json")
    if os.path.isfile(rb):
        try: ct = (json.load(io.open(rb, encoding="utf-8")) or {}).get("commitTime")
        except Exception: ct = None
        idx["rollback"] = {"commitTime": ct or time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(os.path.getmtime(rb)))}
    io.open(os.path.join(dst, "_index.json"), "w", encoding="utf-8").write(json.dumps(idx))
    n_ch += 1
    print("   %-14s files=%-4d rtv=%-8s createdAt=%s" % (channel, len(idx["hashes"]), idx["runtimeVersion"], idx["createdAt"]))
v = os.path.join(src, "helmdeck-apk", "version.json")
if os.path.isfile(v):
    shutil.copy(v, os.path.join(pub, "apk", "version.json")); print("   apk/version.json copied")
if not n_ch: sys.exit("no helmdeck-updates* channel found under %s" % src)
PYEOF

TOTAL=$(find "$W/public" -type f | wc -l)
echo "==> $TOTAL files staged"
if [ "$DRY" = "1" ]; then echo "(dry run - not deploying)"; exit 0; fi

cd "$W"
ARGS=()
[ -n "$APK_URL" ] && ARGS+=(--var "APK_URL:$APK_URL")
echo "==> wrangler deploy"
npx wrangler deploy "${ARGS[@]}" || exit 1
