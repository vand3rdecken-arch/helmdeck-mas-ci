// ONBOARDING CONTROL PLANE (desktop only).
//
// The promise: one screen, one button, plus an OPTIONAL picker of which agent
// engines to also fetch. The user connects Claude Code; from that point
// HelmDeck provisions ITSELF and ends on a pairing QR.
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
//   - Claude Code is the installer AND the only engine that finishes
//     provisioning: it has a one-shot task interface (`claude -p "<task>"`)
//     none of the other engines expose anywhere in this codebase or in
//     Paseo's own source (checked, not assumed - see ENGINES' docstring), so
//     it is force-selected regardless of the picker. Once it is present and
//     authenticated, anything still missing is handed to it as a task rather
//     than reimplemented here as a bespoke installer per dependency.
//   - Other engines (ENGINES below) are OPTIONAL extras the picker can ask
//     for: installed if there's a known safe way to, status-only if not, but
//     never load-bearing for `done` and never promised more than they can do.
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

/** npm, needed only as the installer FOR Claude Code/Codex (see npmInstallGlobal).
 *  Unlike Python there is no small embeddable fallback for Node - if this is
 *  missing the honest floor is "go install Node.js", not a bespoke runtime we
 *  can fetch and unpack ourselves. */
function findNpm() {
  const cmd = win ? "npm.cmd" : "npm";
  const r = runQ(cmd, ["--version"]);
  return r.status === 0 ? cmd : null;
}

/** The full engine catalog the picker shows. `tier` reflects EXACTLY what this
 *  file can actually do for each - the whole point of this list is to keep
 *  the picker from promising a capability the code doesn't have:
 *    full          - claude: installs+logs in itself, AND is the only engine
 *                    with a one-shot task interface (`claude -p "<task>"`),
 *                    which is what lets it finish provisioning (Python
 *                    fallback, daemon diagnosis) for ANY selection. No other
 *                    engine here has an equivalent found anywhere in this
 *                    codebase or in Paseo's own source (checked before
 *                    writing this - see installSelectedEngines below).
 *    npm-install   - codex: a documented public npm package, installable the
 *                    same direct way as Claude itself, no agent needed.
 *    agent-install - opencode: no confident direct install COMMAND (its
 *                    public installer is a curl|sh script, not one npm
 *                    invocation) - fetched via claudeTask instead, so it
 *                    needs Claude present first.
 *    detect-only   - omp/pi: no documented public install path at all (omp's
 *                    copy on this machine came from something else entirely
 *                    - ops/docs/multi-engine-build-plan.md Card 8) - status
 *                    only, never an install attempt. */
const ENGINES = [
  { id: "claude", label: "Claude Code", tier: "full" },
  { id: "codex", label: "Codex", tier: "npm-install", npmPkg: "@openai/codex" },
  { id: "opencode", label: "OpenCode", tier: "agent-install" },
  { id: "omp", label: "OMP", tier: "detect-only" },
  { id: "pi", label: "Pi", tier: "detect-only" },
];

/** `--version` probe shared by every non-claude engine (claude has its own
 *  richer findClaude, incl. the .cmd-shim guess - kept separate). */
