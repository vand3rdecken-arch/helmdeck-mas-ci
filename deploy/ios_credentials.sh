#!/usr/bin/env bash
# iOS signing for HelmDeck: hand EAS an App Store Connect API key, then let it
# create the Distribution Certificate + Provisioning Profile. There is no Xcode
# and no macOS on this box, so the signing assets live on EAS' servers, never in
# this repo.
#
#   bash deploy/ios_credentials.sh              # FIRST RUN - needs a real terminal
#   bash deploy/ios_credentials.sh --profile internal
#   bash deploy/ios_credentials.sh --check      # preflight only, changes nothing
#   bash deploy/ios_credentials.sh --build      # non-interactive build (agent-safe)
#
# ---------------------------------------------------------------------------
# Why the first run needs a terminal, and why that is NOT a 2FA prompt
# ---------------------------------------------------------------------------
# Verified against eas-cli's own source, not the docs (the docs are silent on it):
#
#   credentials/ios/appstore/AppStoreApi.js
#     defaultAuthenticationMode = hasAscEnvVars() ? API_KEY : USER
#
# So the moment EXPO_ASC_API_KEY_PATH / EXPO_ASC_KEY_ID / EXPO_ASC_ISSUER_ID are
# set, EVERY App Store operation authenticates with a JWT minted from the .p8 -
# createDistributionCertificateAsync, createProvisioningProfileAsync,
# createOrReuseAdhocProvisioningProfileAsync and ensureBundleIdExistsAsync all go
# through ensureAuthenticatedAsync() and therefore through the key. credentials/
# context.js additionally SKIPS the "Do you want to log in to your Apple account?"
# prompt outright in API_KEY mode. No Apple ID, no 2FA, no cookie session.
#
# But a first run still cannot be --non-interactive:
#
#   credentials/ios/actions/SetUpDistributionCertificate.js runNonInteractiveAsync
#     if (!currentCertificate) throw new MissingCredentialsNonInteractiveError()
#
# Non-interactive mode REUSES an existing certificate; it refuses to mint the
# first one. Hence: one terminal run to create the assets, and every later build
# (--build below) is unattended and can run from an agent card.
#
# TERMINAL means cmd.exe / Windows Terminal, NOT Git Bash. MinTTY carries stdin
# over named pipes, so node sees no TTY and eas-cli dies with "Input is required,
# but stdin is not readable" at its first Y/n prompt - identical to the error you
# get from </dev/null, and piping `y` in does not fix it. Launch it as:
#   "C:\Program Files\Git\bin\bash.exe" -lc "cd /c/... && bash deploy/ios_credentials.sh"
#
# FIRST RUN ONLY - the capability sync will fail on PUSH_NOTIFICATIONS (Apple
# rejects eas-cli's patch payload). Do NOT reach for EXPO_NO_CAPABILITY_SYNC=1:
# that hides the mismatch instead of fixing it. Tick "Push Notifications" on the
# App ID at developer.apple.com -> Identifiers -> app.helmdeck, save, re-run.
#
# ---------------------------------------------------------------------------
# The two things that still demand a human Apple ID + 2FA
# ---------------------------------------------------------------------------
# AppStoreApi.js routes these through ensureUserAuthenticatedAsync(), which hard-
# forces USER mode and ignores the API key:
#   * ASC API key management itself (list/create/revokeAscApiKeyAsync) - which is
#     exactly why the .p8 must be born by hand in App Store Connect. EAS cannot
#     bootstrap its own key.
#   * Push notification keys (listPushKeysAsync, ...). HelmDeck ships
#     expo-notifications, so the day iOS push is wanted, that step needs a real
#     Apple login. It is NOT needed for a distribution cert or a build.
#
# ---------------------------------------------------------------------------
# One-time setup by the owner
# ---------------------------------------------------------------------------
# (Already done on this box on 2026-08-14 - see DEPLOY.md 2b for the live values.
#  Repeat this only when the key is rotated or the certificate expires.)
# 1. App Store Connect -> Users and Access -> Integrations -> Keys -> "+",
#    role *Admin* (App Manager is not enough for certificate creation, and a
#    Developer-role key cannot create certificates or profiles at all). The role
#    is FIXED at creation - a wrong role means a new key, never an edit.
# 2. Download the .p8. Apple serves it EXACTLY ONCE - there is no re-download.
#    Store it OUTSIDE this repo; this script refuses to run if it sits inside.
# 3. Note the Key ID and the Issuer ID from that same page.
# 4. Put all three in .env (git-ignored, never committed). Write it with a plain
#    editor: PowerShell's `Set-Content -Encoding UTF8` prepends a BOM and bash
#    then chokes on line 1 (`Add-Content` onto an existing file does not).
#      ASC_API_KEY_PATH=C:/hd/secrets/AuthKey_XXXXXXXXXX.p8
#      ASC_KEY_ID=XXXXXXXXXX
#      ASC_ISSUER_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# 5. Optional but recommended - otherwise the run stops on two prompts that the
#    API key cannot answer for you (resolveCredentials.js reads both from env):
#      APPLE_TEAM_ID=XXXXXXXXXX          # developer.apple.com -> Membership details
#      APPLE_TEAM_TYPE=INDIVIDUAL        # or COMPANY_OR_ORGANIZATION / IN_HOUSE
# 6. bash deploy/ios_credentials.sh
set -o pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
[ -f .env ] && set -a && . ./.env && set +a
export PATH="/c/Program Files/nodejs:$PATH"

PROFILE="production"; MODE="setup"
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) PROFILE="${2:?--profile needs a name}"; shift ;;
    --check)   MODE="check" ;;
    --build)   MODE="build" ;;
    -h|--help) sed -n '2,60p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
  shift
