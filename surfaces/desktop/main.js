// HelmDeck desktop (Electron wrapper) - modeled on Paseo's packages/desktop.
// On launch it starts the local services and shows the UI in a native window:
//   - the Python daemon (swarm.py serve) on :8140  (the brain + runner)
//   - the Next.js server on :3300 (the UI, proxies /backend/* to the daemon)
// then loads http://localhost:3300 in a BrowserWindow. On quit it kills both.
//
// Requirements on the user's machine (same as HelmDeck itself):
//   - Python 3.12 (the `py -3.12` launcher on Windows, or `python3`)
//   - the `claude` CLI (Claude Code) - the agent runtime cards execute in
const { app, BrowserWindow, dialog, shell, ipcMain } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const http = require("http");

// A broken-pipe write on stdout/stderr surfaces as an uncaught EPIPE; in a
// packaged GUI build that pops the fatal "A JavaScript error occurred" dialog
// and quits. Swallow EPIPE specifically; let anything else propagate.
process.on("uncaughtException", (e) => {
  if (e && e.code === "EPIPE") return;
  throw e;
});

const { startSetupServer } = require("./setup");

const DAEMON_PORT = 8140;
const WEB_PORT = 3300;
let daemon = null, web = null, win = null, failed = false, setupSrv = null, daemonAdopted = false;

// packaged: resources/{daemon,app-dist}; dev: repo ../{daemon,surfaces/app/dist}
const root = app.isPackaged ? process.resourcesPath : path.join(__dirname, "..", "..");
// THE REAL BRAIN pointer. The packaged install ships its own daemon COPY under
// resources/daemon - a fresh state dir with no relay pairing, no users.json and
// stale code. Spawning THAT (when the adopt probe missed) put a sandbox brain
// on :8140: the phone's room was never polled and the minted token was invalid
// against the real daemon - "Desktop nicht erreichbar" on both ends. One state
// dir must be the single owner, so a pointer file (one line: the absolute path
// of the real daemon dir) redirects spawn AND token mint there.
//
// THE POINTER MUST OUTLIVE A REINSTALL (found live 2026-08-14): NSIS replaces
// the whole resources/ folder on every installer run, so a pointer kept ONLY
// at resources/daemon-dir.txt died with the very next update and silently
// fell back to the bundled sandbox - "Desktop nicht erreichbar" after every
// upgrade, with no error, because the catch below existed to keep a genuinely
// FRESH install working and couldn't tell that apart from a broken redirect.
// Electron's userData dir is untouched by an installer by design, so it is
// now the primary pointer location; resources/daemon-dir.txt is read once as
// a migration source (a hand-set redirect from before this fix, or the setup
// wizard) and copied into userData so it survives from here on.
function resolveDaemonDir() {
  const fs = require("fs");
  const bundled = path.join(root, "daemon");
  const userPointer = path.join(app.getPath("userData"), "daemon-dir.txt");
  const legacyPointer = path.join(root, "daemon-dir.txt");
  const valid = (p) => p && fs.existsSync(path.join(p, "swarm.py"));

  try {
    const p = fs.readFileSync(userPointer, "utf8").trim();
    if (valid(p)) return p;
    if (p) log("daemon", "userData daemon-dir.txt points at '" + p + "' but no swarm.py "
      + "there - falling back\n");
  } catch { /* no userData pointer yet - fall through to migration/bundled */ }

  try {
    const p = fs.readFileSync(legacyPointer, "utf8").trim();
    if (valid(p)) {
      try { fs.writeFileSync(userPointer, p); } catch { /* migration best-effort */ }
      return p;
    }
    if (p) log("daemon", "resources/daemon-dir.txt points at '" + p + "' but no swarm.py "
      + "there - using the bundled copy\n");
  } catch { /* no legacy pointer: genuinely fresh install, bundled copy is correct */ }

  return bundled;
}
const daemonDir = resolveDaemonDir();
// The UI is now the single Expo/React-Native web export (expo export --platform
// web), replacing the old Next.js server. Same static SPA that ships to the
// phone/web; the desktop just serves it locally and points it at the daemon.
const appDistDir = app.isPackaged ? path.join(root, "app-dist") : path.join(__dirname, "..", "app", "dist");

