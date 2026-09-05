#!/usr/bin/env bash
# HelmDeck Watch - build (XcodeGen -> xcodebuild). Mirrors
# surfaces/desktop/build-mac.sh's shape on purpose: MUST run on macOS
# (xcodebuild is Xcode-only), succeeds UNSIGNED with no secrets so a fresh CI
# run always proves the target compiles, and only archives/signs when Apple
# credentials are present.
#
#   bash surfaces/watch/build-watch.sh    # unsigned compile-only check
#   (the env below switches it to a signed archive)
#
# SIGNING is not a --flag, it is WHETHER THE ENV IS COMPLETE. Signed mode
# needs ALL of:
#   ASC_KEY_ID / ASC_ISSUER_ID / ASC_API_KEY_PATH   App Store Connect API key
#                                                    (same key ops/deploy/ios_credentials.sh
#                                                    and surfaces/desktop/build-mac.sh use)
#   APPLE_TEAM_ID                                   developer.apple.com -> Membership details
#   APPLE_CERT_P12_PATH / APPLE_CERT_PASSWORD       the team's Apple Distribution
#                                                    cert exported as .p12 (download
#                                                    from EAS' credential store -
#                                                    see README.md "Owner: the
#                                                    one-time credential step")
#
# WHY a .p12 instead of -allowProvisioningUpdates automatic signing (measured
# across 4 red CI runs, 2026-09-05): `xcodebuild archive` under Automatic
# signing requests an *Apple Development* identity - Xcode's model is
# "archive signs with Development, export re-signs with Distribution". A
# Development identity is the one thing a throwaway CI Mac can never keep:
# its private key is minted into that runner's keychain and destroyed with
# it ("...but its private key is not installed in your keychain"), and Apple
# caps Development certs at 2 per account, so retries wedge the account.
# The team's Distribution cert already exists (minted for app.helmdeck via
# EAS, commit 5eb6a5b) - importing it as a .p12 and signing Release MANUALLY
# (project.yml pins identity + profile names) sidesteps the whole class.
# Profiles are created/fetched by fastlane sigh (preinstalled on GitHub's
# macOS runners) via the same ASC API key - App Store profiles need no
# device UDIDs.
set -o pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

[ "$(uname -s)" = "Darwin" ] || {
  echo "!!! build-watch.sh must run on macOS - xcodebuild exists nowhere else."
  echo "    Use the macos runner: .github/workflows/watchos-app.yml"
  exit 2
}

echo "==> installing XcodeGen"
command -v xcodegen >/dev/null || brew install xcodegen || exit 1

echo "==> generating HelmDeckWatch.xcodeproj from project.yml"
xcodegen generate || exit 1

SIGNED=0
if [ -n "${ASC_KEY_ID:-}" ] && [ -n "${ASC_ISSUER_ID:-}" ] && [ -n "${ASC_API_KEY_PATH:-}" ] \
   && [ -n "${APPLE_TEAM_ID:-}" ] && [ -n "${APPLE_CERT_P12_PATH:-}" ] && [ -n "${APPLE_CERT_PASSWORD:-}" ]; then
  SIGNED=1
elif [ -n "${ASC_KEY_ID:-}" ]; then
  echo "==> signing: PARTIAL - ASC key present but APPLE_CERT_P12/APPLE_CERT_PASSWORD"
  echo "    secrets missing. Falling back to the unsigned compile-only build."
  echo "    For the signed archive do the one-time credential step in surfaces/watch/README.md."
fi

if [ "$SIGNED" != "1" ]; then
  echo "==> signing: OFF - unsigned compile-only build"
  xcodebuild build \
    -project HelmDeckWatch.xcodeproj \
    -scheme HelmDeckWatchCompanion \
    -destination "generic/platform=iOS" \
    CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO \
    || { echo "!!! build failed"; exit 1; }
  echo "DONE. Target compiles."
  exit 0
fi

echo "==> signing: ON (ASC key $ASC_KEY_ID, team $APPLE_TEAM_ID) - manual-signed Release archive"
TMP="${RUNNER_TEMP:-$(mktemp -d)}"

echo "==> importing the Apple Distribution cert into a throwaway keychain"
KC="$TMP/helmdeck-watch.keychain-db"
KC_PASS="$(uuidgen)"
security create-keychain -p "$KC_PASS" "$KC" || exit 1
security set-keychain-settings -lut 21600 "$KC"
security unlock-keychain -p "$KC_PASS" "$KC" || exit 1
security import "$APPLE_CERT_P12_PATH" -P "$APPLE_CERT_PASSWORD" -A -t cert -f pkcs12 -k "$KC" || exit 1
# Without this, codesign hangs on a keychain ACL prompt no CI can answer.
security set-key-partition-list -S apple-tool:,apple: -s -k "$KC_PASS" "$KC" >/dev/null || exit 1
security list-keychains -d user -s "$KC" login.keychain-db

