# Native release diet: a few store submissions per year

Owner decree 2026-10-21: "pro Jahr hoechstens ein paar Mal updaten". Measured
cause of the frequent submissions (12 last bumps in app.json): the Wear OS UI
is Kotlin (`plugins/wear/*.kt`, 3.6k lines; HenryScreen/BoardScreen/CardScreen
alone caused 1.0.29-1.0.34), config plugins (`withLanCleartext` -> 1.0.54), and
until 2026-10-19 one shared runtimeVersion for both platforms.

Target: 3-4 native builds per year, 2 of them forced by the stores.

## Steps (in order)

1. DONE 2026-10-21 - batching gate in `ship.sh`: a detected native change is
   reported (files since `refs/helmdeck/last-native-commit`), never built
   automatically. `SHIP_KIND=native` cuts a release. Documented in DEPLOY.md.
2. OPEN, biggest - Wear UI data-driven. MEASURED 2026-10-21 before starting:
   CONTENT is already server-rendered (/wear/board, /wear/chat, /wear/voice,
   routes_wear.py); only ~60 fixed labels sit in Kotlin (BoardScreen 14,
   CardScreen 17, HenryScreen 15, PairingScreen 9). What forced the bumps is
   LAYOUT and BEHAVIOUR (HenryScreen 920 lines, CardScreen 409). A labels
   table alone would not have saved a single past bump, so the real work is a
   screen-description protocol (rows, buttons, input, actions) interpreted by a
   generic renderer - an iterative job that needs the watch emulator in the
   loop (adb + sdk exist on this box), not a blind rewrite.
   STARTED 2026-10-21: protocol v1 + board prototype. Daemon:
   spine/ops/wear_screen.py (blocks header/text/age/card/button, actions
   open_card/nav/reload) added as `screen` to GET /wear/board, test
   ops/tests/test_wear_screen.py. Watch: plugins/wear/ScreenRenderer.kt, used by
   BoardScreen when `screen` is present (old daemon -> native board fallback).
   VERIFIED: python test + `:wear:compileReleaseKotlin`. NOT VERIFIED: rendering
   on the Wear emulator (AVDs Wear_OS_*_API_30 exist; needs a paired demo
   daemon). Next: emulator check, then Chat and Card screens, then drop the
   native board fallback after one native release carries the renderer.
   Original scope: Kotlin keeps generic blocks (list, row,
   card, button, text, voice clip); the daemon describes screens over the
   existing `WearStream`. Fold `wear-voice-stream-playback` and
   `wear-os-paritaets-audit` into it instead of patching them natively. Needs
   an emulator/watch to verify (no gradle/adb in card worktrees).
3. DONE (code) 2026-10-21 - tunables out of Kotlin. Home: workspace settings key
   `native_tuning` (owner-write, not a secret, exported with the harness; NOT
   user_config = per-account view prefs, NOT project_config). Keys + bounds:
   spine/ops/native_tuning.py (front door in settings_post). App: src/data/
   native_tuning.ts, applied at launch and on foreground by useNativeTuning in
   _layout.tsx -> LiveMic.configure (VAD, dictation chunk) and GlassesBridge.tune
   (-> prefs "tuning" -> GlassVoice max-empty/decide-total, camera capture
   timeout). Old constants stay as defaults, so old daemon / old APK / bad value
   = no change. VERIFIED: tsc, python tests, :livemic and :glasses compile.
   NOT compiled: GlassVoiceService.kt + GlassCameraService.kt (android/ holds no
   copy of the plugin sources until a prebuild; diff reviewed by hand).
   NOT done: texts/flows in the services stay native (they are mechanics).
   The chat (HenryScreen) and pairing stay native on purpose (see step 2).
4. OWNER DECISION - capabilities on reserve. Currently declared (Android
   manifest): CAMERA, RECORD_AUDIO, INTERNET, MODIFY_AUDIO_SETTINGS, VIBRATE,
   storage; iOS: camera string only in app.json (mic/speech strings landed in
   17530b44). Reserving is NOT free: Play reviews sensitive permissions and
   foreground-service types (the FGS-microphone declaration once needed a video),
   Apple asks for a purpose per string. So reserve only what is (a) certain to
   ship and (b) cheap to justify. Candidates to decide, none added blindly:
   iOS NSLocalNetworkUsageDescription + Bonjour (the LAN direct path),
   NSBluetoothAlwaysUsageDescription (glasses on iOS), UIBackgroundModes audio
   (voice/glasses), Android POST_NOTIFICATIONS + BLUETOOTH_CONNECT, camera
   already there. Rule for every new native capability: ship it dormant behind a
   `native_tuning`-style flag so enabling it is an OTA.
5. DONE (policy) - rhythm: native changes are batched by ship.sh (see DEPLOY.md);
   cut a release deliberately (SHIP_KIND=native) about quarterly, plus the forced
   dates: Google targetSdk (summer), Apple Xcode/SDK (spring), Expo SDK upgrades
   only on those dates. The first release must carry, in one go: ScreenRenderer,
   LiveMic.configure, GlassesBridge.tune (all already merged), then every
   capability picked in step 4.
6. OPTIONAL - native builds in CI (EAS / the Mac mirror). Does not reduce the
   count, makes the few builds painless.
