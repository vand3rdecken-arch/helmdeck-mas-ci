// ONBOARDING CONTROL PLANE (desktop only).
//
// The promise: one screen, one button. The user connects Claude Code; from that
// point HelmDeck provisions ITSELF and ends on a pairing QR.
//
// This lives in the Electron main process, NOT the daemon, because at first run
// the daemon is exactly what does not exist yet: no Python, no dependencies, no
// owner token. The SPA is served locally (main.js startWeb) and loads fine with
// a dead daemon, so it talks to this tiny loopback control server instead.
//
// Design rules:
//   - 127.0.0.1 only, and a per-launch nonce in the URL. This endpoint can start
//     processes; it must never be reachable from the LAN or from a stray page.
//   - Every step is IDEMPOTENT and re-entrant: the screen may be reloaded, the
//     button pressed twice, the app restarted mid-way.
//   - Claude Code is the installer. Once `claude` is present and authenticated,
//     anything still missing is handed to it as a task rather than reimplemented
//     here as a bespoke installer per dependency.
//   - Python: prefer bundled, then system, else FETCH the embeddable runtime
//     (~11 MB). The daemon is stdlib-only, so that is all it needs to run.
const { spawn, spawnSync } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const https = require("https");
const path = require("path");

const PORT = 8141;
const PY_EMBED_URL = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip";

const nonce = crypto.randomBytes(16).toString("hex");
const log = [];          // progress lines the screen renders
let running = false;     // provisioning in flight
let done = false;

function say(line, kind = "info") {
  log.push({ ts: Date.now(), kind, line: String(line) });
  if (log.length > 400) log.shift();
}

// ---------------------------------------------------------------- probes ---

const win = process.platform === "win32";

/** The env every provisioning child gets. A GUI-launched Electron can carry a
 *  PATH missing the core Windows dirs (same trap the daemon fixes for itself in
 *  server.py _hydrate_windows_path): then `where`, `cmd`, `powershell` and the
 *  npm shims silently stop resolving and every probe "fails" on a healthy
 *  machine. Hydrate once, use everywhere - setup must be reproducible however
 *  the app was started. */
function hydratedEnv() {
  const env = { ...process.env };
  if (!win) return env;
  const root = env.SystemRoot || "C:\\Windows";
  const want = [path.join(root, "System32"), root,
    path.join(root, "System32", "WindowsPowerShell", "v1.0")];
  const parts = (env.Path || env.PATH || "").split(path.delimiter).filter(Boolean);
  const have = new Set(parts.map((p) => p.toLowerCase()));
  for (const d of want) {
    if (!have.has(d.toLowerCase()) && fs.existsSync(d)) parts.push(d);
  }
  env.Path = parts.join(path.delimiter);
  return env;
}

const runQ = (cmd, args, opts = {}) => {
  try {
    return spawnSync(cmd, args, { shell: win, windowsHide: true, encoding: "utf8", timeout: 20000, env: hydratedEnv(), ...opts });
  } catch (e) {
    return { status: 1, stdout: "", stderr: String(e && e.message) };
  }
};

/** Absolute locations to try when PATH lets us down. A GUI-launched app does not
 *  inherit the user's login-shell PATH (the single most common first-run failure
 *  — Paseo solves it with inheritLoginShellEnv(); on Windows the pragmatic
 *  equivalent is to look where these things actually live). */
function pythonFallbacks() {
  if (!win) return ["/usr/bin/python3", "/usr/local/bin/python3", "/opt/homebrew/bin/python3"];
  const local = process.env.LOCALAPPDATA || "";
  const pf = process.env.ProgramFiles || "C:\\Program Files";
  const out = [path.join(process.env.SystemRoot || "C:\\Windows", "py.exe")];
  for (const v of ["312", "313", "311"]) {
    if (local) out.push(path.join(local, "Programs", "Python", "Python" + v, "python.exe"));
    out.push(path.join(pf, "Python" + v, "python.exe"));
  }
  return out;
}

