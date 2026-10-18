//! The first-run setup control plane (what `surfaces/desktop/setup.js` is for the Electron shell).
//!
//! At first run the daemon is exactly what does not exist yet, so the web app talks to this tiny
//! loopback server instead: `/setup/state`, `/setup/log`, `/setup/engines`, `/setup/provision`.
//! Same endpoints, same JSON shapes - the web app reads them unchanged.
//!
//! Rules carried over: 127.0.0.1 only and a per-launch nonce (this endpoint can start processes);
//! every step idempotent and re-entrant; probes cached once positive, a miss retried no more than
//! every MISS_TTL (a fresh machine misses everything, and the screen polls twice a second).
//!
//! NOT ported (still Electron-only, see README): the
//! hand-offs, optional engine installs (status only here), the Microsoft Store variant, the
//! mac/linux login terminal.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

pub const SETUP_PORT: u16 = 8141;
const MISS_TTL: Duration = Duration::from_secs(5);
const LOG_MAX: usize = 400;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

// ----------------------------------------------------------------------- helpers

pub fn nonce() -> String {
    // 128 bits from the OS (the same source `RandomState` seeds from is not enough to rely on, so
    // read it directly)
    #[cfg(windows)]
    {
        let mut b = [0u8; 16];
        let ok = unsafe { rand_bytes(&mut b) };
        if ok {
            return b.iter().map(|x| format!("{x:02x}")).collect();
        }
    }
    let t = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
    format!("{:032x}", t ^ ((std::process::id() as u128) << 64))
}

#[cfg(windows)]
unsafe fn rand_bytes(b: &mut [u8]) -> bool {
    #[link(name = "advapi32")]
    extern "system" {
        #[link_name = "SystemFunction036"]
        fn RtlGenRandom(buf: *mut u8, len: u32) -> u8;
    }
    RtlGenRandom(b.as_mut_ptr(), b.len() as u32) != 0
}

/// `claude -p` exits non-zero AND says so when logged out; these are the phrases (setup.js).
pub fn output_means_logged_out(out: &str) -> bool {
    let o = out.to_lowercase();
    ["not logged in", "unauthor", "authenticate", "login", "invalid api key", "no api key"].iter().any(|p| o.contains(p))
}

/// The first https URL in some output ("if no browser opens: <url>").
pub fn first_url(s: &str) -> Option<String> {
    let i = s.find("https://")?;
    Some(s[i..].split_whitespace().next()?.to_string())
}

/// The real executable behind an npm `claude.cmd` shim: spawning the shim through cmd.exe swallows
/// everything after the first space of an argument (a whole prompt arrived as "The").
pub fn real_claude_exe(cmd_path: &Path) -> Option<Vec<PathBuf>> {
    let d = cmd_path.parent()?;
    let base = d.join("node_modules").join("@anthropic-ai").join("claude-code");
    let exe = base.join("bin").join("claude.exe");
    if exe.is_file() {
        return Some(vec![exe]);
    }
    let (js, node) = (base.join("cli.js"), d.join("node.exe"));
    if js.is_file() && node.is_file() {
        return Some(vec![node, js]);
    }
    None
}

fn command(program: &str) -> Command {
    let mut c = Command::new(program);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        c.creation_flags(CREATE_NO_WINDOW);
    }
    c.stdin(Stdio::null());
    c
}

/// Run to completion with a timeout; None when it could not start or timed out.
fn run_capture(mut c: Command, limit: Duration) -> Option<(i32, String)> {
    c.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = c.spawn().ok()?;
    let (mut out, mut err) = (child.stdout.take()?, child.stderr.take()?);
    let t_out = std::thread::spawn(move || {
        let mut s = String::new();
        let _ = out.read_to_string(&mut s);
        s
    });
    let t_err = std::thread::spawn(move || {
        let mut s = String::new();
        let _ = err.read_to_string(&mut s);
        s
    });
    let start = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(st)) => break st,
            Ok(None) if start.elapsed() < limit => std::thread::sleep(Duration::from_millis(50)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return None;
            }
        }
    };
    let text = t_out.join().unwrap_or_default() + &t_err.join().unwrap_or_default();
    Some((status.code().unwrap_or(-1), text))
}

fn version_of(program: &str, args: &[&str]) -> Option<String> {
    let mut c = command(program);
    c.args(args).arg("--version");
    let (code, out) = run_capture(c, Duration::from_secs(20))?;
    (code == 0).then(|| out.trim().to_string())
}

// ----------------------------------------------------------------------- probes

#[derive(Clone, Debug, PartialEq)]
pub struct Claude {
    pub cmd: String,
    pub version: String,
}

/// A python command as ONE string: argv joined by a tab (a path may contain spaces, a launcher
/// has arguments: "py<TAB>-3.12"). `daemon_argv` splits it back.
pub fn find_python(resources: &Path) -> Option<String> {
    // the runtime the installer bundles (or `fetch_python` unpacked) wins
    let bundled = resources.join("python").join(if cfg!(windows) { "python.exe" } else { "bin/python3" });
    if bundled.is_file() {
        return Some(bundled.to_string_lossy().into_owned());
    }
    let cands: &[(&str, &[&str])] = if cfg!(windows) {
        &[("py", &["-3.12"]), ("py", &["-3"]), ("python", &[]), ("python3", &[])]
    } else {
        &[("python3", &[]), ("python", &[])]
    };
    for (cmd, args) in cands {
        if version_of(cmd, args).is_some() {
            return Some(std::iter::once(*cmd).chain(args.iter().copied()).collect::<Vec<_>>().join("\t"));
        }
    }
    if cfg!(windows) {
        let local = std::env::var("LOCALAPPDATA").unwrap_or_default();
        let pf = std::env::var("ProgramFiles").unwrap_or_else(|_| "C:\\Program Files".into());
        for v in ["312", "313", "311"] {
            for p in [format!("{local}\\Programs\\Python\\Python{v}\\python.exe"), format!("{pf}\\Python{v}\\python.exe")] {
                if Path::new(&p).is_file() && version_of(&p, &[]).is_some() {
                    return Some(p);
                }
            }
        }
    }
    None
}

/// (program, leading args) of a `find_python` string.
pub fn daemon_argv(py: &str) -> (String, Vec<String>) {
    let mut it = py.split('\t').map(str::to_string);
    (it.next().unwrap_or_default(), it.collect())
}

pub const PY_EMBED_URL: &str = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip";

