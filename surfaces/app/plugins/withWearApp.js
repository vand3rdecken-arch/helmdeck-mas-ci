// Gradle wiring for the HelmDeck WEAR OS module (W2a) - a SEVENTH entry in
// the same list ops/deploy/build_apk.sh already re-applies after every
// `expo prebuild --clean` (LanCleartext/ReleaseSigning/GlassVoice/MetaDat/
// SherpaOnnx/UpdateUrl): surfaces/app/android is git-ignored and regenerated
// from nothing on every build, so a native fact that lives ONLY there is
// silently wiped the next time prebuild runs unless a script re-lays it down.
// The pattern is measured, not invented (README.md Â§7.1: "a seventh entry in
// the same list", the study's own words before this plugin existed).
//
// UNLIKE the other six, this plugin does not PATCH an existing module - it
// CREATES A WHOLE NEW ONE (:wear, a separate installable app). None of the
// existing plugins do that, and none of them are registered in app.json's
// `plugins` array either (checked: only expo-* first-party plugins are) -
// they are CLI-only, invoked exclusively from build_apk.sh. This file follows
// that exact precedent rather than also writing an unexercised Expo
// config-plugin half: Wear OS is Android-only (no iOS Wear), and an
// `expo prebuild` run is not reachable from this card worktree to prove a
// withDangerousMod-based half would even execute in the right order.
//
// WHAT THIS CANNOT PROVE FROM A CARD WORKTREE - said once, here, instead of
// on every function: this repo has no Android SDK, no Gradle, no `expo`
// CLI reachable in this worktree, and the tool guard blocks the short-path
// junction (C:\hd\app) the real build recipe needs (DEPLOY.md:508-515, NDK/
// CMake path-length trap). Every Gradle/Kotlin fact below is either a
// citation from developer.android.com (checked 2026-08-28, see wear/
// build.gradle's own comments for the exact pins) or evidence already living
// in this repo (the phone module's existing hand-installed .kt files prove
// Kotlin is wired at the root). NONE of it has been through Gradle. See
// README.md Â§9.1 for the exact open list.

const MARKER_SETTINGS = "HelmDeck: Wear OS module (withWearApp.js)";
const MARKER_ROOT = "HelmDeck: Compose compiler (withWearApp.js)";
const WEAR_MODULE_DIR = "wear";

/**
 * Add `include ':wear'` to settings.gradle[.kts]. Appended at the end rather
 * than inserted into a specific block - unlike a repository entry (which
 * must land inside a particular `repositories {}`), an `include` statement
 * is valid anywhere at the top level, so appending is both simpler and
 * cannot be broken by a settings.gradle shape this plugin has not seen.
 */
function patchSettingsGradle(text, isKts) {
  if (!text || text.includes(MARKER_SETTINGS)) return text;
  const stmt = isKts ? `include(":${WEAR_MODULE_DIR}")` : `include ':${WEAR_MODULE_DIR}'`;
  return text.replace(/\s*$/, "") + `\n\n// ${MARKER_SETTINGS}\n${stmt}\n`;
}

/**
 * Add the Compose compiler Gradle plugin to the ROOT build.gradle's
 * `buildscript { dependencies { ... } }` classpath - the documented trap
 * (README.md Â§7.1): "das Compose-Compiler-Plugin gehÃ¶rt in die ROOT
 * build.gradle, nicht ins Modul". Kotlin 2.0+ ships the Compose compiler as
 * its own versioned Gradle plugin, released in lockstep with the Kotlin
 * compiler itself.
 *
 * PINNED, not `$kotlinVersion` (measured 2026-08-28, deploy-red on card
 * chat-wear-os-integration-phas): this Expo/RN template (Expo 57,
 * expo-modules-autolinking's ExpoRootProjectPlugin) sets `rootProject.ext.
 * kotlinVersion` from `apply plugin: "expo-root-project"` - which runs as
 * part of the build SCRIPT BODY, after `buildscript {}` has already been
 * evaluated. Gradle special-cases `buildscript {}` to configure before
 * anything else in the file regardless of textual position, so the property
 * does not exist yet when this classpath entry resolves -> "Could not get
 * unknown property 'kotlinVersion'". The actual Kotlin Gradle plugin version
 * this build resolves is 2.1.20, pinned in
 * node_modules/@react-native/gradle-plugin/gradle/libs.versions.toml (which
 * is what backs the version-less `kotlin-gradle-plugin` classpath entry via
 * settings.gradle's composite-build substitution) - confirmed against
 * voice-interaction-design.md:475's independently measured version. Re-check
 * this pin if RN's gradle-plugin bumps its own Kotlin version.
 *
 * Anchored on `buildscript` -> the FIRST `dependencies {` after it, which in
 * every Expo/RN classic-style root build.gradle is the buildscript's own
 * (there is no nested buildscript, so this cannot land in the wrong block).
 */