echo "==> API key json for fastlane"
API_JSON="$TMP/asc-api-key.json"
jq -n --arg kid "$ASC_KEY_ID" --arg iss "$ASC_ISSUER_ID" --rawfile key "$ASC_API_KEY_PATH" \
  '{key_id: $kid, issuer_id: $iss, key: $key, in_house: false}' > "$API_JSON" || exit 1

# App IDs first (sigh cannot create them). NOT via fastlane produce/
# create_app_online: that tool never migrated off Apple-ID auth - its option
# list has no api_key_path at all (measured on 2.238). Bundle-ID
# registration is a plain official ASC API endpoint though, so mint the
# same JWT xcodebuild/sigh use (node is preinstalled; ieee-p1363 gives the
# raw r||s signature JWTs need) and POST directly. 201 = created, 409 =
# already registered - both fine; anything else is a real error.
echo "==> registering App IDs (ASC API directly)"
ASC_TOKEN="$(node -e '
const crypto=require("crypto"),fs=require("fs");
const key=fs.readFileSync(process.env.ASC_API_KEY_PATH,"utf8");
const b64u=o=>Buffer.from(JSON.stringify(o)).toString("base64url");
const now=Math.floor(Date.now()/1000);
const si=b64u({alg:"ES256",kid:process.env.ASC_KEY_ID,typ:"JWT"})+"."+
  b64u({iss:process.env.ASC_ISSUER_ID,iat:now,exp:now+1200,aud:"appstoreconnect-v1"});
const sig=crypto.sign("sha256",Buffer.from(si),{key,dsaEncoding:"ieee-p1363"}).toString("base64url");
process.stdout.write(si+"."+sig);
')" || exit 1
register_app_id() { # identifier, name
  local code
  code=$(curl -sS -o "$TMP/bundleid.json" -w '%{http_code}' \
    -X POST https://api.appstoreconnect.apple.com/v1/bundleIds \
    -H "Authorization: Bearer $ASC_TOKEN" -H 'Content-Type: application/json' \
    -d "{\"data\":{\"type\":\"bundleIds\",\"attributes\":{\"identifier\":\"$1\",\"name\":\"$2\",\"platform\":\"IOS\"}}}")
  case "$code" in
    201) echo "    $1: registered" ;;
    409) echo "    $1: already registered (409)" ;;
    *)   echo "!!! $1: HTTP $code"; cat "$TMP/bundleid.json"; return 1 ;;
  esac
}
register_app_id app.helmdeck.watchcompanion "HelmDeck Watch Companion" || exit 1
register_app_id app.helmdeck.watchcompanion.watchkitapp "HelmDeck Watch App" || exit 1

# One App Store profile per target, with the FIXED names project.yml's
# PROVISIONING_PROFILE_SPECIFIER expects. sigh DID migrate to API-key auth.
echo "==> fetching App Store profiles (fastlane sigh)"
fastlane run get_provisioning_profile api_key_path:"$API_JSON" team_id:"$APPLE_TEAM_ID" \
  app_identifier:app.helmdeck.watchcompanion provisioning_name:"HelmDeckWatchCompanion AppStore" \
  force:true output_path:"$TMP/profiles" || exit 1
fastlane run get_provisioning_profile api_key_path:"$API_JSON" team_id:"$APPLE_TEAM_ID" \
  app_identifier:app.helmdeck.watchcompanion.watchkitapp provisioning_name:"HelmDeckWatch AppStore" \
  force:true output_path:"$TMP/profiles" || exit 1

echo "==> xcodebuild archive (manual Release signing - identity + profiles pinned in project.yml)"
xcodebuild archive \
  -project HelmDeckWatch.xcodeproj \
  -scheme HelmDeckWatchCompanion \
  -archivePath build/HelmDeckWatchCompanion.xcarchive \
  -destination "generic/platform=iOS" \
  -configuration Release \
  "DEVELOPMENT_TEAM=$APPLE_TEAM_ID" \
  OTHER_CODE_SIGN_FLAGS="--keychain $KC" \
  || { echo "!!! archive failed"; exit 1; }
echo "DONE. Archive -> surfaces/watch/build/HelmDeckWatchCompanion.xcarchive"