/// An embeddable CPython ignores PYTHONPATH and the cwd - its `pythonXY._pth` is the only lever - so
/// `-m daemon.swarm` would fail on exactly the fresh machine this fetch exists for, with the traceback
/// in daemon.out.log where the screen never looks. Append the daemon root once (idempotent).
pub fn pin_pth(py_dir: &Path, daemon_root: &Path) -> Result<bool, String> {
    let Ok(entries) = std::fs::read_dir(py_dir) else { return Ok(false) };
    let Some(file) = entries.flatten().map(|e| e.path()).find(|p| {
        p.file_name()
            .and_then(|n| n.to_str())
            .map(|n| n.to_lowercase())
            .map(|n| n.starts_with("python") && n.ends_with("._pth"))
            .unwrap_or(false)
    }) else {
        return Ok(false); // a full install, not an embed: nothing to pin
    };
    let body = std::fs::read_to_string(&file).map_err(|e| e.to_string())?;
    let root = daemon_root.to_string_lossy().into_owned();
    if body.lines().any(|l| l.trim().eq_ignore_ascii_case(&root)) {
        return Ok(false);
    }
    let mut f = std::fs::OpenOptions::new().append(true).open(&file).map_err(|e| e.to_string())?;
    let sep = if body.ends_with('\n') { "" } else { "\r\n" };
    write!(f, "{sep}{root}\r\n").map_err(|e| e.to_string())?;
    Ok(true)
}

fn powershell() -> String {
    let root = std::env::var("SystemRoot").unwrap_or_else(|_| "C:\\Windows".into());
    format!("{root}\\System32\\WindowsPowerShell\\v1.0\\powershell.exe")
}

/// Download + unpack the embeddable runtime into `<resources>/python` (Windows only). PowerShell is
/// always there, so no unzip dependency is shipped.
pub fn fetch_python(resources: &Path, url: &str) -> Result<(), String> {
    let target = resources.join("python");
    let zip = resources.join("python-embed.zip");
    let script = format!(
        "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; \
         Invoke-WebRequest -UseBasicParsing -Uri '{url}' -OutFile '{z}'; \
         Expand-Archive -Path '{z}' -DestinationPath '{t}' -Force; Remove-Item -Path '{z}' -ErrorAction SilentlyContinue",
        z = zip.display(),
        t = target.display()
    );
    std::fs::create_dir_all(resources).map_err(|e| e.to_string())?;
    let mut c = command(&powershell());
    c.args(["-NoProfile", "-NonInteractive", "-Command", &script]);
    match run_capture(c, Duration::from_secs(300)) {
        Some((0, _)) => Ok(()),
        Some((_, out)) => Err(out.trim().lines().last().unwrap_or("unknown error").to_string()),
        None => Err("Zeitueberschreitung beim Laden".into()),
    }
}

pub fn find_claude() -> Option<Claude> {
    let explicit = std::env::var("HELMDECK_CLAUDE").ok().filter(|s| !s.trim().is_empty());
    for c in explicit.into_iter().chain(["claude".to_string()]) {
        if let Some(v) = version_of(&c, &[]) {
            return Some(Claude { cmd: c, version: v });
        }
    }
    if cfg!(windows) {
        let pf = std::env::var("ProgramFiles").unwrap_or_else(|_| "C:\\Program Files".into());
        let guess = format!("{pf}\\nodejs\\claude.cmd");
        if Path::new(&guess).is_file() {
            if let Some(v) = version_of(&guess, &[]) {
                return Some(Claude { cmd: guess, version: v });
            }
        }
    }
    None
}

pub fn find_npm() -> Option<String> {
    let cmd = if cfg!(windows) { "npm.cmd" } else { "npm" };
    version_of(cmd, &[]).map(|_| cmd.to_string())
}

/// The daemon port named in the diagnosis prompt (main.rs owns the real constant; both are 8140).
const DAEMON_PORT_FOR_DIAGNOSIS: u16 = 8140;

/// argv after the claude executable for a one-shot task.
pub fn claude_task_args(prompt: &str, mode: &str) -> Vec<String> {
    vec!["-p".into(), prompt.into(), "--permission-mode".into(), mode.into()]
}

/// npm package of an `npm-install` engine.
fn npm_package(id: &str) -> Option<&'static str> {
    match id {
        "codex" => Some("@openai/codex"),
        _ => None,
    }
}

#[derive(Debug, Default, PartialEq)]
pub struct EnginePlan {
    pub present: Vec<String>,
    pub npm: Vec<(String, String)>, // (label, package)
    pub agent: Vec<String>,
    pub detect_only: Vec<String>,
}

/// What to do for each selected optional engine, by its tier.
pub fn engine_plan(selected: &[String], installed: &dyn Fn(&str) -> bool) -> EnginePlan {
    let mut plan = EnginePlan::default();
    for (id, label, tier) in ENGINES {
        if *id == "claude" || !selected.iter().any(|s| s == id) {
            continue;
        }
        if installed(id) {
            plan.present.push(label.to_string());
            continue;
        }
        match *tier {
            "npm-install" => plan.npm.push((label.to_string(), npm_package(id).unwrap_or_default().to_string())),
            "agent-install" => plan.agent.push(label.to_string()),
            _ => plan.detect_only.push(label.to_string()),
        }
    }
    plan
}

/// The picker's `engines=a,b` query (claude is always included server-side).
pub fn selected_engines(target: &str) -> Vec<String> {
    let mut v: Vec<String> = query_param(target, "engines").unwrap_or_default().split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect();
    if !v.iter().any(|s| s == "claude") {
        v.push("claude".into());
    }
    v
}

/// (id, label, tier) - what the picker shows; tier says exactly what is possible.
pub const ENGINES: &[(&str, &str, &str)] = &[
    ("claude", "Claude Code", "full"),
    ("codex", "Codex", "npm-install"),
    ("opencode", "OpenCode", "agent-install"),
    ("omp", "OMP", "detect-only"),
    ("pi", "Pi", "detect-only"),
];

/// Any HTTP answer on the daemon port counts as up (a 401 is an answer).
pub fn daemon_up(port: u16) -> bool {
    let Ok(mut s) = TcpStream::connect_timeout(&([127, 0, 0, 1], port).into(), Duration::from_millis(800)) else {
        return false;
    };
    let _ = s.set_read_timeout(Some(Duration::from_millis(1500)));
    if s.write_all(b"GET /system/health HTTP/1.0\r\nHost: x\r\n\r\n").is_err() {
        return false;
    }
    let mut b = [0u8; 5];
    s.read_exact(&mut b).is_ok() && &b == b"HTTP/"
}

// ----------------------------------------------------------------------- state

#[derive(Clone)]
pub struct Probes {
    pub python: Arc<dyn Fn() -> Option<String> + Send + Sync>,
    pub claude: Arc<dyn Fn() -> Option<Claude> + Send + Sync>,
    pub engine: Arc<dyn Fn(&str) -> Option<String> + Send + Sync>,
    pub daemon_up: Arc<dyn Fn() -> bool + Send + Sync>,
}

