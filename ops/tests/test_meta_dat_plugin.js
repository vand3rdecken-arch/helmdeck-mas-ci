// Self-sandboxing test for app/plugins/withMetaDat.js — the Gradle wiring that
// puts the Meta DAT camera SDK into the build.
//
// WHY THIS TEST EXISTS AND WHAT IT CANNOT DO. The Kotlin that uses the SDK
// cannot be compiled from a card worktree (DEPLOY.md §2: an APK builds only
// from a short real path such as C:\hd\app), so none of the camera runtime is
// exercised anywhere. What IS mechanically checkable is the part that decides
// whether the build can resolve the dependency at all — pure string→string
// functions over Gradle files. That is what this covers: idempotency, dialect
// correctness, and refusing to write into a file it does not understand.
//
// No network, no filesystem writes outside a temp dir, no gradle. Run:
//     node ops/tests/test_meta_dat_plugin.js

const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");

const P = require("../app/plugins/withMetaDat.js");

let fails = 0;
function ok(cond, msg) {
  console.log((cond ? "  ok   - " : "  FAIL - ") + msg);
  if (!cond) fails++;
}

// --- fixtures modelled on the real Expo template ---------------------------

const SETTINGS_GROOVY = `
pluginManagement { includeBuild(new File(["node", "--print", "require.resolve('expo/package.json')"].execute(null, rootDir).text.trim(), "../expo-gradle-plugin").toString()) }
plugins { id("com.facebook.react.settings") }
dependencyResolutionManagement {
    versionCatalogs { }
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = 'HelmDeck'
include ':app'
`;

const SETTINGS_KTS = `
pluginManagement { }
dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "HelmDeck"
include(":app")
`;

const APP_GRADLE = `
apply plugin: "com.android.application"
android {
    namespace 'app.helmdeck'
    defaultConfig { minSdk 24 }
}
// note: dependencies are managed by expo autolinking where possible
dependencies {
    implementation("com.facebook.react:react-android")
    implementation("androidx.core:core-ktx:1.13.1")
}
`;

// --- settings.gradle -------------------------------------------------------

console.log("settings.gradle:");
{
  const out = P.patchSettingsGradle(SETTINGS_GROOVY, false);
  ok(out !== SETTINGS_GROOVY, "groovy settings.gradle is modified");
  ok(out.includes(P.MAVEN_URL), "the GitHub Packages URL is written in");
  ok(out.includes(P.MARKER), "the idempotency marker is written in");
  ok(
    out.indexOf(P.MAVEN_URL) > out.indexOf("dependencyResolutionManagement"),
    "the maven block lands INSIDE dependencyResolutionManagement, not above it"
  );
  ok(
    out.indexOf(P.MAVEN_URL) < out.indexOf("google()"),
    "the maven block is spliced at the top of the repositories block"
  );
  ok(
    !out.includes('extra.properties["github_token"]'),
    "groovy dialect does NOT get the Kotlin extra.properties accessor"
  );
  ok(
    out.includes("project.hasProperty('github_token')"),
    "groovy dialect gets the groovy property accessor"
  );
  // The credential must never be baked in.
  ok(
    !/gh[pous]_[A-Za-z0-9]/.test(out),
    "no literal token is ever written into the gradle file"
  );
  ok(out.includes("GITHUB_TOKEN"), "the token is read from the environment");

  const twice = P.patchSettingsGradle(out, false);
  ok(twice === out, "IDEMPOTENT: patching an already-patched file is a no-op");
}

{
  const out = P.patchSettingsGradle(SETTINGS_KTS, true);
  ok(
    out.includes('extra.properties["github_token"]'),
    "kts dialect gets the Kotlin extra.properties accessor"
  );
  ok(
    !out.includes("project.hasProperty("),
    "kts dialect does NOT get the groovy property accessor"
  );
  ok(out.includes('url = uri("'), "kts uses the assignment form of url");
}