/** Bundled runtime first (installer ships it), then PATH, then known locations. */
function findPython(resourcesDir) {
  const bundled = path.join(resourcesDir, "python", win ? "python.exe" : "bin/python3");
  if (fs.existsSync(bundled)) return { cmd: bundled, args: [], bundled: true };
  const cands = win
    ? [["py", ["-3.12"]], ["py", ["-3"]], ["python", []], ["python3", []]]
    : [["python3", []], ["python", []]];
  for (const [cmd, args] of cands) {
    const r = runQ(cmd, [...args, "--version"]);
    if (r.status === 0) return { cmd, args, bundled: false };
  }
  for (const abs of pythonFallbacks()) {
    if (!fs.existsSync(abs)) continue;
    const args = abs.toLowerCase().endsWith("py.exe") ? ["-3.12"] : [];
    const r = runQ(`"${abs}"`, [...args, "--version"]);
    if (r.status === 0) return { cmd: `"${abs}"`, args, bundled: false };
  }
  return null;
}

function findClaude() {
  const explicit = process.env.HELMDECK_CLAUDE;
  const cands = explicit ? [explicit] : ["claude"];
  for (const c of cands) {
    const r = runQ(c, ["--version"]);
    if (r.status === 0) return { cmd: c, version: (r.stdout || "").trim() };
  }
  // Windows npm global installs land as claude.cmd and are not always on PATH
  const guess = path.join(process.env.ProgramFiles || "C:\\Program Files", "nodejs", "claude.cmd");
  if (fs.existsSync(guess)) {
    const r = runQ(guess, ["--version"]);
    if (r.status === 0) return { cmd: guess, version: (r.stdout || "").trim() };
  }
  return null;
}

/** Absolute path of a PATH-resolved command, or null. Needed because `claude`
 *  found via runQ("claude", …) is a bare name - to see through the .cmd shim
 *  (below) we need to know which directory it actually lives in. */
function whichWin(cmd) {
  const r = runQ("where", [cmd]);
  if (r.status !== 0) return null;
  return (r.stdout || "").split(/\r?\n/).map((s) => s.trim()).find(Boolean) || null;
}

/** The real executable behind an npm `claude.cmd` shim, or null.
 *
 * THE SILENT CONTEXT KILLER (daemon/spine/agent/agentcli.py::_real_claude_exe,
 * fixed there in ea09780, never ported here): spawning claude.cmd via
 * `cmd /s /c "<argv>"` - which is what { shell: win } does on Windows - is not
 * quote-safe. cmd.exe's escaping plus the shim's own %* re-parse shifts
 * argument boundaries on anything long/punctuation-heavy (parens, periods),
 * and args get swallowed - reproduced live: a multi-sentence diagnose prompt
 * arrived at Claude as just "The". Resolve what the shim points at (npm
 * layout: <dir>\node_modules\@anthropic-ai\claude-code\bin\claude.exe, or
 * cli.js + node.exe for older installs) and spawn THAT as a plain argv list -
 * CreateProcess/CommandLineToArgvW quote it correctly, no shell involved. */
function realClaudeExe(cmdPath) {
  if (!cmdPath) return null;
  const d = path.dirname(path.resolve(cmdPath));
  const exe = path.join(d, "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe");
  if (fs.existsSync(exe)) return [exe];
  const js = path.join(d, "node_modules", "@anthropic-ai", "claude-code", "cli.js");
  const node = path.join(d, "node.exe");
  if (fs.existsSync(js) && fs.existsSync(node)) return [node, js];
  return null;
}

/** Spawn form for `claude`: { cmd, prefixArgs, useShell }. Prefers the
 *  resolved real executable (plain argv, no shell, quote-safe); falls back to
 *  the shim through a shell only when we cannot see through it. */
function resolveClaudeSpawn(claude) {
  if (!win) return { cmd: claude.cmd, prefixArgs: [], useShell: false };
  const abs = path.isAbsolute(claude.cmd) ? claude.cmd : whichWin(claude.cmd);
  const isShim = abs && /\.(cmd|bat)$/i.test(abs);
  const real = isShim ? realClaudeExe(abs) : null;
  if (real) return { cmd: real[0], prefixArgs: real.slice(1), useShell: false };
  return { cmd: claude.cmd, prefixArgs: [], useShell: win };
}

/** Authenticated == a trivial non-interactive prompt returns without an auth
 *  error. `claude -p` exits non-zero and says so when the user is logged out. */
function claudeAuthed(claude) {
  if (!claude) return false;
  const r = runQ(claude.cmd, ["-p", "reply with: ok"], { timeout: 60000 });
  const out = ((r.stdout || "") + (r.stderr || "")).toLowerCase();
  if (/not logged in|unauthor|authenticate|login|invalid api key|no api key/.test(out)) return false;
  return r.status === 0;
}

