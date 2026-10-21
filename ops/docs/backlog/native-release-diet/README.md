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
   Original scope: Kotlin keeps generic blocks (list, row,
   card, button, text, voice clip); the daemon describes screens over the
   existing `WearStream`. Fold `wear-voice-stream-playback` and
   `wear-os-paritaets-audit` into it instead of patching them natively. Needs
   an emulator/watch to verify (no gradle/adb in card worktrees).
3. OPEN - move hardcoded texts, thresholds, flows out of glasses bridge,
   livemic, GlassVoice into JS-passed parameters. Native = mechanics only.
4. OPEN - reserve native capabilities in ONE build: list what is foreseeable
   (permissions, background modes, Meta SDK version, camera, BLE), ship them
   dormant behind JS feature flags.
5. OPEN - release rhythm: quarterly native release plus the forced dates
   (Google targetSdk summer, Apple Xcode spring); Expo SDK upgrades land on
   those dates only.
6. OPTIONAL - native builds in CI (EAS / the Mac mirror). Does not reduce the
   count, makes the few builds painless.