// NO TOKEN IS MINTED HERE ANY MORE.
//
// This used to run `spine.auth.mint_token owner desktop` at every launch and inject
// the result into the SPA's #cfg hash, which meant OPENING THE APP WAS AN OWNER
// LOGIN WITH NO CREDENTIAL: anyone at an unlocked machine had full owner rights
// without knowing anything. The shell now hands over the daemon URL only; the
// SPA authenticates like every other client, through the login screen, and the
// session it gets is persisted by the app (config.ts hydrate merges localStorage
// under the hash, so this is one login - not one per launch).

// Auto-update: TWO layers, because they cover different code.
//  - updater.js (relay OTA, see that file): the UI bundle ONLY - fast,
//    silent, follows the same channel the phone uses.
//  - native-updater.js (electron-updater, Paseo parity): the WHOLE app,
//    main.js/app.asar included - the only path a shell-code fix (found live
//    2026-08-14 chasing the daemon's own stdout capture) can ever reach an
//    installed machine without a hand-run .exe. Runs independently of the
//    UI-bundle sync; either can apply without the other.
// Dev runs are exempt from both, exactly like Paseo ("Auto-update is not
// available in development mode").
// sendToWindow reads the module-scope `win` AT CALL TIME (not a captured
// reference) - the window can be null (still opening) or replaced (a rare
// recreate path), and an update event can fire at any point in that
// lifecycle. Silent no-op if there's nowhere to send it yet; the renderer
// still gets the current state on mount via each get-status IPC handler.
const sendToWindow = (channel, payload) => { if (win && !win.isDestroyed()) win.webContents.send(channel, payload); };

// Mac App Store builds may NEVER self-update (Guideline 2.5.2 forbids an app
// downloading/replacing its own code, and App Sandbox separately makes the
// app-dist swap below IMPOSSIBLE - a sandboxed app cannot write into its own
// installed bundle). Electron sets process.mas=true only in a mas-target
// build (surfaces/desktop/electron-builder.mas.yml), never in the
// direct-distribution build this same main.js also produces.
const isMas = process.mas === true;

let updater = null;
if (app.isPackaged && !isMas) {
  const { createUpdater, readRelayUrl } = require("./updater");
  const feedBase = readRelayUrl(path.join(daemonDir, "relay_feed.json"));
  if (feedBase) {
    updater = createUpdater({
      log, feedBase, appDistDir,
      notify: (status) => sendToWindow("js-update:changed", status),
    });
  } else log("update", "no relay configured - desktop OTA dormant\n");
}
ipcMain.handle("js-update:get", () => (updater ? updater.getStatus() : { state: "current", version: null, message: null }));
// The staged bundle is already downloaded + sha256-verified (updater.js
// stage()); applying it just swaps the directory. A JS bundle swap alone
// doesn't hot-reload the running window, so this restarts the whole app -
// same shape as the native updater's "restart & install now" button.
ipcMain.on("js-update:apply-now", () => {
  if (!updater || !updater.applyStagedNow()) return;
  app.relaunch();
  app.exit(0);
});

const { createNativeUpdater } = require("./native-updater");
const nativeUpdater = createNativeUpdater({
  log, isPackaged: app.isPackaged && !isMas,
  notify: (status) => sendToWindow("native-update:changed", status),
});
ipcMain.handle("native-update:get", () => nativeUpdater.getStatus());
ipcMain.on("native-update:install", () => nativeUpdater.quitAndInstall());