{
  // A file with no dependencyResolutionManagement is left ALONE rather than
  // guessed at — a repositories block written in the wrong scope fails on the
  // build machine, far from here.
  const weird = "rootProject.name = 'x'\ninclude ':app'\n";
  ok(
    P.patchSettingsGradle(weird, false) === weird,
    "a settings file with no dependencyResolutionManagement is left untouched"
  );
  ok(P.patchSettingsGradle("", false) === "", "empty input is returned as-is");
  ok(
    P.patchSettingsGradle(undefined, false) === undefined,
    "undefined input does not throw"
  );
}

// --- app/build.gradle ------------------------------------------------------

console.log("app/build.gradle:");
{
  const out = P.patchAppGradle(APP_GRADLE);
  ok(out !== APP_GRADLE, "app build.gradle is modified");
  for (const a of P.MWDAT_ARTIFACTS) {
    ok(
      out.includes(`com.meta.wearable:${a}:${P.MWDAT_VERSION}`),
      `${a} is pinned at ${P.MWDAT_VERSION}`
    );
  }
  ok(
    !out.includes("mwdat-display") && !out.includes("mwdat-mockdevice"),
    "display/mockdevice are deliberately NOT added"
  );
  // The word "dependencies" appears in a COMMENT above the real block; the
  // implementation lines must not land there.
  const commentIdx = out.indexOf("// note: dependencies are managed");
  const implIdx = out.indexOf("mwdat-core");
  ok(
    implIdx > commentIdx,
    "anchors on the dependencies BLOCK, not the word in the comment"
  );
  ok(
    out.indexOf("dependencies {") < implIdx,
    "the implementation lines land inside the dependencies block"
  );

  const twice = P.patchAppGradle(out);
  ok(twice === out, "IDEMPOTENT: patching an already-patched file is a no-op");

  const weird = "android { }\n";
  ok(
    P.patchAppGradle(weird) === weird,
    "a build.gradle with no dependencies block is left untouched"
  );
}

// --- THE REAL TREE'S SHAPE (regression fixture) ----------------------------
//
// COPIED VERBATIM from C:\hd\app\android on 2026-08-21, after the plugin
// silently did nothing against it. The fixtures above model the NEWER template
// (dependencyResolutionManagement in settings.gradle); this app is Expo 57 /
// RN 0.86 with a hand-managed android/, whose settings.gradle has NO
// dependencyResolutionManagement at all - repositories live in the ROOT
// build.gradle under allprojects{}. The plugin reported "settings.gradle
// already ok" and added no repository anywhere, which would have surfaced much
// later as "could not resolve com.meta.wearable:mwdat-core".

const REAL_SETTINGS = `
pluginManagement {
  def reactNativeGradlePlugin = new File(
    providers.exec { workingDir(rootDir); commandLine("node", "--print", "x") }.standardOutput.asText.get().trim()
  ).getParentFile().absolutePath
  includeBuild(reactNativeGradlePlugin)
}
plugins {
  id("com.facebook.react.settings")
  id("expo-autolinking-settings")
}
expoAutolinking.useExpoModules()
rootProject.name = 'HelmDeck'
expoAutolinking.useExpoVersionCatalog()
include ':app'
`;

const REAL_ROOT_GRADLE = `
buildscript {
  repositories {
    google()
    mavenCentral()
  }
  dependencies {
    classpath('com.android.tools.build:gradle')
  }
}

allprojects {
  repositories {
    google()
    mavenCentral()
    maven { url 'https://www.jitpack.io' }
  }
}

apply plugin: "expo-root-project"
`;

