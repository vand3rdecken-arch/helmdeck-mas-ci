// HelmDeck desktop (Electron wrapper) - modeled on Paseo's packages/desktop.
// On launch it starts the local services and shows the UI in a native window:
//   - the Python daemon (swarm.py serve) on :8140  (the brain + runner)
//   - the Next.js server on :3300 (the UI, proxies /backend/* to the daemon)
// then loads http://localhost:3300 in a BrowserWindow. On quit it kills both.
//
// Requirements on the user's machine (same as HelmDeck itself):
//   - Python 3.12 (the `py -3.12` launcher on Windows, or `python3`)
//   - the `claude` CLI (Claude Code) - the agent runtime cards execute in
const { app, BrowserWindow, dialog, shell } = require("electron");
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

// packaged: resources/{daemon,app-dist}; dev: repo ../{daemon,app/dist}
const root = app.isPackaged ? process.resourcesPath : path.join(__dirname, "..");
// THE REAL BRAIN pointer. The packaged install ships its own daemon COPY under
// resources/daemon - a fresh state dir with no relay pairing, no users.json and
// stale code. Spawning THAT (when the adopt probe missed) put a sandbox brain
// on :8140: the phone's room was never polled and the minted token was invalid
// against the real daemon - "Desktop nicht erreichbar" on both ends. One state
// dir must be the single owner, so resources/daemon-dir.txt (one line: the
// absolute path of the real daemon dir) redirects spawn AND token mint there;
// only a dir that actually contains swarm.py is accepted, else fall back to
// the bundled copy (a fresh install with no pointer keeps working).
function resolveDaemonDir() {
  const bundled = path.join(root, "daemon");
  try {
    const fs = require("fs");
    const p = fs.readFileSync(path.join(root, "daemon-dir.txt"), "utf8").trim();
    if (p && fs.existsSync(path.join(p, "swarm.py"))) return p;
    if (p) log("daemon", "daemon-dir.txt points at '" + p + "' but no swarm.py there - using the bundled copy\n");
  } catch { /* no pointer file: bundled copy */ }
  return bundled;
}
const daemonDir = resolveDaemonDir();
// The UI is now the single Expo/React-Native web export (expo export --platform
// web), replacing the old Next.js server. Same static SPA that ships to the
// phone/web; the desktop just serves it locally and points it at the daemon.
const appDistDir = app.isPackaged ? path.join(root, "app-dist") : path.join(__dirname, "..", "app", "dist");
let desktopToken = "";

// Auto-update (Paseo mechanism, see updater.js): packaged builds silently
// follow the relay's "desktop" OTA channel - check at start + every 30 min,
// download + verify in the background, swap in on quit. Dev runs are exempt
// exactly like Paseo ("Auto-update is not available in development mode").
let updater = null;
if (app.isPackaged) {
  const { createUpdater, readRelayUrl } = require("./updater");
  const feedBase = readRelayUrl(path.join(daemonDir, "settings.json"));
  if (feedBase) updater = createUpdater({ feedBase, appDistDir, log });
  else log("update", "no relay configured - desktop OTA dormant\n");
}

// find a working Python 3: probe candidates with `--version` and use the first
// that runs, so we don't depend on `py` alone being on PATH.
function resolvePython() {
  const { spawnSync } = require("child_process");
  const win = process.platform === "win32";
  const cands = win
    ? [["py", ["-3.12"]], ["py", ["-3"]], ["python", []], ["python3", []]]
    : [["python3", []], ["python", []]];
  for (const [cmd, args] of cands) {
    try {
      const r = spawnSync(cmd, [...args, "--version"], { shell: win, windowsHide: true });
      if (r.status === 0) return { cmd, args };
    } catch { /* try next */ }
  }
  return win ? { cmd: "py", args: ["-3.12"] } : { cmd: "python3", args: [] };
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
    let out = "ignore";
    try { out = fs.openSync(path.join(daemonDir, "daemon.out.log"), "a"); } catch { /* ignore */ }
    // shell:true on Windows so the `py` launcher resolves (bare spawn -> ENOENT)
    daemon = spawn(py.cmd, [...py.args, "swarm.py", "serve", String(DAEMON_PORT)],
      { cwd: daemonDir, env: { ...process.env }, windowsHide: true,
        shell: process.platform === "win32", detached: true,
        stdio: ["ignore", out, out] });
    daemon.on("error", (e) => log("daemon", "start failed: " + e.message + "\n"));
    daemon.unref();   // let Electron exit without waiting on / tethering the daemon
  });
}

// Mint a device token from the local daemon so the served Expo web UI can talk
// to it with the same Bearer-token auth the phone uses (no daemon auth weakening,
// no cookie coupling). Best-effort: the UI still loads if this fails (shows the
// connect screen). Owner-scoped, same-machine only.
function mintDesktopToken(pyOverride) {
  const { spawnSync } = require("child_process");
  const py = pyOverride || resolvePython();
  try {
    // a helper script (not `-c`) so Windows shell quoting can't mangle it
    const r = spawnSync(py.cmd, [...py.args, "mint_token.py", "owner", "desktop"],
      { cwd: daemonDir, shell: process.platform === "win32", windowsHide: true, encoding: "utf8" });
    if (r.status === 0 && r.stdout) desktopToken = r.stdout.trim();
  } catch { /* leave empty */ }
}

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
    icon: path.join(__dirname, "assets", "icon.ico"),   // taskbar/window: the fanned-card mark
    autoHideMenuBar: true, webPreferences: { contextIsolation: true },
  });
  // hand the Expo web app the daemon URL + a device token via the URL hash, so
  // it connects with Bearer auth exactly like the phone (config.ts reads #cfg).
  // `setup` hands the SPA the loopback control endpoint + its per-launch nonce,
  // so the onboarding screen can provision the machine while the daemon is down.
  const cfg = Buffer.from(JSON.stringify({
    baseUrl: "http://localhost:" + DAEMON_PORT, token: desktopToken,
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
        app.setLoginItemSettings({ openAtLogin: true, path: process.execPath, args: [] });
      } catch { /* non-fatal: startup registration is a convenience, not required */ }
    }
    // The onboarding control plane comes up FIRST and always: it is what the
    // screen talks to when Python/Claude/the daemon are not there yet.
    setupSrv = startSetupServer({
      resourcesDir: root, daemonDir, daemonPort: DAEMON_PORT,
      startDaemon: (py) => startDaemon(py),
      mintToken: (py) => { mintDesktopToken(py); return desktopToken; },
    });
    startDaemon();
    mintDesktopToken();   // issue a device token for the served web UI
    // A verified staged bundle (own download, or one the tray staged while the
    // window was closed) lands BEFORE the web server starts, so this launch
    // already serves it - the launch half of the phone's expo-updates flow.
    if (updater) updater.applyStagedAtStartup();
    startWeb();
    waitForWeb(createWindow);
    if (updater) updater.start();   // silent check now, then every 30 min
    app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0 && !failed) createWindow(); });
  });
}

app.on("window-all-closed", () => app.quit());
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
