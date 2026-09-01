// Gradle wiring for the Meta Wearables Device Access Toolkit (DAT) — the
// GLASSES CAMERA. Same dual-path shape as withGlassVoice.js: an expo config
// plugin for `expo prebuild`/EAS, plus a bare-node CLI that ops/deploy/build_apk.sh
// runs against the HAND-MANAGED surfaces/app/android tree. One owner, both paths, no
// drift.
//
// ⚠ NOT REGISTERED IN app.json's `plugins` RIGHT NOW (2026-09-01). This file,
// GlassCameraService.kt and GlassesDevice.kt all still exist and still work -
// they were pulled from the build because `glasses.capture()`/`stopCamera()`
// (surfaces/app/src/data/glasses.ts) have NO caller anywhere in surfaces/app/src.
// The whole point of GlassCameraService is Play's FOREGROUND_SERVICE_CONNECTED_DEVICE
// declaration, and Google Play's foreground-service permission review requires a
// justification AND a demo video of the feature actually working - which cannot
// be done honestly for a capture path with no UI button. Re-add this plugin to
// app.json's `plugins` array the moment glasses.capture() gets a real screen
// (and the worker's /glance/photo route is on the allowlist - see glasses.ts's
// own comment), then re-run the prebuild permission check in
// ops/docs/store/DATA_SAFETY.md before the next Play submission.
//
// WHY THIS FILE EXISTS AT ALL — the fact that changed, measured 2026-08-21.
// ops/docs/glasses-reference.md §11.7 used to say the DAT artifacts were already in
// this box's Gradle cache and resolved offline with no token. That is DEAD:
// `com.meta.wearable` is gone from all 199 cached groups. So the dependency now
// has to be declared AND authenticated, which is what this adds. See §12.1.
//
// THE CREDENTIAL IS NOT A BLOCKER, and this is worth writing down because the
// obvious reading of Meta's docs sends you to mint a token you already have.
// Their integration page insists on "a personal access token (classic)". The
// token that was MEASURED resolving all four 0.9.0 artifacts (HTTP 200 on the
// POM and on every AAR) is the owner's ordinary `gh` CLI token — a `gho_` OAuth
// token, not a `ghp_` classic PAT — which already carries `read:packages`
// (DEPLOY.md:405). So the registry does not enforce "classic" for reads. At
// build time:
//
//     export GITHUB_TOKEN="$(gh auth token)"
//
// or put `github_token=…` in android/local.properties. NEVER commit it — that
// is why the credentials block below reads from the environment and from
// local.properties (which is git-ignored) and from nowhere else.
//
// VERSION PIN. 0.9.0, announced 2026-08-04. The repo publishes NO GitHub
// releases or tags — versions are announced only in Discussions, so the
// releases page reads as "there is no SDK". Do not conclude that. §12.2.
//
// WHAT IS DELIBERATELY NOT ADDED HERE:
//   - `mwdat-display`: the Ray-Ban DISPLAY lens is served by the surfaces/glasses/
//     webapp (GLASS MODE, §11), not by a native push. Adding the artifact would
//     buy nothing and cost APK size.
//   - `mwdat-mockdevice`: the Mock Device Kit does not cover Display glasses
//     (§3.1) and we have real hardware.
//   - android.permission.CAMERA: the frames come from the GLASSES over
//     Bluetooth, not from the phone's camera. DAT gates this with its own
//     Permission.CAMERA check (Wearables.checkPermissionStatus), which is a
//     Meta-side grant, not an Android manifest permission. The app already
//     declares CAMERA for expo-camera anyway; nothing here should widen it.

const MWDAT_VERSION = "0.9.0";
const MWDAT_GROUP = "com.meta.wearable";
// core = session/device lifecycle, camera = the stream + capturePhoto.
const MWDAT_ARTIFACTS = ["mwdat-core", "mwdat-camera"];
const MAVEN_URL =
  "https://maven.pkg.github.com/facebook/meta-wearables-dat-android";

// A marker comment so both paths can detect their own previous work and stay
// idempotent — the same trick withGlassVoice.js uses with SERVICE_NAME.
const MARKER = "HelmDeck: Meta DAT (withMetaDat.js)";

/** The Gradle `maven { … }` block, credentials read from env/local.properties. */
function mavenBlockKts() {
  return `
        // ${MARKER}
        maven {
            url = uri("${MAVEN_URL}")
            credentials {
                // Documented by Meta as literally empty; the token is the auth.
                username = ""
                password = System.getenv("GITHUB_TOKEN")
                    ?: extra.properties["github_token"]?.toString()
                    ?: ""
            }
        }`;
}