console.log("the REAL tree shape (no dependencyResolutionManagement):");
{
  ok(
    P.patchSettingsGradle(REAL_SETTINGS, false) === REAL_SETTINGS,
    "real settings.gradle is correctly left ALONE (no dependencyResolutionManagement)"
  );
  const out = P.patchRootGradle(REAL_ROOT_GRADLE, false);
  ok(out !== REAL_ROOT_GRADLE, "root build.gradle IS patched instead");
  ok(out.includes(P.MAVEN_URL), "the GitHub Packages URL lands in the root gradle");
  // It must go in allprojects, NOT buildscript - buildscript repositories are
  // for gradle plugins, and putting it there resolves nothing at compile time.
  const allIdx = out.indexOf("allprojects");
  const urlIdx = out.indexOf(P.MAVEN_URL);
  ok(urlIdx > allIdx, "the repo lands in allprojects{}, not in buildscript{}");
  ok(
    out.indexOf("google()", allIdx) > urlIdx,
    "spliced at the top of the allprojects repositories block"
  );
  ok(
    !/gh[pous]_[A-Za-z0-9]/.test(out),
    "no literal token written into the root gradle either"
  );
  ok(P.patchRootGradle(out, false) === out, "IDEMPOTENT on the root gradle");
}

// end-to-end on a tree shaped like the real one
console.log("applyToAndroidDir against the REAL tree shape:");
{
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "realtree-"));
  fs.mkdirSync(path.join(dir, "app", "src", "main"), { recursive: true });
  fs.writeFileSync(path.join(dir, "settings.gradle"), REAL_SETTINGS);
  fs.writeFileSync(path.join(dir, "build.gradle"), REAL_ROOT_GRADLE);
  fs.writeFileSync(path.join(dir, "app", "build.gradle"), APP_GRADLE);
  fs.writeFileSync(
    path.join(dir, "app", "src", "main", "AndroidManifest.xml"),
    '<?xml version="1.0"?>\n<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n' +
      "  <application>\n  </application>\n</manifest>\n"
  );

  const r = P.applyToAndroidDir(dir);
  ok(r.repoPlaced === true, "repoPlaced=true - the repository really landed somewhere");
  ok(r.rootGradle === true, "it went into the ROOT build.gradle");
  ok(r.settings === false, "and NOT into settings.gradle");
  const root = fs.readFileSync(path.join(dir, "build.gradle"), "utf8");
  const settings = fs.readFileSync(path.join(dir, "settings.gradle"), "utf8");
  ok(root.includes(P.MAVEN_URL), "root build.gradle on disk has the repo");
  ok(
    !settings.includes(P.MAVEN_URL),
    "settings.gradle on disk does NOT - the repo is declared exactly once"
  );

  const r2 = P.applyToAndroidDir(dir);
  ok(
    r2.rootGradle === false && r2.settings === false && r2.repoPlaced === true,
    "second run: no rewrite, and still reports the repo as placed"
  );
  const root2 = fs.readFileSync(path.join(dir, "build.gradle"), "utf8");
  // split(), NOT new RegExp(MARKER) - the marker contains "(", ")" and ".",
  // which are regex metacharacters, so a RegExp built from it silently matches
  // nothing and the assertion passes/fails for the wrong reason. (It failed
  // for exactly that reason when first written.)
  ok(
    root2.split(P.MARKER).length - 1 === 1,
    "the repo block appears exactly ONCE after two runs"
  );
  ok(
    root2.split(P.MAVEN_URL).length - 1 === 1,
    "the maven URL appears exactly ONCE after two runs"
  );

  fs.rmSync(dir, { recursive: true, force: true });
}

// --- AndroidManifest.xml ---------------------------------------------------

const MANIFEST = `<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET" />
    <application android:name=".MainApplication">
        <activity android:name=".MainActivity" />
    </application>
</manifest>
`;