function daemonUp(port) {
  return new Promise((res) => {
    const req = http.get({ host: "127.0.0.1", port, path: "/tracks", timeout: 1500 }, (r) => {
      r.resume();                       // 200 or 401 both prove it is listening
      res(r.statusCode > 0);
    });
    req.on("error", () => res(false));
    req.on("timeout", () => { req.destroy(); res(false); });
  });
}

// ------------------------------------------------------------ provisioning ---

function download(url, dest, redirects = 0) {
  return new Promise((resolve, reject) => {
    if (redirects > 5) return reject(new Error("too many redirects"));
    https.get(url, (r) => {
      if (r.statusCode >= 300 && r.statusCode < 400 && r.headers.location) {
        r.resume();
        return resolve(download(r.headers.location, dest, redirects + 1));
      }
      if (r.statusCode !== 200) { r.resume(); return reject(new Error("HTTP " + r.statusCode)); }
      const f = fs.createWriteStream(dest);
      r.pipe(f);
      f.on("finish", () => f.close(() => resolve(dest)));
      f.on("error", reject);
    }).on("error", reject);
  });
}

/** Fetch + unpack the embeddable CPython next to our resources. Only reached
 *  when the installer did not bundle it and the machine has no Python. */
async function fetchPython(resourcesDir) {
  const target = path.join(resourcesDir, "python");
  const zip = path.join(resourcesDir, "python-embed.zip");
  say("Lade Python-Laufzeit (~11 MB)…");
  await download(PY_EMBED_URL, zip);
  fs.mkdirSync(target, { recursive: true });
  // PowerShell is always present on Windows; avoids shipping an unzip dependency.
  const r = runQ("powershell", ["-NoProfile", "-Command",
    `Expand-Archive -Path '${zip}' -DestinationPath '${target}' -Force`], { timeout: 120000 });
  try { fs.unlinkSync(zip); } catch { /* leave it */ }
  if (r.status !== 0) throw new Error("Entpacken fehlgeschlagen: " + (r.stderr || "").trim());
  say("Python-Laufzeit bereit.", "ok");
  return findPython(resourcesDir);
}

/** Hand a job to Claude Code. This is the "use Claude to install" step: rather
 *  than hand-rolling an installer per dependency we describe the goal and let
 *  the agent do it on the user's machine, streaming its output to the screen. */
function claudeTask(claude, prompt, cwd, mode = "plan") {
  return new Promise((resolve) => {
    say("Claude richtet ein…");
    // `plan` is READ-ONLY: onboarding may diagnose freely, but it must never
    // silently rewrite the user's HelmDeck installation. Only the step that
    // genuinely has to change the machine (installing a runtime) gets more.
    const { cmd, prefixArgs, useShell } = resolveClaudeSpawn(claude);
    const p = spawn(cmd, [...prefixArgs, "-p", prompt, "--permission-mode", mode],
      { cwd, shell: useShell, windowsHide: true, env: hydratedEnv() });
    let tail = "";
    const onData = (d) => {
      tail += d.toString();
      const lines = tail.split("\n");
      tail = lines.pop() || "";
      for (const l of lines) if (l.trim()) say(l.trim());
    };
    p.stdout.on("data", onData);
    p.stderr.on("data", onData);
    p.on("close", (code) => { if (tail.trim()) say(tail.trim()); resolve(code === 0); });
    p.on("error", (e) => { say("Claude ließ sich nicht starten: " + e.message, "err"); resolve(false); });
  });
}

// ------------------------------------------------------------------ server ---

/**
 * @param ctx {{ resourcesDir, daemonDir, daemonPort, startDaemon }}
 *   startDaemon(py) -> void   (main.js owns the child process + teardown)
 *
 * There is deliberately no mintToken any more. Provisioning used to finish by
 * minting an owner device token and handing it to the SPA - the same
 * credential-free owner login the shell itself used to perform, through a second
 * door. Provisioning installs an INSTANCE; WHO may drive it is settled by
 * logging in. On a genuinely fresh machine no owner account exists yet, so the
 * SPA shows its create-owner screen, which is the only correct answer there.
 */
