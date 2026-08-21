// Native config for GLASS VOICE: talking to the board agent through the
// glasses' own microphone.
//
// WHY THIS IS PLAIN ANDROID AND NOT THE META SDK - the finding that decides the
// whole design, adversarially verified 3-0 in glass-crud-harness/docs/
// android-dat-research.md (finding 2) and re-confirmed 2026-08-17:
//
//     Mic: Bluetooth HFP, 8 kHz mono only, routed with standard Android 12+
//     APIs (setCommunicationDevice(TYPE_BLUETOOTH_SCO) + MODE_IN_COMMUNICATION)
//     - NOT a DAT API. 5-mic beamforming happens on-device.
//
// So the Ray-Ban Display mic is an ordinary Bluetooth headset mic. mwdat-core
// contains zero audio classes and Meta ships no audio artifact at all - the SDK
// is for camera and lens-display only. Nothing here needs the DAT, a GitHub
// PAT, or any Meta approval.
//
// THE LISTEN/SPEAK CONFLICT, and why it is a permission-level concern:
// HFP and A2DP are mutually exclusive (same research, finding 3) - while the
// mic is open, ALL glasses audio drops to telephone quality. The loop must be
// listen -> STOP listening -> then speak the answer. That is enforced in the
// runtime code, but it is written here too because it is the reason this app
// asks for MODIFY_AUDIO_SETTINGS: it has to actively tear the SCO route down,
// not merely stop reading from it.
//
// ANDROID 14 TYPED FOREGROUND SERVICES - a trap already paid for in the
// reference project (glasses-reference.md 3.4). There, commit a722c49 SHRANK
// the FGS type set to dodge a crash when mic/camera were ungranted, and 2edb739
// reversed it on the owner's instruction, permanently annotated "don't reduce
// it". The documented rule is: either grant everything before Start, or declare
// narrowly - PICK ONE AND WRITE IT DOWN. This plugin picks NARROW on purpose:
// HelmDeck's voice service needs the microphone and nothing else, so it
// declares exactly `microphone` and the app must hold RECORD_AUDIO before
// starting it. A broad type set here would re-import a crash class we have no
// use for, because unlike that project we never capture camera or location in
// this service.
//
// BOTH PLATFORMS, and they are NOT the same shape:
//   - Android has a hand-managed app/android, so it needs TWO paths kept in
//     sync: the prebuild plugin, and a bare-node CLI that build_apk.sh runs.
//   - iOS has no hand-managed app/ios - EAS prebuilds from app.json - so the
//     plugin path is the only one, and there is nothing to keep in sync.
// Same file for both, exactly like withLanCleartext.js:
//   - `expo prebuild` / EAS: normal config plugin (registered in app.json)
//   - hand-managed app/android: `node app/plugins/withGlassVoice.js app/android`.
//     Idempotent. That CLI is ANDROID-ONLY by nature - iOS has no such dir.

const PERMISSIONS = [
  // the microphone itself
  "android.permission.RECORD_AUDIO",
  // tearing the SCO route up and down (the listen/speak switch above)
  "android.permission.MODIFY_AUDIO_SETTINGS",
  // Android 12+: talking to an already-PAIRED device. Deliberately NOT
  // BLUETOOTH_SCAN/ADVERTISE - the glasses are paired by the Meta AI app long
  // before HelmDeck is involved, so we never discover, only connect.
  "android.permission.BLUETOOTH_CONNECT",
  // the capture keeps running while the owner looks at the lens rather than the
  // phone, which is the entire point of a head-worn surface
  "android.permission.FOREGROUND_SERVICE",
  "android.permission.FOREGROUND_SERVICE_MICROPHONE",
];

const SERVICE_NAME = "app.helmdeck.voice.GlassVoiceService";
const FGS_TYPE = "microphone"; // NARROW - see the header

