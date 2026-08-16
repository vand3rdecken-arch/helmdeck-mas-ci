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
// Serves BOTH build paths from one file, exactly like withLanCleartext.js:
//   - `expo prebuild`: normal config plugin (registered in app.json)
//   - hand-managed app/android (what deploy/build_apk.sh really builds):
//     `node app/plugins/withGlassVoice.js app/android`. Idempotent.

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

function serviceXml() {
  return (
    `        <service\n` +
    `            android:name="${SERVICE_NAME}"\n` +
    `            android:exported="false"\n` +
    `            android:foregroundServiceType="${FGS_TYPE}" />\n`
  );
}

// --- expo prebuild path -----------------------------------------------------
function withGlassVoice(config) {
  const { withAndroidManifest } = require("expo/config-plugins");
  return withAndroidManifest(config, (c) => {
    const manifest = c.modResults.manifest;
    manifest["uses-permission"] = manifest["uses-permission"] || [];
    for (const name of PERMISSIONS) {
      const has = manifest["uses-permission"].some(
        (p) => p.$ && p.$["android:name"] === name
      );
      if (!has) manifest["uses-permission"].push({ $: { "android:name": name } });
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
  return out;
}

function applyToAndroidDir(androidDir) {
  const fs = require("fs");
  const path = require("path");
  const manifest = path.join(androidDir, "app", "src", "main", "AndroidManifest.xml");
  const before = fs.readFileSync(manifest, "utf8");
  const after = patchManifestXml(before);
  if (after !== before) fs.writeFileSync(manifest, after);
  return { changed: after !== before, permissions: PERMISSIONS, service: SERVICE_NAME };
}

module.exports = withGlassVoice;
module.exports.PERMISSIONS = PERMISSIONS;
module.exports.SERVICE_NAME = SERVICE_NAME;
module.exports.FGS_TYPE = FGS_TYPE;
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
      `(FGS type: ${FGS_TYPE})` +
      (r.changed ? " - manifest patched" : " - manifest already ok")
  );
}