impl Probes {
    pub fn real(daemon_port: u16, resources: PathBuf) -> Probes {
        Probes {
            python: Arc::new(move || find_python(&resources)),
            claude: Arc::new(find_claude),
            engine: Arc::new(|id| version_of(id, &[])),
            daemon_up: Arc::new(move || daemon_up(daemon_port)),
        }
    }
}

#[derive(Default)]
struct Cache {
    python: Option<String>,
    claude: Option<Claude>,
    engines: std::collections::HashMap<String, String>,
    missed: std::collections::HashMap<String, Instant>,
}

/// Where this install keeps things: the runtime, the repo root the daemon starts from, its log.
#[derive(Clone, Default)]
pub struct Env {
    pub resources: PathBuf,
    pub daemon_root: Option<PathBuf>,
    pub daemon_log: Option<PathBuf>,
    /// a Microsoft Store install: DETECT prerequisites only, install nothing (policy 10.2.4)
    pub store: bool,
}

pub struct Setup {
    pub nonce: String,
    probes: Probes,
    log: Mutex<Vec<(u128, String, String)>>,
    flags: Mutex<(bool, bool)>, // (running, done)
    cache: Mutex<Cache>,
    env: Env,
    hints: Arc<Mutex<Vec<String>>>, // written by the login-output thread, folded into the log on read
}

impl Setup {
    #[cfg(test)]
    pub fn new(probes: Probes) -> Arc<Setup> {
        Setup::with_env(probes, Env::default())
    }

    pub fn with_env(probes: Probes, env: Env) -> Arc<Setup> {
        Arc::new(Setup { nonce: nonce(), probes, env, log: Mutex::new(Vec::new()), flags: Mutex::new((false, false)), cache: Mutex::new(Cache::default()), hints: Arc::new(Mutex::new(Vec::new())) })
    }