// PACKAGE VISIBILITY - the line that decides whether the phone can hear at all.
//
// Android 11 (API 30) hid other packages from an app by default, and
// SpeechRecognizer is IMPLEMENTED BY ANOTHER APP (normally the Google app). With
// no <queries> declaration the recognizer is simply invisible: the APK builds
// clean, RECORD_AUDIO is granted, and `SpeechRecognizer.isRecognitionAvailable()`
// returns false forever. That is the worst failure shape there is - correct code,
// correct permission, silent dead microphone, on device only.
//
// WHY THIS LIVES HERE AND NOT IN expo-speech-recognition's OWN PLUGIN. That
// package ships an app.plugin.js which adds exactly this. We deliberately do NOT
// register it, for two reasons:
//   1. It only runs on the `expo prebuild` path. HelmDeck's app/android is
//      HAND-MANAGED (DEPLOY.md) and regenerates from nothing, so every native
//      fact has to be re-applied by a CLI at build time - which that plugin has
//      no half for. Registering it would make the managed and hand-managed
//      builds disagree, and only the phone would ever find out.
//   2. It sets NSMicrophoneUsageDescription / NSSpeechRecognitionUsageDescription
//      to English Apple-boilerplate defaults at config-resolution time, which is
//      BEFORE this plugin's withInfoPlist mod runs - so its `if (!c.modResults[k])`
//      guard would find the slots already filled and quietly keep the English
//      strings, replacing the German ones the owner sees at the permission prompt.
// One owner for the voice native config, both paths, no drift.
const QUERY_ACTION = "android.speech.RecognitionService";
// The Google app implements RecognitionService on essentially every Play device.
// The <intent> filter below is the general form; this named package is the belt
// to its braces, because a handful of OEM builds answer the explicit package
// query but not the intent one.
const QUERY_PACKAGE = "com.google.android.googlequicksearchbox";

// iOS. HelmDeck really does ship there (ASC app 6801637667, TestFlight), so an
// Android-only voice plugin is not "unfinished", it is BROKEN on half the
// product: iOS kills an app on first microphone access when
// NSMicrophoneUsageDescription is absent, and App Review rejects the build
// outright. These strings are user-facing at the permission prompt, so they are
// German like the camera one already in app.json.
//
// Deliberately NOT added: UIBackgroundModes:["audio"]. Voice here is a
// foreground conversation - claiming background audio invites App Review
// scrutiny for a capability nothing uses, and it is the kind of entitlement
// that is easy to add and painful to justify later.
const IOS_INFO = {
  NSMicrophoneUsageDescription:
    "HelmDeck nutzt das Mikrofon, damit du mit Henry sprechen kannst - " +
    "auch über das Mikrofon deiner Brille.",
  NSSpeechRecognitionUsageDescription:
    "HelmDeck wandelt deine Sprache in Text um, um deine Frage an Henry zu " +
    "schicken.",
};

function serviceXml() {
  return (
    `        <service\n` +
    `            android:name="${SERVICE_NAME}"\n` +
    `            android:exported="false"\n` +
    `            android:foregroundServiceType="${FGS_TYPE}" />\n`
  );
}

function queryEntriesXml() {
  return (
    `    <package android:name="${QUERY_PACKAGE}" />\n` +
    `    <intent>\n` +
    `      <action android:name="${QUERY_ACTION}" />\n` +
    `    </intent>`
  );
}

function queriesXml() {
  return `  <queries>\n${queryEntriesXml()}\n  </queries>\n`;
}

// --- expo prebuild path -----------------------------------------------------
function withGlassVoice(config) {
  const { withAndroidManifest, withInfoPlist } = require("expo/config-plugins");

  // iOS first. There is no hand-managed app/ios (EAS prebuilds from app.json),
  // so unlike Android this is the ONLY path - there is no second CLI half to
  // keep in sync.
  config = withInfoPlist(config, (c) => {
    for (const [k, v] of Object.entries(IOS_INFO)) {
      if (!c.modResults[k]) c.modResults[k] = v;
    }
    return c;
  });

  return withAndroidManifest(config, (c) => {
    const manifest = c.modResults.manifest;
    manifest["uses-permission"] = manifest["uses-permission"] || [];
    for (const name of PERMISSIONS) {
      const has = manifest["uses-permission"].some(
        (p) => p.$ && p.$["android:name"] === name
      );
      if (!has) manifest["uses-permission"].push({ $: { "android:name": name } });
    }
    // package visibility for the speech recogniser (see QUERY_ACTION above).
    // MERGED INTO the existing <queries> rather than appended as a second one:
    // this app already declares a <queries> for the https VIEW intent, and
    // <queries> is a once-per-manifest element. Two of them may well survive the
    // merger, but "may well" is not a thing to find out from a phone.
    manifest.queries = manifest.queries || [];
    if (!JSON.stringify(manifest.queries).includes(QUERY_ACTION)) {
      if (!manifest.queries.length) manifest.queries.push({});
      const q = manifest.queries[0];
      q.package = q.package || [];
      if (!q.package.some((p) => p.$ && p.$["android:name"] === QUERY_PACKAGE)) {
        q.package.push({ $: { "android:name": QUERY_PACKAGE } });
      }
      q.intent = q.intent || [];
      q.intent.push({ action: [{ $: { "android:name": QUERY_ACTION } }] });
    }
    const app = (manifest.application || [])[0];
    if (app) {
      app.service = app.service || [];
      const has = app.service.some(
        (s) => s.$ && s.$["android:name"] === SERVICE_NAME
      );
      if (!has) {
        app.service.push({
          $: {
            "android:name": SERVICE_NAME,
            "android:exported": "false",
            "android:foregroundServiceType": FGS_TYPE,
          },
        });
      }
    }
    return c;
  });
}