const PINNED_KOTLIN_VERSION = "2.1.20";

function patchRootGradleForCompose(text) {
  if (!text || text.includes(MARKER_ROOT)) return text;
  const bsIdx = text.indexOf("buildscript");
  if (bsIdx < 0) return text;
  const depIdx = text.indexOf("dependencies", bsIdx);
  if (depIdx < 0) return text;
  const braceIdx = text.indexOf("{", depIdx);
  if (braceIdx < 0) return text;
  const line = `\n        // ${MARKER_ROOT}\n        classpath("org.jetbrains.kotlin:compose-compiler-gradle-plugin:${PINNED_KOTLIN_VERSION}")`;
  return text.slice(0, braceIdx + 1) + line + text.slice(braceIdx + 1);
}

/** Copy the wear/ module's static sources into the hand-managed android/
 *  tree. Whole-file writes, not patches - unlike the other plugins, there is
 *  nothing pre-existing here for `expo prebuild` to have generated; this
 *  entire module is this plugin's own content. Idempotent by content
 *  comparison, same idiom as withMetaDat.js's installKotlin(). */
function installWearModule(androidDir) {
  const fs = require("fs");
  const path = require("path");
  const srcRoot = path.join(__dirname, "wear");
  const JAVA = ["wear", "src", "main", "java", "app", "helmdeck", "wear"];
  const files = [
    ["build.gradle", ["wear", "build.gradle"]],
    ["AndroidManifest.xml", ["wear", "src", "main", "AndroidManifest.xml"]],
    ["MainActivity.kt", [...JAVA, "MainActivity.kt"]],
    // 2026-08-29 (device-code pairing, README.md Â§4.6/Â§9.1 item 20-23):
    // PairingScreen shares MainActivity's package (app.helmdeck.wear);
    // HelmDeckBox and DeviceStore/RelayClient get their own sub-packages
    // (crypto/, data/) matching their `package` declarations exactly - a
    // mismatched directory here is a compile error, not a silent bug, but
    // still worth getting right the first time.
    ["PairingScreen.kt", [...JAVA, "PairingScreen.kt"]],
    // 2026-08-29 (board view, README.md Â§4.7/Â§9.1): the owner decree that
    // wearables talk to Henry, never the worker, lives in CardScreen.kt.
    ["BoardModel.kt", [...JAVA, "BoardModel.kt"]],
    ["BoardScreen.kt", [...JAVA, "BoardScreen.kt"]],
    ["CardScreen.kt", [...JAVA, "CardScreen.kt"]],
    ["HelmDeckBox.kt", [...JAVA, "crypto", "HelmDeckBox.kt"]],
    ["DeviceStore.kt", [...JAVA, "data", "DeviceStore.kt"]],
    ["RelayClient.kt", [...JAVA, "data", "RelayClient.kt"]],
    // 2026-08-29: Henry's spoken reply (/wear/talk's voice.render_b64 clip,
    // README.md Â§4.9) - MediaPlayer playback, own file since neither
    // CardScreen nor RelayClient owns audio concerns.
    ["VoicePlayer.kt", [...JAVA, "data", "VoicePlayer.kt"]],
    // 2026-08-29 (W2d): the watch's OWN sealed FCM receiver, so a card can
    // reach the wrist without the phone being in range to bridge it.
    ["PushService.kt", [...JAVA, "PushService.kt"]],
    // 2026-08-29: Henry reachable from the board, not only from inside a card.
    ["HenryScreen.kt", [...JAVA, "HenryScreen.kt"]],
    // 2026-08-31 (3ce78d0): HenryScreen's LAYOUT as data - `Line`, `Row`,
    // `buildRows`, `newestMessageIndex`. Split out so the scroll index could be
    // asserted against a layout that exists as a value (ops/tests/wear_chat_rows.kt).
    //
    // MISSING FROM THIS LIST UNTIL 2026-09-02, and that omission is exactly why
    // the watch still polls: the split shipped the new HenryScreen (hanging GET
    // on /stream/wait, no ticker) into the generated module while the file
    // DEFINING its symbols never arrived, so `:wear:assembleDebug` has been
    // failing on unresolved references ever since - and the APK on the owner's
    // wrist is therefore still the pre-48f78f0, 15s-timer build. The completeness
    // check below is the half that makes this unrepeatable.
    ["ChatRows.kt", [...JAVA, "ChatRows.kt"]],
    // 2026-09-02: the app's ONE event channel (hanging GET on /stream/wait),
    // hoisted out of HenryScreen so the board screen shares it instead of
    // running load-once - MainActivity composes one screen at a time, so a
    // stream owned by a screen dies on every navigation.
    ["WearStream.kt", [...JAVA, "WearStream.kt"]],
    // 2026-08-29: HelmDeck's own palette, so the watch stops shipping
    // Material's purple baseline.
    ["WearTheme.kt", [...JAVA, "WearTheme.kt"]],
    // AUTO-GENERATED by ops/tools/gen_tokens.py - the palette itself.
    ["WearTokens.kt", [...JAVA, "WearTokens.kt"]],
    // 2026-09-23 (font-size guideline rejection #2, vc1000006): the
    // round-bezel-safe side inset (wearBezelInset()), shared by every
    // screen instead of each one recomputing LocalConfiguration.current
    // .screenWidthDp * 0.10f on its own.
    ["WearLayout.kt", [...JAVA, "WearLayout.kt"]],
  ];
  // EVERY .kt IN wear/ MUST BE LISTED ABOVE. Derived from the directory at
  // build time, never from memory - this list is a hand-maintained mirror of a
  // real folder, and a mirror nobody checks drifts on the first file someone
  // adds. ChatRows.kt drifted for two days (2026-08-31 -> 2026-09-02) and cost
  // the watch its entire push path, because the failure mode is silent HERE and
  // only surfaces as an unresolved-reference wall inside Gradle - a place where
  // "the watch feels laggy" is not the sentence anyone reaches for.
  //
  // THROWS, not warns: a :wear module missing a source file cannot compile, so
  // continuing would only move a certain failure somewhere less legible. Only
  // .kt is checked - build.gradle/AndroidManifest.xml are listed explicitly and
  // ic_launcher.xml is written by the icon block below, not copied.
  const listed = new Set(files.map(([rel]) => rel));
  const missing = fs.readdirSync(srcRoot)
    .filter((f) => f.endsWith(".kt") && !listed.has(f));
  if (missing.length) {
    throw new Error(
      "[withWearApp] " + missing.join(", ") + " exist(s) in plugins/wear/ but " +
      "is not in installWearModule()'s copy list - the :wear module would be " +
      "generated without it and fail to compile. Add it to `files` above.");
  }
  let wrote = 0;
  for (const [rel, dstParts] of files) {
    const code = fs.readFileSync(path.join(srcRoot, rel), "utf8");
    const dst = path.join(androidDir, ...dstParts);
    const had = fs.existsSync(dst) ? fs.readFileSync(dst, "utf8") : null;
    if (had === code) continue;
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.writeFileSync(dst, code);
    wrote++;
  }
  // W2d: the google-services plugin resolves its config per MODULE, so :wear
  // needs its own copy - :app's android/app/google-services.json is not visible
  // to it. Copied from the project's single source of truth rather than kept as
  // a second checked-in file that could drift: one Firebase project, one file,
  // which since 2026-08-29 carries an app.helmdeck.wear client alongside
  // app.helmdeck. Missing entry => Gradle fails loudly ("No matching client
  // found for package name"), which is the honest failure, not a silent skip.
  // Launcher icon (2026-08-29). The module had NO android:icon at all, so the
  // watch listed it with a blank system placeholder - findable only by reading
  // the word "HelmDeck" in the drawer.
  //
  // Copied from the SAME brand PNGs app.json hands Expo for the phone
  // (assets/images/android-icon-*.png), not from the phone module's GENERATED
  // mipmaps: those are produced by expo's own prebuild step, and depending on
  // output that may not exist yet when this plugin runs would be a build-order
  // race. The source assets are always there.
  //
  // BINARY copy - readFileSync WITHOUT "utf8". The text path above would turn
  // every PNG into mojibake and Gradle would reject the resource; that is the
  // one thing to get right here.
  const iconSrcDir = path.join(path.dirname(androidDir), "assets", "images");
  const ICONS = [
    ["android-icon-background.png", "ic_launcher_background.png"],
    ["android-icon-foreground.png", "ic_launcher_foreground.png"],
    ["android-icon-monochrome.png", "ic_launcher_monochrome.png"],
  ];
  // One density only: these are 1024px sources, so Android downscales for every
  // bucket. Shipping five identical copies would just grow the APK.
  const mipDir = path.join(androidDir, "wear", "src", "main", "res", "mipmap-xxhdpi");
  for (const [src, dst] of ICONS) {
    const from = path.join(iconSrcDir, src);
    if (!fs.existsSync(from)) continue;
    const bytes = fs.readFileSync(from);
    const to = path.join(mipDir, dst);
    const had = fs.existsSync(to) ? fs.readFileSync(to) : null;
    if (had && had.equals(bytes)) continue;
    fs.mkdirSync(mipDir, { recursive: true });
    fs.writeFileSync(to, bytes);
    wrote++;
  }
  const adaptiveSrc = path.join(srcRoot, "ic_launcher.xml");
  if (fs.existsSync(adaptiveSrc)) {
    const want = fs.readFileSync(adaptiveSrc, "utf8");
    const dst = path.join(androidDir, "wear", "src", "main", "res",
                          "mipmap-anydpi-v26", "ic_launcher.xml");
    const have = fs.existsSync(dst) ? fs.readFileSync(dst, "utf8") : null;
    if (have !== want) {
      fs.mkdirSync(path.dirname(dst), { recursive: true });
      fs.writeFileSync(dst, want);
      wrote++;
    }
  }

  const gsSrc = path.join(path.dirname(androidDir), "google-services.json");
  if (fs.existsSync(gsSrc)) {
    const gsDst = path.join(androidDir, "wear", "google-services.json");
    const want = fs.readFileSync(gsSrc, "utf8");
    const have = fs.existsSync(gsDst) ? fs.readFileSync(gsDst, "utf8") : null;
    if (have !== want) {
      fs.mkdirSync(path.dirname(gsDst), { recursive: true });
      fs.writeFileSync(gsDst, want);
      wrote++;
    }
  }
  return wrote > 0;
}

