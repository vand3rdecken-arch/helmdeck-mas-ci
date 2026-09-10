// Copy the PHONE MODULE's release keystore into the hand-managed
// android/wear/ tree before every build - same reason withReleaseSigning.js
// re-copies it into android/app/: android/ is git-ignored and regenerated
// from nothing, so a secret that lives only in daemon/certs/ must be
// re-placed every time this script runs.
//
// SAME keystore as the phone module, not a Wear-specific one - see
// surfaces/app/plugins/wear/build.gradle's header comment (2026-09-10 owner
// decision): :wear now shares the phone's applicationId "app.helmdeck" to
// extend the existing Play listing instead of publishing a separate one, and
// Play's upload flow verifies the upload signature against the certificate
// already registered for that app record - a different key would be
// rejected at upload time.
//
// UNLIKE withReleaseSigning.js, there is no Gradle text to patch here - the
// signingConfigs/buildTypes block already lives directly in the committed
// template (surfaces/app/plugins/wear/build.gradle, copied byte-for-byte by
// installWearModule() in withWearApp.js). This script only has to place the
// two secret files that template's loader expects to find next to it.
//
// Usage: node withWearReleaseSigning.js <androidDir>
const fs = require("fs");
const path = require("path");

const androidDir = process.argv[2];
if (!androidDir) { console.error("usage: withWearReleaseSigning.js <androidDir>"); process.exit(1); }

const keystoreSrcDir = path.join(__dirname, "..", "..", "..", "daemon", "certs", "apk-signing");
const propsPath = path.join(keystoreSrcDir, "keystore.properties");
if (!fs.existsSync(propsPath)) {
  console.error(`[withWearReleaseSigning] no ${propsPath} - refusing to build unsigned :wear`);
  process.exit(1);
}
const props = Object.fromEntries(
  fs.readFileSync(propsPath, "utf8")
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith("#"))
    .map((l) => l.split("=").map((s) => s.trim())),
);
const jksSrc = path.join(keystoreSrcDir, props.storeFile);
if (!fs.existsSync(jksSrc)) {
  console.error(`[withWearReleaseSigning] keystore.properties points at ${jksSrc}, which doesn't exist`);
  process.exit(1);
}

const wearDir = path.join(androidDir, "wear");
fs.mkdirSync(wearDir, { recursive: true });
fs.copyFileSync(jksSrc, path.join(wearDir, "release.keystore"));
fs.writeFileSync(
  path.join(wearDir, "keystore.properties"),
  `storeFile=release.keystore\nstorePassword=${props.storePassword}\nkeyAlias=${props.keyAlias}\nkeyPassword=${props.keyPassword}\n`,
);
console.log("[withWearReleaseSigning] :wear release build type signed with daemon/certs/apk-signing/" + props.storeFile);