console.log("AndroidManifest.xml:");
{
  const out = P.patchManifestXml(MANIFEST);
  ok(out.includes(P.CAMERA_SERVICE), "the camera service is declared");
  ok(
    out.includes(`android:foregroundServiceType="${P.CAMERA_FGS_TYPE}"`),
    `FGS type is the narrow "${P.CAMERA_FGS_TYPE}"`
  );
  ok(
    !out.includes('android:foregroundServiceType="camera"'),
    'FGS type is NOT "camera" - the phone camera is never opened'
  );
  ok(
    out.includes('android:exported="false"'),
    "the service is not exported - no other app may start it"
  );
  for (const p of P.CAMERA_PERMISSIONS) {
    ok(out.includes(p), `permission declared: ${p}`);
  }
  ok(
    !out.includes('android:name="android.permission.CAMERA"'),
    "does NOT add the phone CAMERA permission"
  );
  ok(
    out.indexOf(P.CAMERA_SERVICE) < out.indexOf("</application>"),
    "the service lands inside <application>"
  );
  // THE MINSDK OVERRIDE. Both DAT artifacts declare minSdkVersion 29 and this
  // app is 24, so without this the manifest merger hard-fails the build - which
  // is exactly how it was found (a real gradle run, 2026-08-21).
  ok(
    out.includes("tools:overrideLibrary"),
    "uses-sdk carries tools:overrideLibrary (else the merger rejects minSdk 24)"
  );
  ok(
    out.includes("com.meta.wearable.dat.core") &&
      out.includes("com.meta.wearable.dat.camera"),
    "BOTH mwdat artifacts are overridden - core declares minSdk 29 too, not just camera"
  );
  ok(
    out.includes("xmlns:tools"),
    "the tools namespace is present (without it the attribute is a silent no-op)"
  );

  const twice = P.patchManifestXml(out);
  ok(twice === out, "IDEMPOTENT: patching an already-patched manifest is a no-op");

  // A manifest that lacks xmlns:tools must GET it, not silently produce a
  // no-op attribute.
  const noTools = MANIFEST.replace(
    ' xmlns:tools="http://schemas.android.com/tools"', ""
  );
  const fixed = P.patchManifestXml(noTools);
  ok(
    fixed.includes("xmlns:tools") && fixed.includes("tools:overrideLibrary"),
    "a manifest without xmlns:tools has the namespace added"
  );

  // An EXISTING uses-sdk must be extended, never duplicated - two <uses-sdk>
  // elements is itself a merger error.
  const withUsesSdk = MANIFEST.replace(
    "<application",
    '<uses-sdk android:minSdkVersion="24" />\n    <application'
  );
  const ext = P.patchManifestXml(withUsesSdk);
  ok(
    ext.split("<uses-sdk").length - 1 === 1,
    "an existing <uses-sdk> is EXTENDED, not duplicated"
  );
  ok(
    ext.includes("tools:overrideLibrary") && ext.includes('android:minSdkVersion="24"'),
    "extending keeps the original attributes"
  );
}

// The Kotlin must actually honour the API floor the override depends on.
console.log("the runtime guard that makes the override safe:");
{
  const dev = fs.readFileSync(
    path.join(__dirname, "..", "app", "plugins", "metadat", "GlassesDevice.kt"), "utf8");
  const cam = fs.readFileSync(
    path.join(__dirname, "..", "app", "plugins", "metadat", "GlassCameraService.kt"), "utf8");
  ok(dev.includes(`MIN_SDK = ${P.DAT_MIN_SDK}`),
     `GlassesDevice.MIN_SDK matches the plugin's ${P.DAT_MIN_SDK}`);
  ok(dev.includes("SDK_INT >= MIN_SDK"), "supported() checks the running API level");
  ok(dev.includes("if (!supported()) return false"),
     "ensureInitialized refuses BEFORE referencing Wearables");
  ok(cam.includes("GlassesDevice.supported()"),
     "the camera service checks the API floor");
  // Order matters: the floor check must precede the radio claim, or a refused
  // old device would still take (and maybe leak) the radio.
  ok(
    cam.indexOf("GlassesDevice.supported()") < cam.indexOf("GlassesRadio.acquire"),
    "the API-floor check comes BEFORE the radio claim"
  );
}

// --- the CLI half, against a temp tree -------------------------------------