// find a working Python 3: probe candidates with `--version` and use the first
// that runs, so we don't depend on `py` alone being on PATH.
//
// shell:true was the old default for every one of these spawns ("so the `py`
// launcher resolves"). That premise was wrong: py.exe/python.exe are real
// executables, and CreateProcess resolves a bare name via PATH natively - no
// shell needed. Worse, shell:true + an ARRAY of args on Windows does not
// quote for cmd.exe (Node only escapes args itself in the no-shell path);
// it naively joins them into one raw string. Handed a multi-word `-c` script
// this silently split it into separate shell tokens - the same BatBadBut
// class of bug that already bit claude.cmd (drivers._real_claude_exe).
// Found live 2026-08-14: the daemon ran fine every spawn (port answered,
// relay connected) but daemon.out.log never captured one line from any of
// them, direct writes to the same file worked fine, and a reboot (ruling
// out any lock/orphan-handle theory) changed nothing - the loss was inside
// the cmd.exe -> py.exe -> python.exe hop this shell:true caused, not the
// file. probeNoShell() below is now the default; shell:true survives only
// as a last-resort fallback for a PATH setup where CreateProcess itself
// can't find a bare name (unverified to ever be needed here, kept safe).
function probeVersion(cmd, args) {
  const { spawnSync } = require("child_process");
  // spawnSync NEVER throws on a missing executable - ENOENT comes back in
  // r.error with status null. The first cut of this fallback caught only
  // THROWN errors, so "py not on Electron's PATH" (the packaged app's normal
  // state) fell through to the cmd.exe probe on EVERY call - and while the
  // daemon was slow to boot, the setup screen's poll re-probed every ~3s,
  // popping a fresh visible console window each time (the ~28-window cascade,
  // 2026-08-14 17:01-17:03). The shell fallback exists ONLY for the exotic
  // case where CreateProcess can't resolve a bare name that cmd.exe can
  // (per-user App Paths registrations) - so only take it on ENOENT, never on
  // a real nonzero exit, and cache the whole resolution (below) so probing
  // happens once per app run, not once per status poll.
  const r = spawnSync(cmd, [...args, "--version"], { windowsHide: true });
  if (r.status === 0) return true;
  if (!r.error || r.error.code !== "ENOENT") return false;
  const r2 = spawnSync(cmd, [...args, "--version"], { shell: true, windowsHide: true });
  return r2.status === 0;
}

let _pyCache = null;
function resolvePython() {
  if (_pyCache) return _pyCache;
  const win = process.platform === "win32";
  const cands = win
    ? [["py", ["-3.12"]], ["py", ["-3"]], ["python", []], ["python3", []]]
    : [["python3", []], ["python", []]];
  for (const [cmd, args] of cands) {
    if (!probeVersion(cmd, args)) continue;
    const real = win ? realInterpreter(cmd, args) : null;
    _pyCache = real ? { cmd: real, args: [] } : { cmd, args };
    return _pyCache;
  }
  // no candidate answered - do NOT cache the guess, so a Python installed
  // after app start is picked up on the next call.
  return win ? { cmd: "py", args: ["-3.12"] } : { cmd: "python3", args: [] };
}

// Resolve THROUGH a launcher indirection (py.exe) to the real interpreter
// behind it, so the daemon spawns the actual python.exe directly - no shell
// hop, no launcher hop, argv passed exactly as given.
function realInterpreter(cmd, args) {
  const { spawnSync } = require("child_process");
  try {
    const r = spawnSync(cmd, [...args, "-c", "import sys; print(sys.executable)"],
      { windowsHide: true, encoding: "utf8" });
    const p = (r.stdout || "").trim();
    return p && require("fs").existsSync(p) ? p : null;
  } catch { return null; }
}

// Best-effort logging. In a packaged GUI app stdout may be a closed/broken
// pipe; a synchronous write then throws EPIPE, and an uncaught EPIPE in the
// main process crashes the whole app ("A JavaScript error occurred..."). Never
// let a log line take the process down - swallow write errors.
function log(tag, buf) {
  try { process.stdout.write("[" + tag + "] " + buf); } catch { /* broken pipe / closed stdout - ignore */ }
}

// Belt-and-suspenders: if the stdout/stderr streams themselves emit EPIPE
// asynchronously (or any stray error), don't let it become fatal.
for (const s of [process.stdout, process.stderr]) {
  if (s && typeof s.on === "function") s.on("error", () => { /* ignore pipe errors */ });
}

function fail(msg) {
  if (failed) return;
  failed = true;
  dialog.showErrorBox("HelmDeck", msg);
  cleanup();
  app.quit();
}