function probeCliVersion(cmd) {
  const r = runQ(cmd, ["--version"]);
  return { installed: r.status === 0, version: r.status === 0 ? (r.stdout || "").trim() : "" };
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
 * THE SILENT CONTEXT KILLER (spine/agent/agentcli.py::_real_claude_exe,
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

/** Quote one argument for the shell we are about to hand a joined string to.
 *  Only needed on the resolveClaudeSpawn FALLBACK path (shim we cannot see
 *  through): Node does NOT escape argv when `shell` is set - it joins on spaces
 *  and hands the result to cmd.exe - so anything with a space or a colon must
 *  carry its own quotes or it arrives as several arguments. */
const shellQuote = (a) => (win
  ? `"${String(a).replace(/"/g, '\\"')}"`
  : `'${String(a).replace(/'/g, "'\\''")}'`);

/** spawnSync for `claude`, going through resolveClaudeSpawn like claudeTask
 *  already does. This is not cosmetic: `runQ(claude.cmd, ["-p", "reply with: ok"])`
 *  reaches cmd.exe as `claude.cmd -p reply with: ok`, so the prompt splits into
 *  three arguments, claude exits non-zero on the junk, and the caller concludes
 *  "not logged in" on a perfectly healthy, authenticated install - onboarding
 *  then opens a login terminal nobody needs and waits out its full five-minute
 *  poll. Exactly the loss realClaudeExe documents above (fixed for the daemon in
 *  ea09780), reached through the one call site that still used the shell. */
function runClaude(claude, args, opts = {}) {
  const { cmd, prefixArgs, useShell } = resolveClaudeSpawn(claude);
  const argv = [...prefixArgs, ...args];
  try {
    return spawnSync(cmd, useShell ? argv.map(shellQuote) : argv,
      { shell: useShell, windowsHide: true, encoding: "utf8", timeout: 20000, env: hydratedEnv(), ...opts });
  } catch (e) {
    return { status: 1, stdout: "", stderr: String(e && e.message) };
  }
}

/** Authenticated == a trivial non-interactive prompt returns without an auth
 *  error. `claude -p` exits non-zero and says so when the user is logged out. */
function claudeAuthed(claude) {
  if (!claude) return false;
  const r = runClaude(claude, ["-p", "reply with: ok"], { timeout: 60000 });
  const out = ((r.stdout || "") + (r.stderr || "")).toLowerCase();
  if (/not logged in|unauthor|authenticate|login|invalid api key|no api key/.test(out)) return false;
  return r.status === 0;
}

/** Best-effort Node.js bootstrap via winget, mirroring the Python embeddable-
 *  runtime fallback below. Only attempted on Windows (winget's the one
 *  package manager guaranteed present on Win10 21H2+/Win11). A fresh install
 *  updates the machine's registered PATH, but THIS process's env is already
 *  loaded - a freshly-installed npm is typically still invisible until the
 *  app restarts, so the caller re-probes once and, if still blind, says so
 *  plainly instead of pretending the loop can route around it. */
function installNodeViaWinget() {
  if (!win) return false;
  say("Installiere Node.js über winget…");
  const r = runQ("winget", ["install", "-e", "--id", "OpenJS.NodeJS.LTS",
    "--accept-source-agreements", "--accept-package-agreements"], { timeout: 180000 });
  if (r.status !== 0) {
    say("winget-Installation fehlgeschlagen: " + (r.stderr || r.stdout || "").trim(), "err");
    return false;
  }
  say("Node.js installiert.", "ok");
  return true;
}

/** The Paseo-style install step (packages/server/.../npm-global-cli.ts
 *  installLatest): a global CLI dependency is installed BY THE APP, streamed
 *  to the screen, not handed to the user as a command to type into a
 *  terminal they have to go find. Paseo applies this to its own CLI package;
 *  this generalizes it to any package with a plain `npm install -g <pkg>`
 *  install (Claude Code and Codex both qualify - same "one button" promise,
 *  same reason not to dead-end into a manual step). */
function npmInstallGlobal(npmCmd, pkgName, displayName) {
  return new Promise((resolve) => {
    say("Installiere " + displayName + ": npm install -g " + pkgName);
    const p = spawn(npmCmd, ["install", "-g", pkgName],
      { shell: win, windowsHide: true, env: hydratedEnv() });
    let tail = "";
    let settled = false;
    const finish = (ok) => { if (!settled) { settled = true; resolve(ok); } };
    const killer = setTimeout(() => { say("npm install hängt - breche ab.", "err"); p.kill(); finish(false); }, 300000);
    const onData = (d) => {
      tail += d.toString();
      const lines = tail.split("\n");
      tail = lines.pop() || "";
      for (const l of lines) if (l.trim()) say(l.trim());
    };
    p.stdout.on("data", onData);
    p.stderr.on("data", onData);
    p.on("close", (code) => { clearTimeout(killer); if (tail.trim()) say(tail.trim()); finish(code === 0); });
    p.on("error", (e) => { clearTimeout(killer); say("npm ließ sich nicht starten: " + e.message, "err"); finish(false); });
  });
}

/** Login needs an interactive browser OAuth flow - that part genuinely can't
 *  be automated - but the user shouldn't have to know `claude` is the magic
 *  word or go hunting for a terminal themselves. Open one FOR them, already
 *  running `claude` (no -p: interactive, so its own login prompt takes over).
 *  Best-effort by platform: real on Windows (a fresh console); elsewhere an
 *  attempt at the common terminal, never load-bearing -
 *  waitForAuth's poll is what actually decides whether onboarding proceeds. */
function openClaudeLoginTerminal(claude) {
  try {
    if (win) {
      // Prefer the real executable over the .cmd shim (same reason as
      // resolveClaudeSpawn), and let Node do the quoting: with shell:false it
      // quotes any argument containing spaces, so the title stays a title and
      // a path like C:\Program Files\nodejs\claude.cmd survives. Pre-quoting
      // the title by hand produced a doubly-quoted token, and the unquoted
      // ProgramFiles path made `cmd /k` try to run "C:\Program".
      const { cmd, prefixArgs } = resolveClaudeSpawn(claude);
      spawn("cmd.exe", ["/c", "start", "Claude Code Login", "cmd", "/k", cmd, ...prefixArgs],
        { shell: false, windowsHide: false, detached: true, stdio: "ignore", env: hydratedEnv() }).unref();
      return true;
    }
    if (process.platform === "darwin") {
      spawn("osascript", ["-e",
        `tell application "Terminal" to do script "${claude.cmd}"`], { detached: true, stdio: "ignore" }).unref();
      return true;
    }
    spawn("x-terminal-emulator", ["-e", claude.cmd], { detached: true, stdio: "ignore" }).unref();
    return true;
  } catch {
    return false;
  }
}

/** Poll claudeAuthed instead of dead-ending on the first check, so the user
 *  can complete the browser login the app just opened for them without
 *  leaving this screen or restarting HelmDeck. Bounded (5 min): a wedged or
 *  abandoned login must not hang provisioning forever - pressing Start again
 *  simply re-enters here (idempotent, same as every other step). */
async function waitForAuth(claude, timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (claudeAuthed(claude)) return true;
    await new Promise((r) => setTimeout(r, 8000));
  }
  return claudeAuthed(claude);
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

/** Make an embeddable CPython able to import the daemon package.
 *
 * MEASURED, NOT REASONED (2026-08-29, stock 3.12.8 embed extract, the exact
 * production command from the repo root):
 *     python.exe -c "import sys; print(sys.path)"
 *       -> ['...\\python312.zip', '...\\python']          # no cwd, at all
 *     python.exe -m daemon.swarm
 *       -> ModuleNotFoundError: No module named 'daemon'
 *
 * The embeddable build ships a `python3xx._pth`, which PINS sys.path to the zip
 * plus its own directory and - by existing at all - also suppresses the working
 * directory that `-m` normally prepends. It makes PYTHONPATH inert too, so there
 * is no environment-variable way around it; the _pth is the only lever.
 *
 * That lands precisely on the fresh machine this whole fallback exists for:
 * provisioning would fetch the runtime, report "Python-Laufzeit bereit", and
 * then fail to start the very instance it had just made possible - with the
 * traceback in daemon.out.log where the onboarding screen never looks.
 *
 * Appending the root the daemon is actually launched from (main.js startDaemon
 * uses path.dirname(daemonDir) as cwd) is enough; `site` stays disabled. */
function pinPthToDaemonRoot(pyDir, daemonRoot) {
  let entries;
  try { entries = fs.readdirSync(pyDir); } catch { return; }
  const name = entries.find((f) => /^python\d+\._pth$/i.test(f));
  if (!name) return;                    // a full install, not an embed - nothing to pin
  const file = path.join(pyDir, name);
  try {
    const body = fs.readFileSync(file, "utf8");
    // Idempotent: this runs on every provision (which may be re-entered by a
    // reload or a second press), and a stacked duplicate path is a slow leak.
    if (body.split(/\r?\n/).some((l) => l.trim().toLowerCase() === daemonRoot.toLowerCase())) return;
    fs.appendFileSync(file, (body.endsWith("\n") ? "" : "\r\n") + daemonRoot + "\r\n");
    say("Python-Laufzeit auf HelmDeck ausgerichtet.", "ok");
  } catch (e) {
    say("Konnte die Python-Laufzeit nicht ausrichten: " + e.message, "err");
  }
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

/** Installs whichever OPTIONAL engines the picker's selection asked for (never
 *  "claude" - step 1 in provision() already owns that one). Not required for
 *  the daemon (a card defaults to driver "claude") and codex/opencode/pi are
 *  NOT LIVE-VERIFIED yet per their own driver module docstrings
 *  (spine/agent/*_driver.py, owner decree 2026-08-24, "test accounts later")
 *  - fetching a binary is not the same claim as its driver working, so this
 *  only gets a CLI onto PATH, never auto-picks a card onto that driver.
 *  Best-effort per engine, NEVER blocks `done`.
 *
 *  Three different install strategies, one per ENGINES tier (see its own
 *  docstring for why each engine landed where it did):
 *    npm-install   - installed directly (npmInstallGlobal), no agent needed.
 *    agent-install - handed to Claude as a task (claudeTask), same hand-off
 *                    Python's own fallback in provision() already uses -
 *                    scales to engines with no single install COMMAND
 *                    (opencode's public installer is curl|sh, not npm).
 *    detect-only   - no action possible; just says so, once. */
async function installSelectedEngines(claude, cwd, selected) {
  const npmTargets = [], agentTargets = [], detectOnly = [];
  for (const eng of ENGINES) {
    if (eng.id === "claude" || !selected.has(eng.id)) continue;
    if (probeCliVersion(eng.id).installed) { say(eng.label + " bereits vorhanden.", "ok"); continue; }
    if (eng.tier === "npm-install") npmTargets.push(eng);
    else if (eng.tier === "agent-install") agentTargets.push(eng);
    else detectOnly.push(eng);
  }
  if (npmTargets.length) {
    const npm = findNpm();
    if (!npm) {
      say("Ohne npm kann ich " + npmTargets.map((e) => e.label).join(", ") + " nicht installieren.", "err");
    } else {
      for (const eng of npmTargets) await npmInstallGlobal(npm, eng.npmPkg, eng.label);
    }
  }
  if (agentTargets.length) {
    say("Richte über Claude ein: " + agentTargets.map((e) => e.label).join(", ") + "…");
    const list = agentTargets.map((e) => e.label + " (offizieller Installer, z.B. https://opencode.ai für OpenCode)").join("; ");
    const ok = await claudeTask(claude,
      "Install these optional coding-agent CLIs, skipping any already installed, so their "
      + "`--version` command works: " + list + ". "
      + "Do not modify anything else on this machine. Report which succeeded and which failed.",
      cwd, "acceptEdits");
    say(ok ? "Eingerichtet." : "Nicht alle erfolgreich - siehe oben.", ok ? "ok" : "hint");
  }
  for (const eng of detectOnly) {
    say(eng.label + ": keine bekannte Installationsmethode - nur Status wird angezeigt.", "hint");
  }
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
  let _pyProbe = null, _claudeProbe = null, _engineProbeCache = {};
  // A MISS is retried - installing Python while this screen is open has to be
  // noticed - but no more often than MISS_TTL. Both halves matter: on a fresh
  // machine every probe misses BY DEFINITION, and findPython/findClaude shell
  // out per candidate SYNCHRONOUSLY, so an unthrottled retry re-ran up to six
  // blocking spawns per request while two independent hooks poll /setup/state
  // about twice a second - the control plane spent provisioning blocked on its
  // own probes. Positive results still stick forever (below).
  const MISS_TTL = 5000;
  const _missAt = {};
  const cachedProbe = (key, probe) => {
    const now = Date.now();
    if (now - (_missAt[key] || 0) < MISS_TTL) return null;
    const r = probe();
    if (!r) _missAt[key] = now;
    return r;
  };
  const probePython = () => _pyProbe || (_pyProbe = cachedProbe("python", () => findPython(ctx.resourcesDir)));
  const probeClaude = () => _claudeProbe || (_claudeProbe = cachedProbe("claude", () => findClaude()));
  const state = async () => {
    const py = probePython();
    const claude = probeClaude();
    return {
      python: !!py, pythonBundled: !!(py && py.bundled),
      claude: !!claude, claudeVersion: claude ? claude.version : "",
      daemon: await daemonUp(ctx.daemonPort),
      running, done,
    };
  };

  // Same cache-once-positive / throttle-the-miss reasoning as probePython above,
  // and for the same reason: this list is five CLIs, all of them missing on a
  // fresh machine, probed on every poll. The cache holds HITS only, so a null
  // entry is simply "not found yet" and re-probes on the next tick past MISS_TTL.
  const engineStatuses = () => ENGINES.map((eng) => {
    if (eng.id === "claude") {
      const c = probeClaude();
      return { id: eng.id, label: eng.label, tier: eng.tier, installed: !!c, version: c ? c.version : "" };
    }
    const hit = _engineProbeCache[eng.id]
      || (_engineProbeCache[eng.id] = cachedProbe("eng:" + eng.id, () => {
        const s = probeCliVersion(eng.id);
        return s.installed ? s : null;
      }));
    return { id: eng.id, label: eng.label, tier: eng.tier,
      installed: !!hit, version: hit ? hit.version : "" };
  });

  async function provision(selected) {
    if (running) return;
    // The picker's selection; "claude" is force-included regardless of what
    // was passed - it is the only engine that can finish provisioning (see
    // ENGINES' docstring), so deselecting it would silently break every
    // other selection, not just skip an optional extra.
    selected = new Set(selected || ["claude"]);
    selected.add("claude");
    running = true; done = false;
    try {
      // 1) Claude Code — the one thing the user must own (their account), but
      //    NOT the one thing they must type a terminal command for: the app
      //    installs the CLI itself (Paseo's own-CLI installLatest, applied
      //    here to Claude Code) and opens the login prompt for them. Only the
      //    OAuth click in the browser is genuinely theirs to do.
      let claude = findClaude();
      if (!claude) {
        say("Claude Code ist nicht installiert.");
        let npm = findNpm();
        if (!npm) {
          say("Node.js/npm wurde nicht gefunden.");
          if (installNodeViaWinget()) npm = findNpm();
        }
        if (!npm) {
          say("Ohne npm kann ich Claude Code nicht automatisch installieren.", "err");
          say("Installiere Node.js von https://nodejs.org, dann hier erneut starten.", "hint");
          return;
        }
        if (!(await npmInstallGlobal(npm, "@anthropic-ai/claude-code", "Claude Code"))) {
          say("Automatische Installation fehlgeschlagen.", "err");
          say("Installiere manuell: npm i -g @anthropic-ai/claude-code, dann hier erneut starten.", "hint");
          return;
        }
        claude = findClaude();
        if (!claude) {
          say("Claude Code wurde installiert, ist aber noch nicht auffindbar.", "err");
          say("Starte HelmDeck neu, damit die neue PATH-Eintragung geladen wird.", "hint");
          return;
        }
        _claudeProbe = claude;   // installed just now — cache it, skip a re-probe
      }
      say("Claude Code gefunden: " + (claude.version || "ok"), "ok");
      if (!claudeAuthed(claude)) {
        say("Claude Code ist nicht angemeldet — öffne ein Anmeldefenster…");
        if (!openClaudeLoginTerminal(claude)) {
          say("Konnte kein Terminal öffnen.", "err");
          say("Führe im Terminal `claude` aus, melde dich an, dann hier erneut starten.", "hint");
          return;
        }
        say("Melde dich im geöffneten Fenster an — ich warte…", "hint");
        if (!(await waitForAuth(claude, 5 * 60 * 1000))) {
          say("Noch nicht angemeldet.", "err");
          say("Melde dich im geöffneten Fenster an und drücke dann hier erneut Start.", "hint");
          return;
        }
      }
      say("Claude ist angemeldet.", "ok");

      // 2) Runtime for the daemon (stdlib-only, so the embeddable build suffices)
      let py = findPython(ctx.resourcesDir);
      if (!py) {
        say("Keine Python-Laufzeit gefunden.");
        // The embeddable runtime is a WINDOWS artifact (…-embed-amd64.zip) and
        // unpacking it goes through PowerShell, so on macOS/Linux this would
        // download 11 MB and then fail at the unzip. Go straight to the hand-off
        // that can actually succeed there instead of spending the round trip.
        try {
          if (!win) throw new Error("kein einbettbares Python für diese Plattform");
          py = await fetchPython(ctx.resourcesDir);
        } catch (e) {
          say(win ? "Download fehlgeschlagen: " + e.message : e.message, "err");
          say("Ich lasse Claude es übernehmen…");
          // Describe the machine we are ACTUALLY on: this hand-off is now the
          // only route to a runtime on macOS/Linux, and telling Claude to use
          // winget on a Mac wastes the one step that can still rescue the run.
          await claudeTask(claude,
            win
              ? "Install a Python 3.12 runtime on this Windows machine so that `py -3.12 --version` "
                + "works, using winget if available. Do not modify anything else. Report what you did."
              : "Install a Python 3.12 runtime on this " + process.platform + " machine so that "
                + "`python3 --version` reports 3.12 or newer, using the system package manager "
                + "(Homebrew on macOS). Do not modify anything else. Report what you did.",
            ctx.daemonDir, "acceptEdits");   // this step must actually change the machine
          py = findPython(ctx.resourcesDir);
        }
      }
      if (!py) { say("Ohne Python-Laufzeit kann der Daemon nicht starten.", "err"); return; }
      say("Python-Laufzeit bereit.", "ok");
      // Covers BOTH embeddable runtimes we can end up on - the one fetchPython
      // just downloaded and one the installer bundled - because they land in the
      // same directory and carry the same _pth. A system Python needs nothing.
      if (py.bundled) pinPthToDaemonRoot(path.join(ctx.resourcesDir, "python"), path.dirname(ctx.daemonDir));

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

      // 4) optional: other engine CLIs the picker selected (see
      //    installSelectedEngines docstring) — never gates `done`.
      await installSelectedEngines(claude, ctx.daemonDir, selected);

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
    if (url.pathname === "/setup/engines") return send(200, { engines: engineStatuses() });
    if (url.pathname === "/setup/provision") {
      const raw = (url.searchParams.get("engines") || "claude").split(",").map((s) => s.trim()).filter(Boolean);
      // Report whether THIS call started a run. A reload mid-provision re-posts
      // here, and provision() correctly ignores the second one - but answering
      // `started: true` to a call that started nothing is the kind of small lie
      // that later reads as "it ran twice" when debugging a re-entrant flow.
      const already = running;
      provision(raw);
      return send(200, { started: !already, alreadyRunning: already });
    }
    return send(404, { error: "not found" });
  });
  srv.on("error", (e) => say("Setup-Server: " + e.message, "err"));
  srv.listen(PORT, "127.0.0.1");
  return { port: PORT, nonce, close: () => { try { srv.close(); } catch { /* already down */ } } };
}

// pinPthToDaemonRoot is exported alongside the probes so the _pth behaviour it
// works around stays testable without a full provision run.
module.exports = { startSetupServer, findPython, findClaude, pinPthToDaemonRoot, SETUP_PORT: PORT };