done

# Accept either the short names from .env or the EXPO_* names already exported.
KEY_PATH="${ASC_API_KEY_PATH:-${EXPO_ASC_API_KEY_PATH:-}}"
KEY_ID="${ASC_KEY_ID:-${EXPO_ASC_KEY_ID:-}}"
ISSUER_ID="${ASC_ISSUER_ID:-${EXPO_ASC_ISSUER_ID:-}}"
TEAM_ID="${APPLE_TEAM_ID:-${EXPO_APPLE_TEAM_ID:-}}"
TEAM_TYPE="${APPLE_TEAM_TYPE:-${EXPO_APPLE_TEAM_TYPE:-}}"

fail() { echo "!!! $*" >&2; exit 1; }

# --- preflight -------------------------------------------------------------
# hasAscEnvVars() in eas-cli fires if ANY ONE of the three is set, which flips
# auth to API_KEY mode and then dies confusingly on the missing rest. So demand
# all three up front rather than letting eas-cli half-arm itself.
[ -n "$KEY_PATH" ]  || fail "ASC_API_KEY_PATH not set - see the header of this script (.env)"
[ -n "$KEY_ID" ]    || fail "ASC_KEY_ID not set - see the header of this script (.env)"
[ -n "$ISSUER_ID" ] || fail "ASC_ISSUER_ID not set - see the header of this script (.env)"
[ -f "$KEY_PATH" ]  || fail "no .p8 at $KEY_PATH"

# The .p8 is a secret on the level of the Android keystore, and Apple hands it
# out exactly once. Keeping it under the repo is one `git add -A` away from
# publishing it, so refuse outright instead of trusting .gitignore.
KEY_ABS="$(cd "$(dirname "$KEY_PATH")" && pwd)/$(basename "$KEY_PATH")"
case "$KEY_ABS" in
  "$ROOT"/*) fail "the .p8 sits INSIDE the repo ($KEY_ABS) - move it out, e.g. C:/hd/secrets/" ;;
esac

# Worktrees never get their own install; without node_modules every eas command
# dies with "Failed to resolve plugin for module expo-router".
[ -d app/node_modules ] || fail "app/node_modules missing - junction it first (see docs/shots/link.py)"

grep -q "\"$PROFILE\"" app/eas.json || fail "profile '$PROFILE' is not in app/eas.json"

export EXPO_ASC_API_KEY_PATH="$KEY_ABS"
export EXPO_ASC_KEY_ID="$KEY_ID"
export EXPO_ASC_ISSUER_ID="$ISSUER_ID"

# The API key authenticates, but it does NOT tell eas-cli which Apple team to act
# as - resolveAppleTeamAsync() prompts for both unless these are set. Validate the
# team type here: eas-cli only asserts it deep inside the run, after the network
# calls, so a typo would otherwise surface minutes later.
if [ -n "$TEAM_TYPE" ]; then
  case "$TEAM_TYPE" in
    IN_HOUSE|COMPANY_OR_ORGANIZATION|INDIVIDUAL) export EXPO_APPLE_TEAM_TYPE="$TEAM_TYPE" ;;
    *) fail "APPLE_TEAM_TYPE='$TEAM_TYPE' invalid - must be IN_HOUSE, COMPANY_OR_ORGANIZATION or INDIVIDUAL" ;;
  esac
fi
[ -n "$TEAM_ID" ] && export EXPO_APPLE_TEAM_ID="$TEAM_ID"
if [ -z "$TEAM_ID" ] || [ -z "$TEAM_TYPE" ]; then
  echo "--- APPLE_TEAM_ID/APPLE_TEAM_TYPE not both set: expect a prompt for the"
  echo "--- missing one. That prompt is NOT an Apple login and needs no 2FA."
fi

echo "==> EAS account"
( cd app && npx --yes eas-cli@latest whoami ) || fail "not logged in - run: npx eas-cli login"
echo "==> ASC API key ${KEY_ID} (issuer ${ISSUER_ID}) from ${KEY_ABS}"
echo "==> apple team: ${TEAM_ID:-<prompt>} / ${TEAM_TYPE:-<prompt>}"
echo "==> profile: $PROFILE"

if [ "$MODE" = "check" ]; then
  echo "==> preflight OK - nothing was changed"
  exit 0
fi

if [ "$MODE" = "build" ]; then
  # Safe for an agent card: with the key exported this needs no TTY. It FAILS
  # loudly with MissingCredentialsNonInteractiveError if the setup run below has
  # never happened - that error means "run this script without --build first",
  # not "log in to Apple".
  echo "==> non-interactive iOS build"
  ( cd app && npx --yes eas-cli@latest build --platform ios --profile "$PROFILE" --non-interactive )
  exit $?
fi

# --- first run: create the signing assets ----------------------------------
echo "==> setting up iOS build credentials (no Apple ID prompt in API_KEY mode)"
( cd app && npx --yes eas-cli@latest credentials:configure-build --platform ios --profile "$PROFILE" ) || exit 1

cat <<'DONE'

==> now VERIFY, do not assume:
      npx eas-cli credentials -p ios      # must list a Distribution Certificate
                                          # AND a Provisioning Profile, with expiry
      bash deploy/ios_credentials.sh --build
    The --build run is the real proof: it is the unattended path an agent card
    will take. If it reports MissingCredentialsNonInteractiveError, the setup
    above did not actually persist the certificate.

    A `production` profile needs no device UDIDs. An `internal` (ad-hoc) build
    installs only on devices registered with `npx eas-cli device:create`.
DONE