// --- hand-managed android/ path (deploy/build_apk.sh) -----------------------
function patchManifestXml(xml) {
  let out = xml;
  for (const name of PERMISSIONS) {
    if (!out.includes(`android:name="${name}"`)) {
      out = out.replace(
        /(<manifest\b[^>]*>)/,
        `$1\n    <uses-permission android:name="${name}" />`
      );
    }
  }
  if (!out.includes(SERVICE_NAME)) {
    // insert before </application>, the only place a <service> may live
    out = out.replace(/([ \t]*)<\/application>/, `${serviceXml()}$1</application>`);
  }
  if (!out.includes(QUERY_ACTION)) {
    // <queries> is a MANIFEST-level element - a sibling of <application>, not a
    // child - and it may appear only ONCE. This tree already ships one (the
    // https VIEW intent from expo-web-browser), so extend that block when it is
    // there and only create one when it is not.
    out = /<queries>/.test(out)
      ? out.replace("<queries>", `<queries>\n${queryEntriesXml()}`)
      : out.replace(/([ \t]*)<\/manifest>/, `${queriesXml()}$1</manifest>`);
  }
  return out;
}

// The service SOURCE lives beside this plugin as a real .kt file (readable,
// reviewable, diffable) and is COPIED into the git-ignored android tree. Same
// rule as the manifest: app/android is hand-managed and regenerates from
// nothing, so anything that must survive a rebuild has to be re-applied from a
// tracked source. Keeping it as .kt rather than a string inside this JS is the
// difference between code you can review and code you can only hope about.
const KOTLIN_SRC = "glassvoice/GlassVoiceService.kt";
const KOTLIN_DST = ["app", "src", "main", "java", "app", "helmdeck", "voice",
                    "GlassVoiceService.kt"];

function installKotlin(androidDir) {
  const fs = require("fs");
  const path = require("path");
  const src = path.join(__dirname, KOTLIN_SRC);
  const dst = path.join(androidDir, ...KOTLIN_DST);
  const code = fs.readFileSync(src, "utf8");
  const had = fs.existsSync(dst) ? fs.readFileSync(dst, "utf8") : null;
  if (had === code) return false;
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.writeFileSync(dst, code);
  return true;
}

function applyToAndroidDir(androidDir) {
  const fs = require("fs");
  const path = require("path");
  const manifest = path.join(androidDir, "app", "src", "main", "AndroidManifest.xml");
  const before = fs.readFileSync(manifest, "utf8");
  const after = patchManifestXml(before);
  if (after !== before) fs.writeFileSync(manifest, after);
  const wroteKotlin = installKotlin(androidDir);
  return { changed: after !== before, wroteKotlin,
           permissions: PERMISSIONS, service: SERVICE_NAME };
}

module.exports = withGlassVoice;
module.exports.PERMISSIONS = PERMISSIONS;
module.exports.IOS_INFO = IOS_INFO;
module.exports.SERVICE_NAME = SERVICE_NAME;
module.exports.FGS_TYPE = FGS_TYPE;
module.exports.QUERY_ACTION = QUERY_ACTION;
module.exports.QUERY_PACKAGE = QUERY_PACKAGE;
module.exports.patchManifestXml = patchManifestXml;
module.exports.applyToAndroidDir = applyToAndroidDir;

if (require.main === module) {
  const target = process.argv[2];
  if (!target) {
    console.error("usage: node app/plugins/withGlassVoice.js <path-to-android-dir>");
    process.exit(2);
  }
  const r = applyToAndroidDir(target);
  console.log(
    `[withGlassVoice] ${r.permissions.length} permissions + ${r.service} ` +
      `(FGS type: ${FGS_TYPE}) + <queries> ${QUERY_ACTION}` +
      (r.wroteKotlin ? " + service source installed" : "") +
      (r.changed ? " - manifest patched" : " - manifest already ok")
  );
}