// `py` may be supplied by the setup flow (bundled/just-fetched runtime); without
// it we fall back to whatever the machine has. A failure here is NO LONGER fatal:
// first run is exactly the case where Python is missing, and the onboarding
// screen is what fixes it — killing the app would leave the user nowhere.
// Is a daemon already answering on :8140? ANY HTTP reply (even 401) means one is
// listening. Used to ADOPT it instead of spawning a second (Paseo probe-then-adopt).
// Retried: a single 1.2s shot raced a daemon that was busy or mid-restart and
// the miss spawned a SECOND daemon over the live one (SO_REUSEADDR lets both
// bind on Windows) - observed in the field. Three tries ~2.7s apart makes
// "there is a daemon, adopt it" the outcome of every transient blip; a real
// absence still resolves in under 3s of extra startup.
function daemonReachable(cb, tries = 3) {
  const miss = () => (tries > 1
    ? setTimeout(() => daemonReachable(cb, tries - 1), 700)
    : cb(false));
  const req = http.get({ host: "127.0.0.1", port: DAEMON_PORT, path: "/tracks", timeout: 2000 },
    (r) => { r.destroy(); cb(true); });
  req.on("error", miss);
  req.on("timeout", function () { this.destroy(); miss(); });
}

function startDaemon(pyOverride) {
  // ADOPT-OR-DETACH (Paseo daemon-manager parity). The daemon holds the phone's
  // relay bridge, so it must NOT be bound to this desktop window's lifecycle:
  //  1) if one is already reachable (a prior detached session, a relaunch, a
  //     CLI-started daemon) -> ADOPT it, never spawn a second or evict it;
  //  2) else spawn it DETACHED + unref -> it keeps its own process group, so a
  //     crash or tree-kill of Electron can never take the phone offline, and it
  //     survives a normal window close too (see cleanup()).
  daemonReachable((up) => {
    if (up) {
      daemonAdopted = true;
      log("daemon", "adopted an already-running daemon on :" + DAEMON_PORT + " (not spawning)\n");
      return;
    }
    const py = pyOverride || resolvePython();
    const fs = require("fs");
    // detached needs a real sink, not an inherited pipe that dies with Electron -
    // append to a log file so the daemon is fully independent yet still logged.
    // openSync can hit a transient sharing violation (AV/indexer briefly
    // holding the file, or the just-evicted prior daemon's handle not yet
    // released) - silently falling back to "ignore" on the FIRST try meant a
    // healthy daemon could run its whole life with zero captured output.
    // Retry a few times before giving up. If the canonical name STILL won't
    // open (a lingering process holding it in a mode that denies new opens,
    // outliving the process that set it - not just a transient AV/indexer
    // brush) fall back to a PID-suffixed file instead of losing capture for
    // this whole run: a frozen canonical log with an unrelated pinned handle
    // must not silence every daemon start until a reboot clears the pin.
    let out = "ignore", usedPath = null;
    const logPath = path.join(daemonDir, "daemon.out.log");
    const fallbackPath = path.join(daemonDir, "daemon.out." + process.pid + ".log");
    let openErr = null;
    for (const candidate of [logPath, fallbackPath]) {
      openErr = null;
      for (let i = 0; i < 5; i++) {
        try { out = fs.openSync(candidate, "a"); openErr = null; usedPath = candidate; break; }
        catch (e) { openErr = e; }
        const until = Date.now() + 150;
        while (Date.now() < until) { /* short synchronous backoff */ }
      }
      if (!openErr) break;
    }
    if (openErr) {
      log("daemon", "could not open daemon.out.log OR its PID fallback - "
        + "output NOT captured: " + openErr.message + "\n");
    } else if (usedPath === fallbackPath) {
      log("daemon", "daemon.out.log unavailable (held by another process) - "
        + "logging to " + fallbackPath + " instead\n");
    }
    // shell:true only when py.cmd is still a bare launcher name (resolvePython
    // couldn't resolve the real interpreter) - a real absolute exe path spawns
    // directly, which also removes the cmd.exe hop that was swallowing this
    // process's stdout/stderr (see resolvePython/realInterpreter above).
    const daemonNeedsShell = process.platform === "win32" && !path.isAbsolute(py.cmd);
    // daemon/ is a real Python package now (absolute spine/
    // cells.<id> imports) - launched as a module from the REPO
    // ROOT, not a bare script from inside daemon/ (daemon/debt.py
    // sys-path-trick-to-real-package-imports). swarm.py itself stays put.
    daemon = spawn(py.cmd, [...py.args, "-m", "daemon.swarm", "serve", String(DAEMON_PORT)],
      // PYTHONUNBUFFERED: a written line survives even an abrupt taskkill /F
      // (SINGLETON eviction, a competing supervisor) - no flush window needed.
      // cwd is daemonDir's PARENT (not the top-level `root` const) so a
      // resolveDaemonDir() override (userData daemon-dir.txt pointing at a
      // dev checkout) still resolves `daemon` as a package from the right
      // place, exactly like the bundled case.
      { cwd: path.dirname(daemonDir), env: { ...process.env, PYTHONUNBUFFERED: "1" }, windowsHide: true,
        shell: daemonNeedsShell, detached: true,
        stdio: ["ignore", out, out] });
    daemon.on("error", (e) => log("daemon", "start failed: " + e.message + "\n"));
    daemon.unref();   // let Electron exit without waiting on / tethering the daemon
  });
}

