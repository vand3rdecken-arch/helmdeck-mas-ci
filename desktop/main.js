// SwarmDeck desktop (Electron wrapper) - modeled on Paseo's packages/desktop.
// On launch it starts the local services and shows the UI in a native window:
//   - the Python daemon (swarm.py serve) on :8140  (the brain + runner)
//   - the Next.js server on :3300 (the UI, proxies /backend/* to the daemon)
// then loads http://localhost:3300 in a BrowserWindow. On quit it kills both.
//
// Requirements on the user's machine (same as SwarmDeck itself):
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

const DAEMON_PORT = 8140;
const WEB_PORT = 3300;
let daemon = null, web = null, win = null, failed = false;

// packaged: resources/{daemon,app-dist}; dev: repo ../{daemon,app/dist}
const root = app.isPackaged ? process.resourcesPath : path.join(__dirname, "..");
const daemonDir = path.join(root, "daemon");
// The UI is now the single Expo/React-Native web export (expo export --platform
// web), replacing the old Next.js server. Same static SPA that ships to the
// phone/web; the desktop just serves it locally and points it at the daemon.
const appDistDir = app.isPackaged ? path.join(root, "app-dist") : path.join(__dirname, "..", "app", "dist");
let desktopToken = "";

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
  dialog.showErrorBox("SwarmDeck", msg);
  cleanup();
  app.quit();
}

function startDaemon() {
  const py = resolvePython();
  // shell:true on Windows so the `py` launcher resolves (bare spawn -> ENOENT)
  daemon = spawn(py.cmd, [...py.args, "swarm.py", "serve", String(DAEMON_PORT)],
    { cwd: daemonDir, env: { ...process.env }, windowsHide: true, shell: process.platform === "win32" });
  daemon.stdout.on("data", (d) => log("daemon", d));
  daemon.stderr.on("data", (d) => log("daemon", d));
  daemon.on("error", (e) =>
    fail("Could not start the Python daemon. Install Python 3.12 and make sure "
      + "the `claude` CLI is available.\n\n" + e.message));
}

// Mint a device token from the local daemon so the served Expo web UI can talk
// to it with the same Bearer-token auth the phone uses (no daemon auth weakening,
// no cookie coupling). Best-effort: the UI still loads if this fails (shows the
// connect screen). Owner-scoped, same-machine only.
function mintDesktopToken() {
  const { spawnSync } = require("child_process");
  const py = resolvePython();
  try {
    const r = spawnSync(py.cmd,
      [...py.args, "-c", "import auth,sys; sys.stdout.write(auth.issue_token('owner','desktop'))"],
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
      res.writeHead(200, { "Content-Type": MIME[path.extname(file)] || "application/octet-stream" });
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
    width: 1360, height: 900, title: "SwarmDeck", backgroundColor: "#0b0f14",
    icon: path.join(__dirname, "assets", "icon.ico"),   // taskbar/window: the fanned-card mark
    autoHideMenuBar: true, webPreferences: { contextIsolation: true },
  });
  // hand the Expo web app the daemon URL + a device token via the URL hash, so
  // it connects with Bearer auth exactly like the phone (config.ts reads #cfg).
  const cfg = Buffer.from(JSON.stringify({ baseUrl: "http://localhost:" + DAEMON_PORT, token: desktopToken })).toString("base64");
  win.loadURL("http://localhost:" + WEB_PORT + "/#cfg=" + encodeURIComponent(cfg));
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
function cleanup() { killTree(daemon); killTree(web); daemon = web = null; }

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
    startDaemon();
    mintDesktopToken();   // issue a device token for the served web UI
    startWeb();
    waitForWeb(createWindow);
    app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0 && !failed) createWindow(); });
  });
}

app.on("window-all-closed", () => app.quit());
app.on("before-quit", cleanup);
process.on("exit", cleanup);
