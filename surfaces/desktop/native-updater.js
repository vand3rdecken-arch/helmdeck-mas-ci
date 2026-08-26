// Full-app auto-update via electron-updater (Paseo parity: packages/surfaces/desktop/
// src/features/auto-updater.ts uses the same library the same way). This is
// what updater.js was never able to be: updater.js only ever syncs the UI
// bundle (app-dist), because a plain file sync can't safely replace the
// running process's own code. electron-updater downloads the real published
// installer build, verifies it against the signed blockmap, and reinstalls
// the WHOLE app (main.js, app.asar, node_modules - everything) silently on
// quit - the only way a shell-code fix (found live 2026-08-14: the daemon
// spawn losing its own stdout, three installer rounds to chase down and fix)
// can ever reach an already-installed machine without the owner re-running
// an .exe download by hand.
//
// Deliberately NOT Paseo's full rollout/staging-bucket machinery - this is a
// single-owner app on one release channel, not a multi-tenant product; a
// plain checkForUpdates() on an interval is the right amount of complexity.
const { autoUpdater } = require("electron-updater");

const CHECK_INTERVAL_MS = 30 * 60 * 1000;   // same cadence as updater.js

// The gap this closes (owner-reported 2026-08-26): the phone gets a visible
// "update available" banner (apk_update.tsx, checked against the relay's own
// version.json), but the desktop shell's update state only ever went to the
// log file - checking/available/downloaded/error was real and running, just
// invisible in the app. `notify` is the seam: main.js wires it to an IPC
// push to the renderer (see preload.js), so the SAME events that already
// fire here become a UI state instead of a log line, with no change to the
// update mechanism itself (still autoDownload + autoInstallOnAppQuit).
function createNativeUpdater({ log, isPackaged, notify }) {
  const emit = typeof notify === "function" ? notify : () => {};
  let status = { state: "unavailable", version: null, message: null };
  const set = (state, extra) => { status = { state, version: null, message: null, ...extra }; emit(status); };

  if (!isPackaged) {
    // Paseo parity: "Auto-update is not available in development mode" - a
    // dev run has no published release to compare against and no installed
    // location to replace.
    return { start() {}, stop() {}, getStatus: () => status, quitAndInstall() {} };
  }
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.allowDowngrade = false;
  // electron-updater's own logger defaults to console, which is exactly the
  // broken-pipe-risk stream main.js's log() already guards against - route
  // through the same guarded sink instead.
  autoUpdater.logger = {
    info: (m) => log("update", "[native] " + m + "\n"),
    warn: (m) => log("update", "[native] WARN " + m + "\n"),
    error: (m) => log("update", "[native] ERROR " + m + "\n"),
    debug: () => { /* quiet */ },
  };
  set("checking");
  autoUpdater.on("checking-for-update", () => set("checking"));
  autoUpdater.on("update-available", (info) => {
    log("update", "[native] update available: " + info.version + " - downloading\n");
    set("downloading", { version: info.version });
  });
  autoUpdater.on("update-not-available", () => {
    log("update", "[native] up to date\n");
    set("current");
  });
  autoUpdater.on("update-downloaded", (info) => {
    log("update", "[native] " + info.version + " downloaded - installs silently on quit\n");
    set("downloaded", { version: info.version });
  });
  autoUpdater.on("error", (e) => {
    const message = String((e && e.message) || e);
    log("update", "[native] check/download failed (will retry next cycle): " + message + "\n");
    set("error", { message });
  });

  let timer = null;
  function checkOnce() {
    autoUpdater.checkForUpdates().catch((e) =>
      log("update", "[native] checkForUpdates threw: " + (e && e.message) + "\n"));
  }
  return {
    start() {
      checkOnce();
      timer = setInterval(checkOnce, CHECK_INTERVAL_MS);
    },
    stop() { if (timer) { clearInterval(timer); timer = null; } },
    getStatus: () => status,
    // Explicit, owner-initiated install (the "restart now" tap) instead of
    // waiting for autoInstallOnAppQuit - same call electron-updater's own
    // quit-and-install path uses; isSilent=false shows the native progress
    // dialog, isForceRunAfter=true reopens the app once reinstalled.
    quitAndInstall() { if (status.state === "downloaded") autoUpdater.quitAndInstall(false, true); },
  };
}

module.exports = { createNativeUpdater };