// mintDesktopToken() lived here and is deliberately GONE (see the note at the
// top). spine/auth/mint_token.py itself stays - it is still a legitimate operator
// tool for provisioning a device token by hand - but nothing in the desktop
// shell calls it any more, so no credential-free owner session is handed out.

// Serve the exported SPA locally with index.html fallback for client-side routes.
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml",
  ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".ico": "image/x-icon", ".map": "application/json" };
function startWeb() {
  const fs = require("fs");
  web = http.createServer((req, res) => {
    let p = decodeURIComponent(req.url.split("?")[0].split("#")[0]);
    let file = path.join(appDistDir, p);
    if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      const idx = path.join(appDistDir, p, "index.html");
      file = fs.existsSync(idx) ? idx : path.join(appDistDir, "index.html"); // SPA fallback
    }
    fs.readFile(file, (err, buf) => {
      if (err) { res.writeHead(404); return res.end("not found"); }
      // NEVER cache the SPA shell. Without this, Electron heuristically caches
      // index.html to disk and serves a STALE bundle after an app-dist refresh -
      // so a shipped fix silently never reaches the window even across restarts
      // (the "auf dem Desktop kommt nichts an" class). Hashed JS/CSS assets carry
      // a content hash in their filename, so they are safe (in fact good) to
      // cache; only the entry documents must always be revalidated.
      const ext = path.extname(file);
      const noStore = ext === ".html" || ext === ".json" || ext === "";
      res.writeHead(200, {
        "Content-Type": MIME[ext] || "application/octet-stream",
        "Cache-Control": noStore ? "no-store, must-revalidate" : "public, max-age=31536000, immutable",
      });
      res.end(buf);
    });
  });
  web.on("error", (e) => fail("Could not start the UI server.\n\n" + e.message));
  web.listen(WEB_PORT, "127.0.0.1");
}

function waitForWeb(cb, tries = 90) {
  const ping = () => {
    http.get({ host: "localhost", port: WEB_PORT, path: "/", timeout: 2000 }, (r) => { r.destroy(); cb(); })
      .on("error", () => { if (--tries <= 0) fail("Timed out waiting for the UI to start."); else setTimeout(ping, 1000); })
      .on("timeout", function () { this.destroy(); });
  };
  ping();
}

function createWindow() {
  if (failed) return;
  win = new BrowserWindow({
    width: 1360, height: 900, title: "HelmDeck", backgroundColor: "#0b0f14",
    // taskbar/window: the fanned-card mark. macOS ignores this entirely (the
    // Dock icon comes from the .app bundle's .icns) and a .ico is not a format
    // it can read, so don't hand it one.
    ...(process.platform === "darwin"
      ? {}
      : { icon: path.join(__dirname, "assets", "icon.ico") }),
    autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, preload: path.join(__dirname, "preload.js") },
  });
  // Hand the Expo web app the daemon URL via the URL hash (config.ts reads
  // #cfg). NO token: the SPA logs in like any other client and keeps its own
  // session. `setup` hands the SPA the loopback control endpoint + its
  // per-launch nonce, so the onboarding screen can provision the machine while
  // the daemon is down.
  const cfg = Buffer.from(JSON.stringify({
    baseUrl: "http://localhost:" + DAEMON_PORT,
    setup: setupSrv ? { port: setupSrv.port, nonce: setupSrv.nonce } : undefined,
  })).toString("base64");
  // ?v=<launch time> busts any residual disk cache so a refreshed app-dist is
  // ALWAYS what the window loads (belt-and-suspenders with the no-store header).
  win.loadURL("http://localhost:" + WEB_PORT + "/?v=" + Date.now() + "#cfg=" + encodeURIComponent(cfg));
  // open external links in the real browser, not a new Electron window
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: "deny" }; });
  win.on("closed", () => { win = null; });
}