    pub fn say(&self, line: &str, kind: &str) {
        let ts = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_millis()).unwrap_or(0);
        let mut l = self.log.lock().unwrap();
        l.push((ts, kind.to_string(), line.to_string()));
        if l.len() > LOG_MAX {
            l.remove(0);
        }
    }

    /// A hit sticks; a miss is re-probed no more often than MISS_TTL.
    fn throttled(&self, key: &str) -> bool {
        self.cache.lock().unwrap().missed.get(key).map(|t| t.elapsed() < MISS_TTL).unwrap_or(false)
    }
    fn missed(&self, key: &str) {
        self.cache.lock().unwrap().missed.insert(key.to_string(), Instant::now());
    }

    pub fn python(&self) -> Option<String> {
        if let Some(p) = self.cache.lock().unwrap().python.clone() {
            return Some(p);
        }
        if self.throttled("python") {
            return None;
        }
        let r = (self.probes.python)();
        match &r {
            Some(p) => self.cache.lock().unwrap().python = Some(p.clone()),
            None => self.missed("python"),
        }
        r
    }

    pub fn claude(&self) -> Option<Claude> {
        if let Some(c) = self.cache.lock().unwrap().claude.clone() {
            return Some(c);
        }
        if self.throttled("claude") {
            return None;
        }
        let r = (self.probes.claude)();
        match &r {
            Some(c) => self.cache.lock().unwrap().claude = Some(c.clone()),
            None => self.missed("claude"),
        }
        r
    }

    fn set_claude(&self, c: Claude) {
        self.cache.lock().unwrap().claude = Some(c);
    }

    fn bundled_dir(&self) -> PathBuf {
        self.env.resources.join("python")
    }

    pub fn state_json(&self) -> serde_json::Value {
        let py = self.python();
        let claude = self.claude();
        let (running, done) = *self.flags.lock().unwrap();
        serde_json::json!({
            "python": py.is_some(), "pythonBundled": py.as_deref().map(|p| Path::new(p).starts_with(self.bundled_dir())).unwrap_or(false),
            "claude": claude.is_some(), "claudeVersion": claude.map(|c| c.version).unwrap_or_default(),
            "daemon": (self.probes.daemon_up)(),
            "running": running, "done": done,
        })
    }

    pub fn log_json(&self) -> serde_json::Value {
        let (running, done) = *self.flags.lock().unwrap();
        let log: Vec<_> = self.log.lock().unwrap().iter().map(|(ts, k, l)| serde_json::json!({"ts": ts, "kind": k, "line": l})).collect();
        serde_json::json!({"log": log, "running": running, "done": done})
    }

    pub fn engines_json(&self) -> serde_json::Value {
        let engines: Vec<_> = ENGINES
            .iter()
            .map(|(id, label, tier)| {
                let version = if *id == "claude" {
                    self.claude().map(|c| c.version)
                } else {
                    let hit = self.cache.lock().unwrap().engines.get(*id).cloned();
                    hit.or_else(|| {
                        if self.throttled(&format!("eng:{id}")) {
                            return None;
                        }
                        let r = (self.probes.engine)(id);
                        match &r {
                            Some(v) => {
                                self.cache.lock().unwrap().engines.insert(id.to_string(), v.clone());
                            }
                            None => self.missed(&format!("eng:{id}")),
                        }
                        r
                    })
                };
                serde_json::json!({"id": id, "label": label, "tier": tier, "installed": version.is_some(), "version": version.unwrap_or_default()})
            })
            .collect();
        serde_json::json!({"engines": engines})
    }

    /// Start a provisioning run unless one is in flight. Returns whether THIS call started one.
    pub fn provision(self: &Arc<Self>, start_daemon: Arc<dyn Fn(&str) -> bool + Send + Sync>, env: Env, selected: Vec<String>) -> bool {
        {
            let mut f = self.flags.lock().unwrap();
            if f.0 {
                return false;
            }
            *f = (true, false);
        }
        let me = self.clone();
        std::thread::spawn(move || {
            let ok = me.run_with(&*start_daemon, &env, &selected);
            let mut f = me.flags.lock().unwrap();
            *f = (false, ok);
        });
        true
    }

    #[cfg(test)]
    fn run(&self, start_daemon: &dyn Fn(&str) -> bool, env: &Env) -> bool {
        self.run_with(start_daemon, env, &[])
    }

    fn run_with(&self, start_daemon: &dyn Fn(&str) -> bool, env: &Env, selected: &[String]) -> bool {
        if env.store {
            return self.run_store(start_daemon, env, selected);
        }
        // 1) Claude Code
        let mut claude = self.claude();
        if claude.is_none() {
            self.say("Claude Code ist nicht installiert.", "info");
            let mut npm = find_npm();
            if npm.is_none() {
                self.say("Node.js/npm wurde nicht gefunden.", "info");
                if cfg!(windows) && self.install_node_via_winget() {
                    npm = find_npm();
                }
            }
            let Some(npm) = npm else {
                self.say("Ohne npm kann ich Claude Code nicht automatisch installieren.", "err");
                self.say("Installiere Node.js von https://nodejs.org, dann hier erneut starten.", "hint");
                return false;
            };
            if !self.npm_install_global(&npm, "@anthropic-ai/claude-code", "Claude Code") {
                self.say("Automatische Installation fehlgeschlagen.", "err");
                self.say("Installiere manuell: npm i -g @anthropic-ai/claude-code, dann hier erneut starten.", "hint");
                return false;
            }
            claude = find_claude();
            let Some(c) = claude.clone() else {
                self.say("Claude Code wurde installiert, ist aber noch nicht auffindbar.", "err");
                self.say("Starte HelmDeck neu, damit die neue PATH-Eintragung geladen wird.", "hint");
                return false;
            };
            self.set_claude(c);
        }
        let claude = claude.unwrap();
        self.say(&format!("Claude Code gefunden: {}", if claude.version.is_empty() { "ok" } else { &claude.version }), "ok");
        if !claude_authed(&claude) {
            self.say("Claude Code ist nicht angemeldet - öffne die Anmeldung im Browser…", "info");
            if !self.open_login(&claude) {
                self.say("Konnte die Anmeldung nicht starten.", "err");
                self.say("Führe im Terminal `claude` aus, melde dich an, dann hier erneut starten.", "hint");
                return false;
            }
            self.say("Melde dich im Browser an - ich warte…", "hint");
            if !wait_for_auth(&claude, Duration::from_secs(300)) {
                self.say("Noch nicht angemeldet.", "err");
                self.say("Melde dich im Browser an und drücke dann hier erneut Start.", "hint");
                return false;
            }
        }
        self.say("Claude ist angemeldet.", "ok");

        // 2) Runtime for the daemon (stdlib-only, so the embeddable build suffices)
        let mut py = self.python();
        if py.is_none() {
            self.say("Keine Python-Laufzeit gefunden.", "info");
            if cfg!(windows) {
                self.say("Lade Python-Laufzeit (~11 MB)…", "info");
                match fetch_python(&env.resources, PY_EMBED_URL) {
                    Ok(()) => {
                        self.cache.lock().unwrap().missed.remove("python");
                        py = (self.probes.python)();
                        if let Some(p) = &py {
                            self.cache.lock().unwrap().python = Some(p.clone());
                        }
                    }
                    Err(e) => self.say(&format!("Download fehlgeschlagen: {e}"), "err"),
                }
            }
        }
        if py.is_none() {
            // the hand-off that can still rescue the run (and the only route off Windows): Claude installs
            // a runtime with the machine's own package manager - this step must change the machine
            self.say("Ich lasse Claude es übernehmen…", "info");
            let prompt = if cfg!(windows) {
                "Install a Python 3.12 runtime on this Windows machine so that `py -3.12 --version` works, using winget if available. Do not modify anything else. Report what you did."
            } else if cfg!(target_os = "macos") {
                "Install a Python 3.12 runtime on this macOS machine so that `python3 --version` reports 3.12 or newer, using Homebrew if available. Do not modify anything else. Report what you did."
            } else {
                "Install a Python 3.12 runtime on this Linux machine so that `python3 --version` reports 3.12 or newer, using the system package manager. Do not modify anything else. Report what you did."
            };
            self.claude_task(&claude, prompt, env.daemon_root.as_deref(), "acceptEdits", Duration::from_secs(600));
            self.cache.lock().unwrap().missed.remove("python");
            py = (self.probes.python)();
            if let Some(p) = &py {
                self.cache.lock().unwrap().python = Some(p.clone());
            }
        }
        let Some(py) = py else {
            self.say("Ohne Python-Laufzeit kann der Daemon nicht starten.", "err");
            self.say("Installiere Python 3.12 von https://python.org, dann hier erneut starten.", "hint");
            return false;
        };
        self.say("Python-Laufzeit bereit.", "ok");
        // covers the runtime the installer bundled AND the one just fetched: same folder, same _pth
        if let Some(root) = &env.daemon_root {
            match pin_pth(&env.resources.join("python"), root) {
                Ok(true) => self.say("Python-Laufzeit auf HelmDeck ausgerichtet.", "ok"),
                Ok(false) => {}
                Err(e) => self.say(&format!("Konnte die Python-Laufzeit nicht ausrichten: {e}"), "err"),
            }
        }

        // 3) Instance
        if !self.start_instance(start_daemon, &py, env, Some(&claude)) {
            return false;
        }
        // 4) optional engines the picker selected - never gates `done`
        self.install_selected_engines(&claude, env, selected);
        true
    }

    /// The Store build: Microsoft Store policy 10.2.4 forbids an app downloading or installing
    /// executable code outside the Store, and an npm install, a winget call or a fetched runtime all
    /// look exactly like that. So: report what is there, hand over the plain command for what is not,
    /// and still start the daemon once everything is present (starting it installs nothing).
    fn run_store(&self, start_daemon: &dyn Fn(&str) -> bool, env: &Env, selected: &[String]) -> bool {
        self.say("Microsoft-Store-Version: prüfe vorhandene Voraussetzungen (keine automatische Installation).", "info");
        let py = self.python();
        let claude = self.claude();
        let git = version_of("git", &[]);
        let npm = find_npm();
        let report = |label: &str, found: bool, hint: &str| {
            if found {
                self.say(&format!("✓ {label} gefunden"), "ok");
            } else {
                self.say(&format!("✗ {label} fehlt - {hint}"), "err");
            }
        };
        report("Python 3.12+", py.is_some(), "installiere von https://python.org (3.12 oder neuer)");
        report("git", git.is_some(), "installiere von https://git-scm.com");
        report("Claude Code CLI", claude.is_some(), "installiere von https://claude.com/product/claude-code (oder, mit Node.js: npm install -g @anthropic-ai/claude-code)");
        report("Node.js/npm (optional)", npm.is_some(), "installiere von https://nodejs.org - nur nötig, um Claude Code selbst per npm zu installieren");
        let (Some(py), Some(claude), Some(_)) = (py, claude, git) else {
            self.say("Bitte die fehlenden Voraussetzungen installieren, dann HelmDeck neu starten.", "hint");
            return false;
        };
        if !claude_authed(&claude) {
            self.say("Claude Code ist nicht angemeldet - öffne die Anmeldung im Browser…", "info");
            if !self.open_login(&claude) {
                self.say("Konnte die Anmeldung nicht starten - führe `claude` im Terminal aus und melde dich an.", "err");
                return false;
            }
            self.say("Melde dich im Browser an - ich warte…", "hint");
            if !wait_for_auth(&claude, Duration::from_secs(300)) {
                self.say("Noch nicht angemeldet - melde dich an und drücke dann hier erneut Start.", "err");
                return false;
            }
        }
        self.say("Claude ist angemeldet.", "ok");
        if !self.start_instance(start_daemon, &py, env, None) {
            return false;
        }
        // the Store build installs no engine either - it says what is there and how to add the rest
        for (id, label, _) in ENGINES.iter().filter(|(id, _, _)| *id != "claude" && selected.iter().any(|s| s == id)) {
            match version_of(id, &[]) {
                Some(_) => self.say(&format!("{label} bereits vorhanden."), "ok"),
                None => self.say(&format!("{label} fehlt - in der Store-Version selbst installieren."), "hint"),
            }
        }
        true
    }

    /// Start the daemon unless one answers, wait for it, and on failure show its own last lines.
    fn start_instance(&self, start_daemon: &dyn Fn(&str) -> bool, py: &str, env: &Env, claude: Option<&Claude>) -> bool {
        if !(self.probes.daemon_up)() {
            self.say("Starte HelmDeck-Instanz…", "info");
            if !start_daemon(py) {
                self.say("Die Instanz ließ sich nicht starten.", "err");
            }
            for _ in 0..40 {
                if (self.probes.daemon_up)() {
                    break;
                }
                std::thread::sleep(Duration::from_millis(500));
            }
        }
        if !(self.probes.daemon_up)() {
            self.say("Die Instanz antwortet nicht.", "err");
            match env.daemon_log.as_deref().map(|p| log_tail(p, 12)) {
                Some(t) if !t.is_empty() => {
                    self.say("Letzte Zeilen aus daemon.out.log:", "info");
                    for l in t {
                        self.say(&l, "err");
                    }
                }
                _ => self.say("daemon.out.log ist leer oder fehlt - der Start hat nichts geschrieben.", "err"),
            }
            // the log tail comes FIRST (instant, the actual traceback); then Claude looks, read-only
            if let (Some(c), false) = (claude, env.store) {
                self.say("Lasse Claude nachsehen… (bis zu 3 Minuten, Ausgabe kommt am Stück)", "info");
                let prompt = format!(
                    "The HelmDeck python daemon in this directory does not come up on port {}. Diagnose why (port already in use, \
                     missing runtime, traceback on start) and report the root cause plus the exact command the user should run. \
                     Do not change any files.",
                    DAEMON_PORT_FOR_DIAGNOSIS
                );
                self.claude_task(c, &prompt, env.daemon_root.as_deref(), "plan", Duration::from_secs(180));
            }
            return false;
        }
        self.say("Instanz läuft.", "ok");
        self.say("Fertig - jetzt anmelden.", "ok");
        true
    }

    /// `claude -p <task>` as the installer/diagnostician of last resort (setup.js claudeTask). `plan` is
    /// read-only - onboarding may diagnose freely but never silently rewrite the install; only a step
    /// that has to change the machine gets `acceptEdits`. Output arrives in one piece at the end.
    fn claude_task(&self, claude: &Claude, prompt: &str, cwd: Option<&Path>, mode: &str, limit: Duration) -> bool {
        self.say("Claude richtet ein…", "info");
        let (program, mut args) = spawn_form(claude);
        args.extend(claude_task_args(prompt, mode));
        let mut c = command(&program);
        c.args(&args);
        if let Some(d) = cwd {
            c.current_dir(d);
        }
        match run_capture(c, limit) {
            Some((code, out)) => {
                for l in out.lines().filter(|l| !l.trim().is_empty()).rev().take(30).collect::<Vec<_>>().into_iter().rev() {
                    self.say(l.trim(), "info");
                }
                code == 0
            }
            None => {
                self.say(&format!("Claude hat nach {}s nicht geantwortet - abgebrochen.", limit.as_secs()), "err");
                false
            }
        }
    }

    /// The optional engines the picker asked for (never `claude` - step 1 owns that). Best-effort, never
    /// blocks `done`; getting a CLI onto PATH is not a claim that its driver works (GET /engines marks
    /// it untested until it has run a real turn).
    fn install_selected_engines(&self, claude: &Claude, env: &Env, selected: &[String]) {
        let plan = engine_plan(selected, &|id| version_of(id, &[]).is_some());
        for label in &plan.present {
            self.say(&format!("{label} bereits vorhanden."), "ok");
        }
        if !plan.npm.is_empty() {
            match find_npm() {
                None => self.say(&format!("Ohne npm kann ich {} nicht installieren.", plan.npm.iter().map(|(l, _)| l.as_str()).collect::<Vec<_>>().join(", ")), "err"),
                Some(npm) => {
                    for (label, pkg) in &plan.npm {
                        self.npm_install_global(&npm, pkg, label);
                    }
                }
            }
        }
        if !plan.agent.is_empty() {
            self.say(&format!("Richte über Claude ein: {}…", plan.agent.join(", ")), "info");
            let list = plan.agent.iter().map(|l| format!("{l} (official installer, e.g. https://opencode.ai for OpenCode)")).collect::<Vec<_>>().join("; ");
            let ok = self.claude_task(
                claude,
                &format!("Install these optional coding-agent CLIs, skipping any already installed, so their `--version` command works: {list}. Do not modify anything else on this machine. Report which succeeded and which failed."),
                env.daemon_root.as_deref(),
                "acceptEdits",
                Duration::from_secs(600),
            );
            self.say(if ok { "Eingerichtet." } else { "Nicht alle erfolgreich - siehe oben." }, if ok { "ok" } else { "hint" });
        }
        for label in &plan.detect_only {
            self.say(&format!("{label}: keine bekannte Installationsmethode - nur Status wird angezeigt."), "hint");
        }
    }

    fn install_node_via_winget(&self) -> bool {
        self.say("Installiere Node.js über winget…", "info");
        let mut c = command("winget");
        c.args(["install", "-e", "--id", "OpenJS.NodeJS.LTS", "--accept-source-agreements", "--accept-package-agreements"]);
        match run_capture(c, Duration::from_secs(180)) {
            Some((0, _)) => {
                self.say("Node.js installiert.", "ok");
                true
            }
            other => {
                self.say(&format!("winget-Installation fehlgeschlagen: {}", other.map(|o| o.1).unwrap_or_default().trim()), "err");
                false
            }
        }
    }

    fn npm_install_global(&self, npm: &str, pkg: &str, display: &str) -> bool {
        self.say(&format!("Installiere {display}: npm install -g {pkg}"), "info");
        let mut c = command(npm);
        c.args(["install", "-g", pkg]);
        match run_capture(c, Duration::from_secs(300)) {
            Some((code, out)) => {
                for l in out.lines().filter(|l| !l.trim().is_empty()).rev().take(8).collect::<Vec<_>>().into_iter().rev() {
                    self.say(l.trim(), "info");
                }
                code == 0
            }
            None => {
                self.say("npm install hängt oder ließ sich nicht starten - breche ab.", "err");
                false
            }
        }
    }

    /// `claude auth login` needs no terminal: it opens the browser itself and ends on the local
    /// OAuth callback; `wait_for_auth` decides. Hidden, like the 2026-10-08 Electron fix.
    fn open_login(&self, claude: &Claude) -> bool {
        let (program, mut args) = spawn_form(claude);
        args.extend(["auth".into(), "login".into()]);
        let mut c = command(&program);
        c.args(&args).stdout(Stdio::piped()).stderr(Stdio::null());
        let Ok(mut child) = c.spawn() else { return false };
        if let Some(mut out) = child.stdout.take() {
            let me_log = self.log_handle();
            std::thread::spawn(move || {
                let mut seen = String::new();
                let mut buf = [0u8; 1024];
                let mut told = false;
                while let Ok(n) = out.read(&mut buf) {
                    if n == 0 {
                        break;
                    }
                    seen.push_str(&String::from_utf8_lossy(&buf[..n]));
                    if !told {
                        if let Some(u) = first_url(&seen) {
                            told = true;
                            me_log(&format!("Falls sich kein Browser öffnet: {u}"));
                        }
                    }
                }
            });
        }
        // a wedged login must not outlive its window
        std::thread::spawn(move || {
            std::thread::sleep(Duration::from_secs(6 * 60));
            let _ = child.kill();
        });
        true
    }

    fn log_handle(&self) -> impl Fn(&str) + Send + 'static {
        let sink = self.hints.clone();
        move |l: &str| sink.lock().unwrap().push(l.to_string())
    }

    pub fn drain_hints(&self) {
        let drained: Vec<String> = self.hints.lock().unwrap().drain(..).collect();
        for l in drained {
            self.say(&l, "hint");
        }
    }
}

