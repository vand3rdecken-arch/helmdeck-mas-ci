// Re-apply the OTA update URL + pairing deep-link host from app.json into the
// hand-managed android/ project. Same contract as withLanCleartext/
// withGlassVoice: surfaces/app/android is git-ignored, `expo prebuild` never runs, so
// every source-of-truth native value MUST be re-stamped before each build.
//
// This one exists because it was missed: the relay cutover (7331736) changed
// app.json's updates.url to relay.helmdeck.de, but the generated manifest kept
// the dead Oracle VM (141.144.227.105.sslip.io). Builds 48 and the first 49
// shipped phoning a server that will never answer - every OTA check timed out
// and the phone stayed on its embedded bundle forever ("kein OTA"), proven in
// emulator logcat (UpdateFailedToLoad, connect timeout). An OTA can never fix
// a wrong OTA URL, so this class is APK-rebuild-only - which is exactly why it
// must be impossible to build with a stale one.
//
// Usage: node app/plugins/withUpdateUrl.js surfaces/app/android
const fs = require("fs");
const path = require("path");

const androidDir = process.argv[2];
if (!androidDir) { console.error("usage: withUpdateUrl.js <androidDir>"); process.exit(1); }

const appJson = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "app.json"), "utf8"));
const url = appJson.expo?.updates?.url;
if (!url) { console.error("[withUpdateUrl] no expo.updates.url in app.json"); process.exit(1); }
const host = new URL(url).host;

const manifest = path.join(androidDir, "app", "src", "main", "AndroidManifest.xml");
const before = fs.readFileSync(manifest, "utf8");
let after = before.replace(
  /(<meta-data android:name="expo\.modules\.updates\.EXPO_UPDATE_URL" android:value=")[^"]*(")/,
  `$1${url}$2`,
);
// The /pair deep link must live on the same relay host - a stale host here
// makes pairing links from the desktop open the browser instead of the app.
after = after.replace(
  /(<data android:scheme="https" android:host=")[^"]*(" android:pathPrefix="\/pair"\/>)/,
  `$1${host}$2`,
);
if (!after.includes(`android:value="${url}"`)) {
  console.error("[withUpdateUrl] EXPO_UPDATE_URL meta-data not found in manifest - refusing to build blind");
  process.exit(1);
}
if (after !== before) {
  fs.writeFileSync(manifest, after);
  console.log(`[withUpdateUrl] manifest re-stamped: ${url} (pair host ${host})`);
} else {
  console.log(`[withUpdateUrl] manifest already current: ${url}`);
}