console.log("applyToAndroidDir (hand-managed path):");
{
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "metadat-"));
  const mainDir = path.join(dir, "app", "src", "main");
  fs.mkdirSync(mainDir, { recursive: true });
  fs.writeFileSync(path.join(dir, "settings.gradle"), SETTINGS_GROOVY);
  fs.writeFileSync(path.join(dir, "app", "build.gradle"), APP_GRADLE);
  fs.writeFileSync(path.join(mainDir, "AndroidManifest.xml"), MANIFEST);

  const r1 = P.applyToAndroidDir(dir);
  ok(
    r1.settings === true && r1.app === true && r1.manifest === true,
    "first run patches settings, app gradle and manifest"
  );
  ok(r1.kotlin === true, "first run installs the camera service source");
  const s = fs.readFileSync(path.join(dir, "settings.gradle"), "utf8");
  const a = fs.readFileSync(path.join(dir, "app", "build.gradle"), "utf8");
  ok(s.includes(P.MAVEN_URL), "settings.gradle really written to disk");
  ok(a.includes("mwdat-camera"), "app/build.gradle really written to disk");

  // The .kt must land on the package path the manifest names, or the class is
  // simply absent at runtime and the service fails to start with a
  // ClassNotFoundException the manifest cannot warn about.
  const kt = path.join(dir, "app", "src", "main", "java", "app", "helmdeck",
                       "glasses", "GlassCameraService.kt");
  ok(fs.existsSync(kt), "GlassCameraService.kt installed on its package path");
  const ktSrc = fs.readFileSync(kt, "utf8");
  ok(
    ktSrc.includes("package app.helmdeck.glasses"),
    "the installed source declares the package the manifest references"
  );
  ok(
    P.CAMERA_SERVICE === "app.helmdeck.glasses.GlassCameraService" &&
      ktSrc.includes("class GlassCameraService"),
    "manifest service name and the Kotlin class agree"
  );
  ok(
    ktSrc.includes("GlassesRadio.acquire"),
    "the camera takes the radio arbiter before touching the SDK"
  );

  // BOTH product shapes. The display/non-display split must be ASKED of the
  // SDK, never inferred from a model-name list that rots on the next frame
  // Meta ships (CLAUDE.md's no-monkey-patches law).
  const devKt = path.join(dir, "app", "src", "main", "java", "app", "helmdeck",
                          "glasses", "GlassesDevice.kt");
  ok(fs.existsSync(devKt), "GlassesDevice.kt installed (display vs non-display)");
  const devSrc = fs.readFileSync(devKt, "utf8");
  ok(
    devSrc.includes("isDisplayCapable()"),
    "display capability is READ FROM THE SDK, not inferred"
  );
  ok(
    !/RAYBAN_META\s*(==|->|,)/.test(devSrc.replace(/\/\*[\s\S]*?\*\//g, "")),
    "no hardcoded model-name matching outside comments"
  );

  const r2 = P.applyToAndroidDir(dir);
  ok(
    r2.settings === false && r2.app === false && r2.manifest === false &&
      r2.kotlin === false,
    "second run reports no change (idempotent on disk too)"
  );

  fs.rmSync(dir, { recursive: true, force: true });
}

// --- the SHARED arbiter, installed by the VOICE plugin ---------------------
//
// GlassesRadio.kt is what keeps the mic and the camera off the Bluetooth radio
// at the same time (§12.4). It is installed by withGlassVoice.js and merely
// USED by withMetaDat.js - one owner per file. That split is only safe if the
// voice plugin really does install it, so it is checked here rather than
// assumed, next to the camera half that depends on it.

console.log("withGlassVoice installs the shared arbiter:");
{
  const V = require("../app/plugins/withGlassVoice.js");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "glassvoice-"));
  const main = path.join(dir, "app", "src", "main");
  fs.mkdirSync(main, { recursive: true });
  fs.writeFileSync(
    path.join(main, "AndroidManifest.xml"),
    '<?xml version="1.0" encoding="utf-8"?>\n' +
      '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n' +
      "    <application>\n    </application>\n</manifest>\n"
  );

  const r1 = V.applyToAndroidDir(dir);
  ok(r1.wroteKotlin === true, "first run installs kotlin sources");

  const svc = path.join(main, "java", "app", "helmdeck", "voice", "GlassVoiceService.kt");
  const radio = path.join(main, "java", "app", "helmdeck", "glasses", "GlassesRadio.kt");
  ok(fs.existsSync(svc), "GlassVoiceService.kt installed");
  ok(fs.existsSync(radio), "GlassesRadio.kt installed (the shared arbiter)");

  const svcSrc = fs.readFileSync(svc, "utf8");
  const radioSrc = fs.readFileSync(radio, "utf8");
  ok(
    radioSrc.includes("package app.helmdeck.glasses"),
    "arbiter declares the package both services import"
  );
  ok(
    svcSrc.includes("import app.helmdeck.glasses.GlassesRadio"),
    "the voice service imports the arbiter"
  );
  ok(
    svcSrc.includes("GlassesRadio.acquire(GlassesRadio.Mode.MIC)"),
    "the voice service CLAIMS the radio for the glasses mic"
  );
  ok(
    svcSrc.includes("GlassesRadio.release(GlassesRadio.Mode.MIC)"),
    "the voice service RELEASES the radio"
  );
  // The narrowness of the guard is the point: a phone-mic listen opens no SCO
  // link, so it must not be gated behind the arbiter.
  ok(
    svcSrc.includes("ACTION_LISTEN_PHONE_MIC"),
    "the phone-mic action still exists (never blocked by the arbiter)"
  );

  const r2 = V.applyToAndroidDir(dir);
  ok(r2.wroteKotlin === false, "second run rewrites nothing (idempotent)");

  fs.rmSync(dir, { recursive: true, force: true });
}