function mavenBlockGroovy() {
  return `
        // ${MARKER}
        maven {
            url = uri("${MAVEN_URL}")
            credentials {
                username = ""
                password = System.getenv("GITHUB_TOKEN") ?: (project.hasProperty('github_token') ? project.property('github_token') : '')
            }
        }`;
}

/**
 * Add the GitHub Packages repository to a settings.gradle[.kts].
 *
 * Repositories go in settings.gradle rather than the module's build.gradle
 * because the Expo template uses `dependencyResolutionManagement`, which by
 * default FAILS a build that declares project-level repositories. Putting it
 * anywhere else is the kind of thing that only fails on the build machine.
 *
 * Idempotent by MARKER, and a no-op (returns the input unchanged) when there is
 * no repositories block to extend — better to leave the file alone and let the
 * build fail loudly than to write a repositories block in the wrong scope.
 */
function patchSettingsGradle(text, isKts) {
  if (!text || text.includes(MARKER)) return text;
  if (!/dependencyResolutionManagement/.test(text)) return text;
  // The DIALECT IS PASSED IN, never sniffed from the body. A Groovy
  // `credentials` block and a Kotlin one differ in ways that do not fail at
  // parse time on the wrong dialect - they fail later, on the build machine,
  // which is the worst place to learn it. Callers know the filename; they say.
  const block = isKts ? mavenBlockKts() : mavenBlockGroovy();
  // Extend the FIRST repositories { } inside dependencyResolutionManagement.
  const idx = text.indexOf("dependencyResolutionManagement");
  if (idx < 0) return text;
  const repoIdx = text.indexOf("repositories", idx);
  if (repoIdx < 0) return text;
  const braceIdx = text.indexOf("{", repoIdx);
  if (braceIdx < 0) return text;
  return text.slice(0, braceIdx + 1) + block + text.slice(braceIdx + 1);
}

/**
 * Add the repository to the ROOT build.gradle's `allprojects { repositories }`.
 *
 * WHY BOTH THIS AND patchSettingsGradle EXIST - measured against the real tree
 * on 2026-08-21, and the first version of this plugin was WRONG because it only
 * had the other one. There are two template generations in the wild:
 *
 *   - NEWER: settings.gradle declares `dependencyResolutionManagement`, which by
 *     default FAILS any build that also declares project repositories. The repo
 *     must go there.
 *   - THIS APP (Expo 57 / RN 0.86, hand-managed android/): settings.gradle has
 *     NO dependencyResolutionManagement at all - it is pluginManagement plus
 *     expoAutolinking - and repositories live in the ROOT build.gradle under
 *     `allprojects { repositories { google(); mavenCentral(); jitpack } }`.
 *
 * The synthetic fixture in the test modelled only the first shape, so the
 * plugin reported "settings.gradle already ok" against the real tree and
 * silently added no repository - which would have surfaced much later as a
 * gradle "could not resolve com.meta.wearable:mwdat-core". The test now carries
 * a fixture copied from the REAL file so this cannot regress.
 *
 * Exactly ONE of the two is written, chosen by which the tree actually uses -
 * declaring the repo in both places is what triggers the
 * dependencyResolutionManagement failure this is trying to avoid.
 */
function patchRootGradle(text, isKts) {
  if (!text || text.includes(MARKER)) return text;
  const idx = text.indexOf("allprojects");
  if (idx < 0) return text;
  const repoIdx = text.indexOf("repositories", idx);
  if (repoIdx < 0) return text;
  const braceIdx = text.indexOf("{", repoIdx);
  if (braceIdx < 0) return text;
  const block = isKts ? mavenBlockKts() : mavenBlockGroovy();
  return text.slice(0, braceIdx + 1) + block + text.slice(braceIdx + 1);
}

/**
 * Add the DAT dependencies to an app/build.gradle[.kts].
 *
 * Only touches the LAST `dependencies {` block, which in both the Expo Groovy
 * template and a .kts variant is the app module's own. Idempotent by MARKER.
 */