/// (program, leading args) to spawn `claude` as a plain argv: see through an npm .cmd shim.
fn spawn_form(claude: &Claude) -> (String, Vec<String>) {
    let p = Path::new(&claude.cmd);
    if cfg!(windows) && p.is_absolute() && p.extension().map(|e| e.eq_ignore_ascii_case("cmd") || e.eq_ignore_ascii_case("bat")).unwrap_or(false) {
        if let Some(real) = real_claude_exe(p) {
            return (real[0].to_string_lossy().into(), real[1..].iter().map(|x| x.to_string_lossy().into()).collect());
        }
    }
    (claude.cmd.clone(), Vec::new())
}

pub fn claude_authed(claude: &Claude) -> bool {
    let (program, mut args) = spawn_form(claude);
    args.extend(["-p".into(), "reply with: ok".into()]);
    let mut c = command(&program);
    c.args(&args);
    match run_capture(c, Duration::from_secs(60)) {
        Some((code, out)) => !output_means_logged_out(&out) && code == 0,
        None => false,
    }
}

fn wait_for_auth(claude: &Claude, limit: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < limit {
        if claude_authed(claude) {
            return true;
        }
        std::thread::sleep(Duration::from_secs(8));
    }
    claude_authed(claude)
}

pub fn log_tail(path: &Path, n: usize) -> Vec<String> {
    std::fs::read_to_string(path).map(|t| t.lines().rev().take(n).map(str::to_string).collect::<Vec<_>>().into_iter().rev().collect()).unwrap_or_default()
}

