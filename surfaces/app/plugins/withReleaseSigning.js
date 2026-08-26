// Re-apply the release-signing keystore into the hand-managed android/
// project. Same contract as withLanCleartext/withGlassVoice/withUpdateUrl:
// surfaces/app/android is git-ignored, so every source-of-truth native value
// must be re-stamped before each build - but this one was MISSED when
// `expo prebuild --clean` was added to build_apk.sh (2026-08-26, the icon
// pipeline fix): prebuild regenerates build.gradle's signingConfigs from
// scratch, which had been hand-edited at some earlier point to sign release
// builds with daemon/certs/apk-signing/swarmdeck-release.jks - a change that
// lived ONLY in the git-ignored android/ tree with no script anywhere to
// reproduce it. Once prebuild started actually running, every build fell
// back to signingConfigs.debug for the release build type too (RN's
// template default), producing an APK signed with a DIFFERENT certificate
// than every previously-installed one - Android refuses to install it
// ("Die App wurde nicht installiert, da das Paket in Konflikt mit einem
// bestehenden Paket steht" / INSTALL_FAILED_UPDATE_INCOMPATIBLE), and the
// only fix on an already-installed phone is a full uninstall.
//
// Usage: node app/plugins/withReleaseSigning.js surfaces/app/android
const fs = require("fs");
const path = require("path");

const androidDir = process.argv[2];
if (!androidDir) { console.error("usage: withReleaseSigning.js <androidDir>"); process.exit(1); }

const keystoreSrcDir = path.join(__dirname, "..", "..", "..", "daemon", "certs", "apk-signing");
const propsPath = path.join(keystoreSrcDir, "keystore.properties");
if (!fs.existsSync(propsPath)) {
  console.error(`[withReleaseSigning] no ${propsPath} - refusing to build unsigned/debug-signed`);
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
  console.error(`[withReleaseSigning] keystore.properties points at ${jksSrc}, which doesn't exist`);
  process.exit(1);
}

const appDir = path.join(androidDir, "app");
fs.copyFileSync(jksSrc, path.join(appDir, "release.keystore"));
fs.writeFileSync(
  path.join(appDir, "keystore.properties"),
  `storeFile=release.keystore\nstorePassword=${props.storePassword}\nkeyAlias=${props.keyAlias}\nkeyPassword=${props.keyPassword}\n`,
);

const gradlePath = path.join(appDir, "build.gradle");
let gradle = fs.readFileSync(gradlePath, "utf8");

const LOADER = `def releaseSigningProps = new Properties()\n` +
  `def releaseSigningPropsFile = file('keystore.properties')\n` +
  `if (releaseSigningPropsFile.exists()) {\n` +
  `    releaseSigningProps.load(new FileInputStream(releaseSigningPropsFile))\n` +
  `}\n`;
if (!gradle.includes("releaseSigningProps")) {
  gradle = gradle.replace(/(\napply plugin:[^\n]*\n)/, `$1\n${LOADER}`);
}

const RELEASE_CONFIG =
  `        release {\n` +
  `            storeFile file(releaseSigningProps.getProperty('storeFile', 'release.keystore'))\n` +
  `            storePassword releaseSigningProps.getProperty('storePassword')\n` +
  `            keyAlias releaseSigningProps.getProperty('keyAlias')\n` +
  `            keyPassword releaseSigningProps.getProperty('keyPassword')\n` +
  `        }\n`;
if (!/signingConfigs\s*\{[^}]*release\s*\{/s.test(gradle)) {
  gradle = gradle.replace(
    /(signingConfigs\s*\{\n)/,
    `$1${RELEASE_CONFIG}`,
  );
}

// Anchored to buildTypes so this can't touch signingConfigs.release's OWN
// block above, and non-greedy + dotall so it skips past comment lines
// (the RN template has two between "release {" and "signingConfig") without
// also skipping past buildTypes.debug's own "signingConfig signingConfigs.
// debug" line, which must NOT change.
const alreadyApplied = /buildTypes\s*\{[\s\S]*?release\s*\{[\s\S]*?signingConfig signingConfigs\.release/.test(gradle);
const buildTypesMatch = alreadyApplied ? null : gradle.match(
  /buildTypes\s*\{[\s\S]*?release\s*\{[\s\S]*?signingConfig signingConfigs\.debug/,
);
if (!alreadyApplied && !buildTypesMatch) {
  console.error("[withReleaseSigning] could not find buildTypes.release's signingConfig line - refusing to build blind");
  process.exit(1);
}
if (buildTypesMatch) gradle = gradle.replace(buildTypesMatch[0], buildTypesMatch[0].replace(
  /signingConfig signingConfigs\.debug$/, "signingConfig signingConfigs.release",
));

fs.writeFileSync(gradlePath, gradle);
console.log("[withReleaseSigning] release build type signed with daemon/certs/apk-signing/" + props.storeFile);