// --- EVERY local plugin must be applied by build_apk.sh --------------------
//
// THE BUG THIS EXISTS FOR, found 2026-08-21 while wiring withMetaDat: app.json
// listed the plugin, but ops/deploy/build_apk.sh did not apply it. surfaces/app/android is
// git-ignored and hand-managed, so an unapplied plugin contributes NOTHING to
// the tree - gradle then builds an APK with the whole feature missing and
// EXITS ZERO, because there is nothing to fail. DEPLOY.md §2 names this class
// exactly: "the skips are SILENT: the build goes green and the artifact is
// wrong."
//
// The manifest/gradle assertions above cannot catch it: they prove the plugin
// WORKS, not that anyone RUNS it. This closes the gap generically, so the next
// plugin someone adds to app.json cannot repeat it.

console.log("build_apk.sh applies every local plugin:");
{
  const appJson = JSON.parse(
    fs.readFileSync(path.join(__dirname, "..", "app", "app.json"), "utf8")
  );
  const sh = fs.readFileSync(
    path.join(__dirname, "..", "deploy", "build_apk.sh"), "utf8"
  );
  // Local plugins only: "./plugins/withX" (string form) or ["./plugins/withX", {...}].
  const local = appJson.expo.plugins
    .map((p) => (Array.isArray(p) ? p[0] : p))
    .filter((p) => typeof p === "string" && p.startsWith("./plugins/"))
    .map((p) => p.replace("./plugins/", ""));

  ok(local.length > 0, `found ${local.length} local plugins in app.json`);
  for (const name of local) {
    ok(
      sh.includes(`node app/plugins/${name}.js surfaces/app/android`),
      `build_apk.sh applies ${name}`
    );
  }
  // And each one must actually exist on disk, or the build dies at run time.
  for (const name of local) {
    ok(
      fs.existsSync(path.join(__dirname, "..", "app", "plugins", `${name}.js`)),
      `app/plugins/${name}.js exists`
    );
  }
}

console.log(fails === 0 ? "\nALL PASS" : `\n${fails} FAILURE(S)`);
process.exit(fails === 0 ? 0 : 1);