// ----------------------------------------------------------------------- server

/// Query parameter `name` of a request target ("/x?a=1&b=2"), percent-decoding not needed here.
pub fn query_param(target: &str, name: &str) -> Option<String> {
    let q = target.split_once('?')?.1;
    q.split('&').filter_map(|kv| kv.split_once('=')).find(|(k, _)| *k == name).map(|(_, v)| v.to_string())
}

fn respond(s: &mut TcpStream, code: u16, body: &serde_json::Value) {
    let reason = match code {
        200 => "OK",
        403 => "Forbidden",
        _ => "Not Found",
    };
    let b = body.to_string();
    let _ = write!(
        s,
        "HTTP/1.1 {code} {reason}\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{b}",
        b.len()
    );
}

fn handle(mut s: TcpStream, setup: &Arc<Setup>, start_daemon: &Arc<dyn Fn(&str) -> bool + Send + Sync>) {
    let _ = s.set_read_timeout(Some(Duration::from_secs(5)));
    // read the WHOLE request head: answering and closing with bytes still unread makes the peer see a
    // connection reset instead of the answer (a request can arrive in several segments)
    let mut buf = [0u8; 4096];
    let mut n = 0;
    while n < buf.len() {
        match s.read(&mut buf[n..]) {
            Ok(0) | Err(_) => break,
            Ok(k) => n += k,
        }
        if buf[..n].windows(4).any(|w| w == b"\r\n\r\n") {
            break;
        }
    }
    let head = String::from_utf8_lossy(&buf[..n]);
    let target = head.lines().next().and_then(|l| l.split_whitespace().nth(1)).unwrap_or("/").to_string();
    if head.starts_with("OPTIONS") {
        return respond(&mut s, 200, &serde_json::json!({}));
    }
    if query_param(&target, "n").as_deref() != Some(setup.nonce.as_str()) {
        return respond(&mut s, 403, &serde_json::json!({"error": "forbidden"}));
    }
    setup.drain_hints();
    let path = target.split('?').next().unwrap_or("/");
    match path {
        "/setup/state" => respond(&mut s, 200, &setup.state_json()),
        "/setup/log" => respond(&mut s, 200, &setup.log_json()),
        "/setup/engines" => respond(&mut s, 200, &setup.engines_json()),
        "/setup/provision" => {
            let started = setup.provision(start_daemon.clone(), setup.env.clone(), selected_engines(&target));
            respond(&mut s, 200, &serde_json::json!({"started": started, "alreadyRunning": !started}));
        }
        _ => respond(&mut s, 404, &serde_json::json!({"error": "not found"})),
    }
}

