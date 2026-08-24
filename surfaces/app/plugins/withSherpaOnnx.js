// Native wiring for the ON-DEVICE STT option (sherpa-onnx) - the runtime half.
//
// WHY TWO HALVES (see surfaces/app/modules/livemic/android/build.gradle for the other):
// AGP forbids a local .aar inside a LIBRARY module, so livemic compiles against
// an extracted classes.jar (compileOnly, nothing bundled) and the APP module
// must carry the full AAR - classes plus the onnxruntime JNI libs. surfaces/app/android
// is git-ignored and hand-managed (DEPLOY.md), so exactly like withMetaDat.js
// this file is the one owner that re-applies that fact before every build:
// download the pinned release AAR into surfaces/app/android/app/libs and add the
// dependency line. Without it the APK builds green and `initLocalStt` throws
// NoClassDefFoundError at runtime - the silent-wrong-artifact class again.
//
// No expo-prebuild half on purpose: the module guards every sherpa reference
// in try/catch(Throwable), so an EAS/iOS build without this wiring degrades to
// "device STT unavailable" instead of crashing - and iOS has no sherpa AAR.

const SHERPA_VERSION = "1.13.6";
const AAR_NAME = `sherpa-onnx-${SHERPA_VERSION}.aar`;
const AAR_URL = `https://github.com/k2-fsa/sherpa-onnx/releases/download/v${SHERPA_VERSION}/${AAR_NAME}`;
const DEP_MARK = "// HelmDeck: sherpa-onnx (withSherpaOnnx.js)";
const DEP_LINE = `    ${DEP_MARK}\n    implementation files('libs/${AAR_NAME}')\n`;

async function download(url, dst) {
  const fs = require("fs");
  const followFetch = async (u, depth) => {
    if (depth > 5) throw new Error("too many redirects");
    const res = await fetch(u, { redirect: "follow" });
    if (!res.ok) throw new Error(`HTTP ${res.status} for ${u}`);
    return Buffer.from(await res.arrayBuffer());
  };
  const buf = await followFetch(url, 0);
  fs.writeFileSync(dst, buf);
  return buf.length;
}

async function applyToAndroidDir(androidDir) {
  const fs = require("fs");
  const path = require("path");
  const libs = path.join(androidDir, "app", "libs");
  fs.mkdirSync(libs, { recursive: true });
  const aar = path.join(libs, AAR_NAME);
  let downloaded = 0;
  if (!fs.existsSync(aar) || fs.statSync(aar).size === 0) {
    downloaded = await download(AAR_URL, aar);
  }
  const gradlePath = path.join(androidDir, "app", "build.gradle");
  const before = fs.readFileSync(gradlePath, "utf8");
  let after = before;
  if (!after.includes(DEP_MARK)) {
    // same insertion point as withMetaDat: right after `dependencies {`.
    // \r?\n, not \n: the hand-managed tree is CRLF on this box, and the
    // strict form silently failed to match (measured 2026-08-23).
    after = after.replace(/dependencies\s*\{\r?\n/, (m) => m + DEP_LINE);
    if (!after.includes(DEP_MARK)) {
      throw new Error("[withSherpaOnnx] could not find dependencies block in app/build.gradle");
    }
    fs.writeFileSync(gradlePath, after);
  }
  return { aar: AAR_NAME, downloaded, patched: after !== before };
}

module.exports = { applyToAndroidDir, SHERPA_VERSION, AAR_NAME, AAR_URL };

if (require.main === module) {
  const target = process.argv[2];
  if (!target) {
    console.error("usage: node app/plugins/withSherpaOnnx.js <path-to-android-dir>");
    process.exit(2);
  }
  applyToAndroidDir(target).then((r) => {
    console.log(`[withSherpaOnnx] ${r.aar}` +
      (r.downloaded ? ` downloaded (${(r.downloaded / 1e6).toFixed(1)} MB)` : " cached") +
      (r.patched ? " - build.gradle patched" : " - build.gradle already ok"));
  }).catch((e) => { console.error(String(e)); process.exit(1); });
}