function startSetupServer(ctx) {
  // Probe results are CACHED once positive: /setup/state is polled every few
  // seconds by the connect screen, and findPython/findClaude shell out per
  // candidate on every call - during a slow daemon boot (a 60-90s worktree
  // sweep, seen live 2026-08-14) that spawned a fresh console window every
  // ~3s, cascading ~28 windows across the desktop. A found runtime doesn't
  // un-install mid-run; a MISSING one is re-probed (so installing Python
  // while the setup screen is open is still picked up on the next poll).
  let _pyProbe = null, _claudeProbe = null;
  const state = async () => {
    const py = _pyProbe || (_pyProbe = findPython(ctx.resourcesDir));
    const claude = _claudeProbe || (_claudeProbe = findClaude());
    return {
      python: !!py, pythonBundled: !!(py && py.bundled),
      claude: !!claude, claudeVersion: claude ? claude.version : "",
      daemon: await daemonUp(ctx.daemonPort),
      running, done,
    };
  };

  async function provision() {
    if (running) return;
    running = true; done = false;
    try {
      // 1) Claude Code — the one thing the user must own. We never install it
      //    silently: it needs their account.
      let claude = findClaude();
      if (!claude) {
        say("Claude Code ist nicht installiert.", "err");
        say("Installiere es und starte HelmDeck neu: npm i -g @anthropic-ai/claude-code", "hint");
        return;
      }
      say("Claude Code gefunden: " + (claude.version || "ok"), "ok");
      if (!claudeAuthed(claude)) {
        say("Claude Code ist nicht angemeldet.", "err");
        say("Führe im Terminal `claude` aus, melde dich an, dann hier erneut starten.", "hint");
        return;
      }
      say("Claude ist angemeldet.", "ok");

      // 2) Runtime for the daemon (stdlib-only, so the embeddable build suffices)
      let py = findPython(ctx.resourcesDir);
      if (!py) {
        say("Keine Python-Laufzeit gefunden.");
        try { py = await fetchPython(ctx.resourcesDir); }
        catch (e) {
          say("Download fehlgeschlagen: " + e.message, "err");
          say("Ich lasse Claude es übernehmen…");
          await claudeTask(claude,
            "Install a Python 3.12 runtime on this Windows machine so that `py -3.12 --version` "
            + "works, using winget if available. Do not modify anything else. Report what you did.",
            ctx.daemonDir, "acceptEdits");   // this step must actually change the machine
          py = findPython(ctx.resourcesDir);
        }
      }
      if (!py) { say("Ohne Python-Laufzeit kann der Daemon nicht starten.", "err"); return; }
      say("Python-Laufzeit bereit.", "ok");

      // 3) Instance
      if (!(await daemonUp(ctx.daemonPort))) {
        say("Starte HelmDeck-Instanz…");
        ctx.startDaemon(py);
        for (let i = 0; i < 40 && !(await daemonUp(ctx.daemonPort)); i++) {
          await new Promise((r) => setTimeout(r, 500));
        }
      }
      if (!(await daemonUp(ctx.daemonPort))) {
        say("Die Instanz antwortet nicht — lasse Claude nachsehen…", "err");
        await claudeTask(claude,
          "The HelmDeck python daemon in this directory does not come up on port " + ctx.daemonPort
          + ". Diagnose why (port already in use, missing runtime, traceback on start) and report the "
          + "root cause plus the exact command the user should run. Do not change any files.",
          ctx.daemonDir);   // read-only: diagnose, never silently rewrite the install
      }
      if (!(await daemonUp(ctx.daemonPort))) { say("Instanz konnte nicht gestartet werden.", "err"); return; }
      say("Instanz läuft auf :" + ctx.daemonPort, "ok");

      done = true;
      say("Fertig — jetzt anmelden.", "ok");
    } finally {
      running = false;
    }
  }

  const srv = http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    const send = (code, body) => {
      res.writeHead(code, { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" });
      res.end(JSON.stringify(body));
    };
    if (url.searchParams.get("n") !== nonce) return send(403, { error: "forbidden" });
    if (url.pathname === "/setup/state") return send(200, await state());
    if (url.pathname === "/setup/log") return send(200, { log, running, done });
    if (url.pathname === "/setup/provision") { provision(); return send(200, { started: true }); }
    return send(404, { error: "not found" });
  });
  srv.on("error", (e) => say("Setup-Server: " + e.message, "err"));
  srv.listen(PORT, "127.0.0.1");
  return { port: PORT, nonce, close: () => { try { srv.close(); } catch { /* already down */ } } };
}

module.exports = { startSetupServer, findPython, findClaude, SETUP_PORT: PORT };