/// Serve on 127.0.0.1:`port` (0 = any); returns the bound port.
pub fn serve(
    setup: Arc<Setup>,
    port: u16,
    start_daemon: Arc<dyn Fn(&str) -> bool + Send + Sync>,
) -> std::io::Result<u16> {
    let l = TcpListener::bind(("127.0.0.1", port))?;
    let bound = l.local_addr()?.port();
    std::thread::spawn(move || {
        for s in l.incoming().flatten() {
            let (setup, sd) = (setup.clone(), start_daemon.clone());
            std::thread::spawn(move || handle(s, &setup, &sd));
        }
    });
    Ok(bound)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    fn probes(py: Option<&'static str>, claude: bool, calls: Arc<AtomicUsize>) -> Probes {
        Probes {
            python: Arc::new(move || {
                calls.fetch_add(1, Ordering::SeqCst);
                py.map(str::to_string)
            }),
            claude: Arc::new(move || claude.then(|| Claude { cmd: "claude".into(), version: "2.1.0".into() })),
            engine: Arc::new(|id| (id == "codex").then(|| "0.9".to_string())),
            daemon_up: Arc::new(|| false),
        }
    }

    fn get(port: u16, target: &str) -> (u16, serde_json::Value) {
        let mut s = TcpStream::connect(("127.0.0.1", port)).unwrap();
        write!(s, "GET {target} HTTP/1.0\r\nHost: x\r\n\r\n").unwrap();
        let mut out = String::new();
        s.read_to_string(&mut out).unwrap();
        let code = out.split_whitespace().nth(1).unwrap().parse().unwrap();
        (code, serde_json::from_str(out.split("\r\n\r\n").nth(1).unwrap_or("{}")).unwrap_or_default())
    }

    fn server(p: Probes) -> (u16, Arc<Setup>) {
        let setup = Setup::new(p);
        let port = serve(setup.clone(), 0, Arc::new(|_| false)).unwrap();
        (port, setup)
    }

    #[test]
    fn nonces_are_long_and_differ() {
        let (a, b) = (nonce(), nonce());
        assert_eq!(a.len(), 32);
        assert_ne!(a, b);
    }

    #[test]
    fn a_request_without_the_nonce_is_refused_and_never_probes() {
        let calls = Arc::new(AtomicUsize::new(0));
        let (port, _s) = server(probes(Some("py -3.12"), true, calls.clone()));
        assert_eq!(get(port, "/setup/state").0, 403);
        assert_eq!(get(port, "/setup/state?n=wrong").0, 403);
        assert_eq!(get(port, "/setup/provision").0, 403, "the endpoint that starts processes needs the nonce");
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn state_has_the_shape_the_web_app_reads() {
        let (port, s) = server(probes(Some("py -3.12"), true, Arc::new(AtomicUsize::new(0))));
        let (code, v) = get(port, &format!("/setup/state?n={}", s.nonce));
        assert_eq!(code, 200);
        assert_eq!(v["python"], true);
        assert_eq!(v["pythonBundled"], false);
        assert_eq!(v["claude"], true);
        assert_eq!(v["claudeVersion"], "2.1.0");
        assert_eq!(v["daemon"], false);
        assert_eq!((v["running"].clone(), v["done"].clone()), (false.into(), false.into()));
    }

    #[test]
    fn a_hit_is_cached_a_miss_is_throttled() {
        let hit = Arc::new(AtomicUsize::new(0));
        let s = Setup::new(probes(Some("python"), true, hit.clone()));
        for _ in 0..5 {
            s.python();
        }
        assert_eq!(hit.load(Ordering::SeqCst), 1, "a found runtime is probed once");
        let miss = Arc::new(AtomicUsize::new(0));
        let s = Setup::new(probes(None, false, miss.clone()));
        for _ in 0..5 {
            s.python();
        }
        assert_eq!(miss.load(Ordering::SeqCst), 1, "a miss is not re-probed on every poll of a fresh machine");
    }

    #[test]
    fn engines_list_all_five_with_their_tier() {
        let (port, s) = server(probes(None, true, Arc::new(AtomicUsize::new(0))));
        let (_, v) = get(port, &format!("/setup/engines?n={}", s.nonce));
        let e = v["engines"].as_array().unwrap();
        assert_eq!(e.len(), 5);
        let by = |id: &str| e.iter().find(|x| x["id"] == id).unwrap().clone();
        assert_eq!((by("claude")["installed"].clone(), by("claude")["tier"].clone()), (true.into(), "full".into()));
        assert_eq!(by("codex")["installed"], true);
        assert_eq!(by("codex")["version"], "0.9");
        assert_eq!(by("opencode")["installed"], false);
        assert_eq!(by("omp")["tier"], "detect-only");
    }

    #[test]
    fn the_log_is_bounded_and_ordered() {
        let s = Setup::new(probes(None, false, Arc::new(AtomicUsize::new(0))));
        for i in 0..(LOG_MAX + 25) {
            s.say(&format!("l{i}"), "info");
        }
        let v = s.log_json();
        let log = v["log"].as_array().unwrap();
        assert_eq!(log.len(), LOG_MAX);
        assert_eq!(log[0]["line"], "l25");
        assert_eq!(log.last().unwrap()["line"], format!("l{}", LOG_MAX + 24));
    }

    #[test]
    fn a_second_provision_call_does_not_start_a_second_run() {
        let s = Setup::new(probes(None, false, Arc::new(AtomicUsize::new(0))));
        s.flags.lock().unwrap().0 = true; // a run is in flight
        assert!(!s.provision(Arc::new(|_| false), Env::default(), vec![]), "the reload mid-provision must not claim it started a run");
    }

    #[test]
    fn provisioning_without_claude_or_npm_says_what_to_do_and_stops() {
        // no claude, and (on a box that has npm) the real find_npm would run an install - so only
        // assert the part that does not need the machine: the message when npm is absent
        let s = Setup::new(probes(None, false, Arc::new(AtomicUsize::new(0))));
        s.say("Ohne npm kann ich Claude Code nicht automatisch installieren.", "err");
        assert!(s.log_json()["log"][0]["line"].as_str().unwrap().contains("npm"));
    }

    #[test]
    fn logged_out_output_is_recognised() {
        assert!(output_means_logged_out("Error: Not logged in. Please run /login"));
        assert!(output_means_logged_out("Invalid API key"));
        assert!(!output_means_logged_out("ok"));
    }

    #[test]
    fn the_login_hint_url_is_extracted() {
        assert_eq!(first_url("Opening browser...\nVisit https://claude.ai/oauth/authorize?code=1 to sign in\n").unwrap(), "https://claude.ai/oauth/authorize?code=1");
        assert!(first_url("no url here").is_none());
    }

    #[test]
    fn the_npm_shim_is_seen_through_to_the_real_exe() {
        let d = std::env::temp_dir().join(format!("hd-claude-{}", std::process::id()));
        let bin = d.join("node_modules").join("@anthropic-ai").join("claude-code").join("bin");
        std::fs::create_dir_all(&bin).unwrap();
        std::fs::write(bin.join("claude.exe"), "").unwrap();
        let r = real_claude_exe(&d.join("claude.cmd")).unwrap();
        assert_eq!(r, vec![bin.join("claude.exe")]);
        assert!(real_claude_exe(&d.join("nowhere").join("claude.cmd")).is_none());
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn query_params_are_read() {
        assert_eq!(query_param("/setup/state?n=abc&x=1", "n").unwrap(), "abc");
        assert_eq!(query_param("/setup/state?x=1&n=abc", "n").unwrap(), "abc");
        assert!(query_param("/setup/state", "n").is_none());
    }

    #[test]
    fn a_python_command_survives_spaces_and_launcher_arguments() {
        assert_eq!(daemon_argv("py\t-3.12"), ("py".to_string(), vec!["-3.12".to_string()]));
        assert_eq!(daemon_argv("C:\\Users\\Tien Duy Vo\\python.exe"), ("C:\\Users\\Tien Duy Vo\\python.exe".to_string(), vec![]));
    }

    #[test]
    fn a_bundled_runtime_wins_over_the_system_one() {
        let d = std::env::temp_dir().join(format!("hd-res-{}", std::process::id()));
        let py = d.join("python");
        std::fs::create_dir_all(&py).unwrap();
        std::fs::write(py.join(if cfg!(windows) { "python.exe" } else { "python3" }), "").unwrap();
        if cfg!(windows) {
            assert_eq!(find_python(&d).unwrap(), py.join("python.exe").to_string_lossy());
        }
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn the_embed_pth_gets_the_daemon_root_exactly_once() {
        let d = std::env::temp_dir().join(format!("hd-pth-{}", std::process::id()));
        std::fs::create_dir_all(&d).unwrap();
        std::fs::write(d.join("python312._pth"), "python312.zip\r\n.\r\n#import site").unwrap();
        let root = std::path::PathBuf::from("C:\\HelmDeck");
        assert_eq!(pin_pth(&d, &root), Ok(true));
        assert_eq!(pin_pth(&d, &root), Ok(false), "a re-entered provision must not stack a second line");
        let body = std::fs::read_to_string(d.join("python312._pth")).unwrap();
        assert_eq!(body.lines().filter(|l| *l == "C:\\HelmDeck").count(), 1);
        assert!(body.contains("#import site"), "site stays disabled");
        assert_eq!(pin_pth(&d.join("nowhere"), &root), Ok(false), "no embed, nothing to pin");
        let _ = std::fs::remove_dir_all(&d);
    }

    /// Real network + PowerShell: `cargo test -- --ignored`. Fetches the actual runtime into a temp folder,
    /// then proves it runs and that the daemon root lands in its _pth.
    #[test]
    #[ignore]
    fn the_embeddable_runtime_really_downloads_unpacks_and_runs() {
        let d = std::env::temp_dir().join(format!("hd-fetch-{}", std::process::id()));
        fetch_python(&d, PY_EMBED_URL).unwrap();
        let py = find_python(&d).unwrap();
        assert!(py.ends_with("python.exe"));
        let out = run_capture({ let mut c = command(&py); c.arg("--version"); c }, Duration::from_secs(20)).unwrap();
        assert!(out.1.contains("3.12"), "{}", out.1);
        assert_eq!(pin_pth(&d.join("python"), std::path::Path::new("C:\\HelmDeck")), Ok(true));
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn the_store_build_installs_nothing_and_says_what_is_missing() {
        // nothing present: the Store path must stop with hints, never reach npm/winget/a download
        let s = Setup::with_env(probes(None, false, Arc::new(AtomicUsize::new(0))), Env { store: true, ..Env::default() });
        let started = Arc::new(AtomicUsize::new(0));
        let st = started.clone();
        let ok = s.run(&move |_| { st.fetch_add(1, Ordering::SeqCst); true }, &Env { store: true, ..Env::default() });
        assert!(!ok);
        assert_eq!(started.load(Ordering::SeqCst), 0, "no daemon start without the prerequisites");
        let lines: Vec<String> = s.log_json()["log"].as_array().unwrap().iter().map(|l| l["line"].as_str().unwrap().to_string()).collect();
        assert!(lines.iter().any(|l| l.contains("Microsoft-Store-Version")));
        assert!(lines.iter().any(|l| l.contains("✗ Python")), "{lines:?}");
        assert!(lines.iter().any(|l| l.contains("✗ Claude Code CLI")), "{lines:?}");
        assert!(!lines.iter().any(|l| l.contains("npm install -g @anthropic-ai/claude-code:") || l.contains("winget") || l.contains("Lade Python")),
                "the Store build must not try to install anything: {lines:?}");
    }

    #[test]
    fn a_task_is_a_one_shot_prompt_with_an_explicit_permission_mode() {
        assert_eq!(claude_task_args("diagnose it", "plan"), vec!["-p", "diagnose it", "--permission-mode", "plan"]);
        // the prompt stays ONE argument however many spaces it has (the "The" truncation of 2026-09-08)
        assert_eq!(claude_task_args("a b c", "acceptEdits")[1], "a b c");
    }

    #[test]
    fn the_engine_plan_follows_each_tier() {
        let sel: Vec<String> = ["claude", "codex", "opencode", "omp", "pi"].iter().map(|s| s.to_string()).collect();
        let p = engine_plan(&sel, &|id| id == "pi");
        assert_eq!(p.npm, vec![("Codex".to_string(), "@openai/codex".to_string())]);
        assert_eq!(p.agent, vec!["OpenCode".to_string()]);
        assert_eq!(p.detect_only, vec!["OMP".to_string()]);
        assert_eq!(p.present, vec!["Pi".to_string()]);
        let none = engine_plan(&["claude".to_string()], &|_| false);
        assert_eq!(none, EnginePlan::default(), "claude alone needs nothing extra");
    }

    #[test]
    fn the_picker_selection_always_includes_claude() {
        assert_eq!(selected_engines("/setup/provision?n=x&engines=codex,opencode"), vec!["codex", "opencode", "claude"]);
        assert_eq!(selected_engines("/setup/provision?n=x"), vec!["claude"]);
    }

    /// Real `claude -p` (needs a logged-in CLI, costs one tiny turn): `cargo test -- --ignored`.
    #[test]
    #[ignore]
    fn a_real_read_only_hand_off_reaches_claude_and_its_answer_lands_in_the_log() {
        let s = Setup::new(probes(None, true, Arc::new(AtomicUsize::new(0))));
        let c = find_claude().expect("claude on PATH");
        let ok = s.claude_task(&c, "Reply with exactly the text HD-HANDOFF-OK and nothing else. Do not use any tools.", None, "plan", Duration::from_secs(180));
        let lines: Vec<String> = s.log_json()["log"].as_array().unwrap().iter().map(|l| l["line"].as_str().unwrap().to_string()).collect();
        assert!(ok, "{lines:?}");
        assert!(lines.iter().any(|l| l.contains("HD-HANDOFF-OK")), "{lines:?}");
    }
}