function applyToAndroidDir(androidDir) {
  const fs = require("fs");
  const path = require("path");
  const out = { settings: false, rootGradle: false, module: false };

  for (const name of ["settings.gradle", "settings.gradle.kts"]) {
    const fp = path.join(androidDir, name);
    if (!fs.existsSync(fp)) continue;
    const before = fs.readFileSync(fp, "utf8");
    const after = patchSettingsGradle(before, name.endsWith(".kts"));
    if (after !== before) {
      fs.writeFileSync(fp, after);
      out.settings = true;
    }
    break;
  }
  if (!out.settings) {
    // Re-run is a no-op (MARKER already present), not a failure - only warn
    // when settings.gradle is missing outright.
    const already = ["settings.gradle", "settings.gradle.kts"].some(
      (n) => fs.existsSync(path.join(androidDir, n)) &&
        fs.readFileSync(path.join(androidDir, n), "utf8").includes(MARKER_SETTINGS)
    );
    out.settingsAlready = already;
  }

  const rootGradle = path.join(androidDir, "build.gradle");
  if (fs.existsSync(rootGradle)) {
    const before = fs.readFileSync(rootGradle, "utf8");
    const after = patchRootGradleForCompose(before);
    if (after !== before) {
      fs.writeFileSync(rootGradle, after);
      out.rootGradle = true;
    }
  }

  out.module = installWearModule(androidDir);
  return out;
}

module.exports = { applyToAndroidDir, patchSettingsGradle, patchRootGradleForCompose,
  MARKER_SETTINGS, MARKER_ROOT, WEAR_MODULE_DIR };

if (require.main === module) {
  const target = process.argv[2];
  if (!target) {
    console.error("usage: node app/plugins/withWearApp.js <path-to-android-dir>");
    process.exit(2);
  }
  const r = applyToAndroidDir(target);
  console.log(
    `[withWearApp] settings.gradle ${r.settings ? "patched" : (r.settingsAlready ? "already ok" : "NOT FOUND")}, ` +
      `root build.gradle ${r.rootGradle ? "patched" : "already ok"}, ` +
      `:wear module ${r.module ? "written" : "already current"}`
  );
  if (!r.settings && !r.settingsAlready) {
    // LOUD, non-zero - same discipline as withMetaDat.js's missing-repo
    // check. Without `include ':wear'` the module exists on disk but Gradle
    // never sees it, and the build goes green having built nothing new -
    // the exact silent-wrong-artifact class this repo has been burned by.
    console.error(
      "[withWearApp] ERROR: no settings.gradle[.kts] found - the :wear module " +
        "will NOT be part of the build."
    );
    process.exit(1);
  }
}