function patchAppGradle(text) {
  if (!text || text.includes(MARKER)) return text;
  // Anchored on the `dependencies {` BLOCK OPENER, not on the bare word: the
  // Expo template's app/build.gradle mentions "dependencies" in comments and
  // inside other blocks, and lastIndexOf on the word could land in prose and
  // splice an implementation line into a comment.
  const m = [...text.matchAll(/(^|\n)\s*dependencies\s*\{/g)].pop();
  if (!m) return text;
  const braceIdx = text.indexOf("{", m.index);
  if (braceIdx < 0) return text;
  // `implementation("g:a:v")` is valid in BOTH Groovy and KTS, so unlike the
  // repositories block this needs no dialect switch.
  const lines = MWDAT_ARTIFACTS.map(
    (a) => `    implementation("${MWDAT_GROUP}:${a}:${MWDAT_VERSION}")`
  ).join("\n");
  const block = `\n    // ${MARKER}\n${lines}`;
  return text.slice(0, braceIdx + 1) + block + text.slice(braceIdx + 1);
}

// The camera SERVICE. Narrow FGS type on purpose, same reasoning as
// withGlassVoice.js picks `microphone`: this service holds a link to a
// CONNECTED DEVICE (the glasses) and never opens the phone's own camera, so
// `connectedDevice` is the honest type. Declaring `camera` here would claim a
// capability we do not use and drag in the Android 14 typed-FGS crash class
// (glasses-reference 3.4) for nothing.
// ⚠ THE MINSDK COLLISION - measured by an actual build on 2026-08-21, not
// predicted. BOTH mwdat-core and mwdat-camera 0.9.0 declare
// `<uses-sdk android:minSdkVersion="29">`, and this app is minSdk 24, so the
// manifest merger HARD-FAILS the build:
//
//     uses-sdk:minSdkVersion 24 cannot be smaller than version 29 declared in
//     library [com.meta.wearable:mwdat-camera:0.9.0]
//
// Two ways out, and the choice matters to every HelmDeck user, not just to
// glasses owners:
//
//   1. Raise the app's minSdk 24 -> 29. One line, and it DROPS every Android
//      7.0 / 7.1 / 8.0 / 8.1 / 9 device from the whole product - for a feature
//      most users will never touch. (The reference project glass-crud-harness
//      could do this freely: it was glasses-only and already shipped minSdk 29.
//      HelmDeck is a board app that also talks to glasses.)
//   2. tools:overrideLibrary + a HARD RUNTIME GUARD. Nobody loses the app; the
//      camera is simply unavailable below API 29.
//
// This takes (2). Android's own suggestion text warns the override "may lead to
// runtime failures", and that warning is exactly right IF you then call the
// library on an old device - so the guard is not optional decoration, it is the
// other half of this decision. GlassCameraService and GlassesDevice both refuse
// before touching a single DAT class below MIN_SDK, and ART only loads a class
// on first use, so an old device never resolves them.
const DAT_MIN_SDK = 29;
const OVERRIDE_LIBS = "com.meta.wearable.dat.core,com.meta.wearable.dat.camera";

const CAMERA_SERVICE = "app.helmdeck.glasses.GlassCameraService";
const CAMERA_FGS_TYPE = "connectedDevice";
const CAMERA_PERMISSIONS = [
  "android.permission.FOREGROUND_SERVICE",
  "android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE",
];

const KOTLIN_FILES = [
  ["metadat/GlassCameraService.kt",
   ["app", "src", "main", "java", "app", "helmdeck", "glasses", "GlassCameraService.kt"]],
  // Which glasses are attached and whether they have a LENS. Ships with the
  // camera plugin rather than the voice one because it needs DAT classes
  // (Wearables/Device) that only exist once mwdat-core is on the classpath -
  // putting it with the voice plugin would make the mic build depend on the
  // camera SDK, which is exactly backwards.
  ["metadat/GlassesDevice.kt",
   ["app", "src", "main", "java", "app", "helmdeck", "glasses", "GlassesDevice.kt"]],
];
// NB GlassesRadio.kt is installed by withGlassVoice.js, not here - one owner
// per file. This plugin only consumes it.

function installKotlin(androidDir) {
  const fs = require("fs");
  const path = require("path");
  let wrote = 0;
  for (const [rel, dstParts] of KOTLIN_FILES) {
    const src = path.join(__dirname, rel);
    const dst = path.join(androidDir, ...dstParts);
    const code = fs.readFileSync(src, "utf8");
    const had = fs.existsSync(dst) ? fs.readFileSync(dst, "utf8") : null;
    if (had === code) continue;
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.writeFileSync(dst, code);
    wrote++;
  }
  return wrote > 0;
}

/** Add the camera service + its FGS permissions to a raw AndroidManifest.xml. */
function patchManifestXml(xml) {
  let out = xml;
  // The uses-sdk override (see DAT_MIN_SDK above). Needs the tools namespace;
  // this app already declares it, but a regenerated manifest might not, so add
  // it rather than assume - a missing xmlns makes the attribute a silent no-op
  // and the build fails again with the same merger error.
  if (!out.includes('xmlns:tools=')) {
    out = out.replace(
      /(<manifest\b[^>]*?)(>)/,
      '$1 xmlns:tools="http://schemas.android.com/tools"$2'
    );
  }
  if (!out.includes("overrideLibrary")) {
    if (/<uses-sdk\b/.test(out)) {
      // Extend an existing uses-sdk rather than adding a second one.
      out = out.replace(
        /(<uses-sdk\b)([^>]*?)(\/?>)/,
        `$1$2 tools:overrideLibrary="${OVERRIDE_LIBS}"$3`
      );
    } else {
      out = out.replace(
        /(<manifest\b[^>]*>)/,
        `$1\n    <uses-sdk tools:overrideLibrary="${OVERRIDE_LIBS}" />`
      );
    }
  }
  for (const name of CAMERA_PERMISSIONS) {
    if (!out.includes(`android:name="${name}"`)) {
      out = out.replace(
        /(<manifest\b[^>]*>)/,
        `$1\n    <uses-permission android:name="${name}" />`
      );
    }
  }
  if (!out.includes(CAMERA_SERVICE)) {
    const svc =
      `        <service\n` +
      `            android:name="${CAMERA_SERVICE}"\n` +
      `            android:exported="false"\n` +
      `            android:foregroundServiceType="${CAMERA_FGS_TYPE}" />\n`;
    out = out.replace(/([ \t]*)<\/application>/, `${svc}$1</application>`);
  }
  return out;
}

// --- expo prebuild path -----------------------------------------------------
function withMetaDat(config) {
  const {
    withSettingsGradle,
    withAppBuildGradle,
    withAndroidManifest,
  } = require("expo/config-plugins");

  config = withAndroidManifest(config, (c) => {
    const manifest = c.modResults.manifest;
    // Same override as the CLI half (see DAT_MIN_SDK). The tools namespace is
    // an attribute on <manifest> itself in this representation.
    manifest.$ = manifest.$ || {};
    if (!manifest.$["xmlns:tools"]) {
      manifest.$["xmlns:tools"] = "http://schemas.android.com/tools";
    }
    manifest["uses-sdk"] = manifest["uses-sdk"] || [{ $: {} }];
    const usesSdk = manifest["uses-sdk"][0];
    usesSdk.$ = usesSdk.$ || {};
    usesSdk.$["tools:overrideLibrary"] = OVERRIDE_LIBS;
    manifest["uses-permission"] = manifest["uses-permission"] || [];
    for (const name of CAMERA_PERMISSIONS) {
      const has = manifest["uses-permission"].some(
        (p) => p.$ && p.$["android:name"] === name
      );
      if (!has) manifest["uses-permission"].push({ $: { "android:name": name } });
    }
    const app = (manifest.application || [])[0];
    if (app) {
      app.service = app.service || [];
      const has = app.service.some(
        (s) => s.$ && s.$["android:name"] === CAMERA_SERVICE
      );
      if (!has) {
        app.service.push({
          $: {
            "android:name": CAMERA_SERVICE,
            "android:exported": "false",
            "android:foregroundServiceType": CAMERA_FGS_TYPE,
          },
        });
      }
    }
    return c;
  });
  config = withSettingsGradle(config, (c) => {
    // expo reports the dialect as modResults.language ('groovy' | 'kt').
    c.modResults.contents = patchSettingsGradle(
      c.modResults.contents,
      c.modResults.language === "kt"
    );
    return c;
  });
  return withAppBuildGradle(config, (c) => {
    c.modResults.contents = patchAppGradle(c.modResults.contents);
    return c;
  });
}

// --- hand-managed android/ path (ops/deploy/build_apk.sh) -----------------------
function applyToAndroidDir(androidDir) {
  const fs = require("fs");
  const path = require("path");
  // EVERY key initialised, not just the ones the happy path assigns. The
  // manifest key used to be written only when it changed, so a no-change run
  // reported `undefined` rather than `false` - which reads as falsy in an `if`
  // and as a bug in a `=== false` check. A status object that is sometimes
  // missing a field is worse than one that is always complete.
  const out = { settings: false, rootGradle: false, repoPlaced: false,
                app: false, manifest: false, kotlin: false };
  // THE REPOSITORY GOES IN EXACTLY ONE PLACE - see patchRootGradle. Try the
  // settings.gradle form first (newer templates, where project repositories are
  // forbidden), and fall back to the root build.gradle's allprojects block only
  // when settings.gradle did not take it. `already` guards the idempotent case:
  // a second run changes nothing, and must NOT then decide the file "didn't
  // take it" and write the repo into the OTHER file as well.
  let placed = false;
  for (const name of ["settings.gradle", "settings.gradle.kts"]) {
    const p = path.join(androidDir, name);
    if (!fs.existsSync(p)) continue;
    const before = fs.readFileSync(p, "utf8");
    if (before.includes(MARKER)) { placed = true; break; }
    const after = patchSettingsGradle(before, name.endsWith(".kts"));
    if (after !== before) {
      fs.writeFileSync(p, after);
      out.settings = true;
      placed = true;
    }
    break;
  }
  if (!placed) {
    for (const name of ["build.gradle", "build.gradle.kts"]) {
      const p = path.join(androidDir, name);
      if (!fs.existsSync(p)) continue;
      const before = fs.readFileSync(p, "utf8");
      if (before.includes(MARKER)) { placed = true; break; }
      const after = patchRootGradle(before, name.endsWith(".kts"));
      if (after !== before) {
        fs.writeFileSync(p, after);
        out.rootGradle = true;
        placed = true;
      }
      break;
    }
  }
  // A tree where NEITHER shape matched would build until gradle cannot resolve
  // com.meta.wearable, which is a confusing place to learn it. Say so here.
  out.repoPlaced = placed;
  for (const name of ["build.gradle", "build.gradle.kts"]) {
    const p = path.join(androidDir, "app", name);
    if (!fs.existsSync(p)) continue;
    const before = fs.readFileSync(p, "utf8");
    const after = patchAppGradle(before);
    if (after !== before) {
      fs.writeFileSync(p, after);
      out.app = true;
    }
    break;
  }
  const manifest = path.join(androidDir, "app", "src", "main", "AndroidManifest.xml");
  if (fs.existsSync(manifest)) {
    const before = fs.readFileSync(manifest, "utf8");
    const after = patchManifestXml(before);
    if (after !== before) {
      fs.writeFileSync(manifest, after);
      out.manifest = true;
    }
  }
  out.kotlin = installKotlin(androidDir);
  return out;
}

module.exports = withMetaDat;
module.exports.MWDAT_VERSION = MWDAT_VERSION;
module.exports.MWDAT_ARTIFACTS = MWDAT_ARTIFACTS;
module.exports.MAVEN_URL = MAVEN_URL;
module.exports.MARKER = MARKER;
module.exports.DAT_MIN_SDK = DAT_MIN_SDK;
module.exports.OVERRIDE_LIBS = OVERRIDE_LIBS;
module.exports.CAMERA_SERVICE = CAMERA_SERVICE;
module.exports.CAMERA_FGS_TYPE = CAMERA_FGS_TYPE;
module.exports.CAMERA_PERMISSIONS = CAMERA_PERMISSIONS;
module.exports.patchSettingsGradle = patchSettingsGradle;
module.exports.patchRootGradle = patchRootGradle;
module.exports.patchAppGradle = patchAppGradle;
module.exports.patchManifestXml = patchManifestXml;
module.exports.applyToAndroidDir = applyToAndroidDir;

if (require.main === module) {
  const target = process.argv[2];
  if (!target) {
    console.error("usage: node app/plugins/withMetaDat.js <path-to-android-dir>");
    process.exit(2);
  }
  const r = applyToAndroidDir(target);
  const where = r.settings ? "settings.gradle"
    : r.rootGradle ? "root build.gradle"
    : "already present";
  console.log(
    `[withMetaDat] mwdat ${MWDAT_VERSION} (${MWDAT_ARTIFACTS.join(", ")}) - ` +
      `repo: ${where}, ` +
      `app build.gradle ${r.app ? "patched" : "already ok"}, ` +
      `manifest ${r.manifest ? "patched" : "already ok"}` +
      (r.kotlin ? ", kotlin sources installed" : "")
  );
  if (!r.repoPlaced) {
    // LOUD, and non-zero. A missing repository does not fail here - it fails
    // deep in gradle as "could not resolve com.meta.wearable", long after
    // anyone connects it to this step.
    console.error(
      "[withMetaDat] ERROR: no repositories block found. Expected either " +
        "dependencyResolutionManagement in settings.gradle or allprojects{} " +
        "in the root build.gradle. The DAT artifacts will NOT resolve."
    );
    process.exit(1);
  }
}