function killTree(proc) {
  if (!proc || !proc.pid || proc.killed) return;
  try {
    if (process.platform === "win32") spawn("taskkill", ["/pid", String(proc.pid), "/T", "/F"]);
    else proc.kill("SIGTERM");
  } catch { /* ignore */ }
}
function cleanup() {
  // LEAVE THE DAEMON RUNNING. It is detached and holds the phone's relay bridge,
  // so closing the desktop window must not take the phone offline (Paseo only
  // stops a *managed* daemon on quit; ours stays a background service the phone
  // depends on, and an adopted daemon was never ours to stop). A relaunch
  // adopts it. Only the local UI server + setup control plane are ours to close.
  killTree(web); web = null;
  if (setupSrv) { setupSrv.close(); setupSrv = null; }
}

// Single-instance lock: the daemon is the phone's ONLY way in (it holds the
// relay bridge). A second launch would spawn a SECOND daemon on the same room,
// and the two would fight over every phone frame - so refuse to start twice and
// just focus the window that already owns the port.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (win) { if (win.isMinimized()) win.restore(); win.focus(); }
    else if (!failed) createWindow();
  });

  app.whenReady().then(() => {
    // Auto-start at login so the daemon + relay bridge are up whenever the
    // machine is - otherwise the phone shows "Desktop nicht erreichbar" until
    // someone opens the app by hand. Only the packaged build registers itself
    // (a dev `electron .` run must not wire the dev binary into startup).
    if (app.isPackaged) {
      try {
        // On macOS the login item IS the .app bundle, registered by the OS -
        // handing it process.execPath (the helper binary buried in
        // Contents/MacOS) registers a path the user cannot recognise and
        // Ventura+ may refuse. openAtLogin alone is the supported form there.
        app.setLoginItemSettings(process.platform === "darwin"
          ? { openAtLogin: true }
          : { openAtLogin: true, path: process.execPath, args: [] });
      } catch { /* non-fatal: startup registration is a convenience, not required */ }
    }
    // The onboarding control plane comes up FIRST and always: it is what the
    // screen talks to when Python/Claude/the daemon are not there yet.
    setupSrv = startSetupServer({
      resourcesDir: root, daemonDir, daemonPort: DAEMON_PORT,
      startDaemon: (py) => startDaemon(py),
    });
    startDaemon();
    // A verified staged bundle (own download, or one the tray staged while the
    // window was closed) lands BEFORE the web server starts, so this launch
    // already serves it - the launch half of the phone's expo-updates flow.
    if (updater) updater.applyStagedAtStartup();
    startWeb();
    waitForWeb(createWindow);
    if (updater) updater.start();   // silent check now, then every 30 min (UI bundle)
    nativeUpdater.start();          // silent check now, then every 30 min (whole app)
    app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0 && !failed) createWindow(); });
  });
}

// macOS keeps an app alive with no windows (the Dock icon stays lit, Cmd-Q or
// the Dock quits it) and the "activate" handler above already re-opens the
// window. Quitting on last-window-close there would be un-Mac-like AND would
// make the tray-less Mac build unreachable after one accidental red button.
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
// Paseo quit lifecycle (main.ts + quit-lifecycle.ts): when a downloaded update
// is staged, hold the first quit, revalidate it against the feed within the 5s
// deadline, swap it in silently (no forced relaunch), then really exit. With
// nothing staged the quit is untouched.
let quittingForUpdate = false;
app.on("before-quit", (e) => {
  if (quittingForUpdate || !updater || !updater.hasStage()) return;
  quittingForUpdate = true;
  e.preventDefault();
  updater.applyOnQuit().catch(() => false).then(() => app.exit(0));
});
app.on("before-quit", cleanup);
process.on("exit", cleanup);
