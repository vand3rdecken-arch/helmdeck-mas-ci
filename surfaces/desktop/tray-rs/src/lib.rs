//! HelmDeck tray supervisor - logic, kept free of any UI so it can be tested.
//!
//! Rust prototype of surfaces/desktop/tray.py. Same contract, same traps:
//!
//! * Supervision is by HEALTH, not PID. ANY HTTP reply on the daemon port
//!   means a daemon is serving (even 401). The probe asks `/system/health`,
//!   which answers directly; `/` 302-redirects to the web UI, so probing it
//!   once measured the WEB server and let this supervisor spawn a rival whose
//!   singleton lock evicted the healthy daemon (2026-08-29).
//! * A daemon that is already serving is ADOPTED. We only spawn when the port
//!   is quiet AND our own child (if any) is gone.
//! * The daemon is started detached from any console, stdout/stderr appended
//!   to daemon/daemon.out.log (one log, whichever supervisor started it).
//!
//! State is derived on every tick from what the OS and the db say; nothing
//! here remembers a "daemon is up" flag.

use std::fs::{File, OpenOptions};
use std::io::{self, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::thread::sleep;
use std::time::Duration;

pub const DEFAULT_PORT: u16 = 8140;
pub const CREATE_NO_WINDOW: u32 = 0x0800_0000;
pub const RUN_KEY: &str = r"Software\Microsoft\Windows\CurrentVersion\Run";
pub const RUN_NAME: &str = "HelmDeck";

// ------------------------------------------------------------------ health

/// True when ANY HTTP reply comes back from 127.0.0.1:`port`.
pub fn health(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut s) = TcpStream::connect_timeout(&addr, Duration::from_secs(2)) else {
        return false;
    };
    let _ = s.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = s.set_write_timeout(Some(Duration::from_secs(2)));
    let req = b"GET /system/health HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
    if s.write_all(req).is_err() {
        return false;
    }
    let mut buf = [0u8; 5];
    let mut n = 0;
    while n < buf.len() {
        match s.read(&mut buf[n..]) {
            Ok(0) | Err(_) => break,
            Ok(k) => n += k,
        }
    }
    n == buf.len() && &buf == b"HTTP/"
}

// ------------------------------------------------------------ relay status

/// "gekoppelt" / "wartet auf Kopplung" / "nicht konfiguriert" / "unbekannt".
/// `raw` is the JSON of the `relay` row (settings.relay), None when unreadable.
pub fn relay_status_from_json(raw: Option<&str>) -> String {
    let Some(raw) = raw else {
        return "unbekannt".into();
    };
    let Ok(v) = serde_json::from_str::<serde_json::Value>(raw) else {
        return "unbekannt".into();
    };
    let s = |k: &str| v.get(k).and_then(|x| x.as_str()).unwrap_or("").trim().to_string();
    if s("url").is_empty() || s("room").is_empty() {
        return "nicht konfiguriert".into();
    }
    if !s("phone_pub").is_empty() {
        return "gekoppelt".into();
    }
    // devices paired after the first phone live in the pinned list
    let pinned = v
        .get("pubs")
        .and_then(|x| x.as_array())
        .map(|a| !a.is_empty())
        .unwrap_or(false);
    if pinned { "gekoppelt".into() } else { "wartet auf Kopplung".into() }
}

/// Reads the relay row straight from helmdeck.db (WAL allows a concurrent
/// reader process; the daemon's own loader does the same), falling back to the
/// legacy settings.json like tray.py does.
pub fn relay_status(daemon_dir: &Path) -> String {
    use rusqlite::{Connection, OpenFlags};
    let db = daemon_dir.join("helmdeck.db");
    let from_db = Connection::open_with_flags(
        &db,
        OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .ok()
    .and_then(|c| {
        let _ = c.busy_timeout(Duration::from_secs(2));
        c.query_row("SELECT value FROM workspace_config WHERE key='relay'", [], |r| {
            r.get::<_, String>(0)
        })
        .ok()
    });
    if let Some(raw) = from_db {
        return relay_status_from_json(Some(&raw));
    }
    let legacy = std::fs::read_to_string(daemon_dir.join("settings.json"))
        .ok()
        .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok())
        .and_then(|v| v.get("relay").map(|r| r.to_string()));
    relay_status_from_json(legacy.as_deref())
}

// -------------------------------------------------------------- daemon spawn

/// Repo root: --root, HELMDECK_ROOT, then walk up from the exe and from the
/// cwd until `daemon/swarm.py` exists.
pub fn find_root(arg: Option<&str>) -> Option<PathBuf> {
    let ok = |p: &Path| p.join("daemon").join("swarm.py").is_file();
    if let Some(a) = arg {
        let p = PathBuf::from(a);
        return ok(&p).then_some(p);
    }
    if let Ok(e) = std::env::var("HELMDECK_ROOT") {
        let p = PathBuf::from(e);
        if ok(&p) {
            return Some(p);
        }
    }
    let starts = [std::env::current_exe().ok(), std::env::current_dir().ok()];
    for start in starts.into_iter().flatten() {
        let mut cur: Option<&Path> = Some(start.as_path());
        while let Some(p) = cur {
            if ok(p) {
                return Some(p.to_path_buf());
            }
            cur = p.parent();
        }
    }
    None
}

/// pythonw.exe for the daemon: HELMDECK_PYTHON, then the per-user 3.12
/// install (the interpreter the live daemon runs on), then PATH.
pub fn find_python() -> Option<PathBuf> {
    if let Ok(p) = std::env::var("HELMDECK_PYTHON") {
        let p = PathBuf::from(p);
        if p.is_file() {
            return Some(p);
        }
    }
    if let Ok(local) = std::env::var("LOCALAPPDATA") {
        let p = PathBuf::from(local).join(r"Programs\Python\Python312\pythonw.exe");
        if p.is_file() {
            return Some(p);
        }
    }
    let path = std::env::var_os("PATH")?;
    std::env::split_paths(&path)
        .map(|d| d.join("pythonw.exe"))
        .find(|p| p.is_file())
}

/// daemon.out.log, or a pid-suffixed file when another process pins the
/// canonical name (a supervisor must not go dark until the next reboot).
pub fn open_daemon_log(daemon_dir: &Path) -> io::Result<File> {
    let canonical = daemon_dir.join("daemon.out.log");
    match OpenOptions::new().create(true).append(true).open(&canonical) {
        Ok(f) => Ok(f),
        Err(_) => {
            let fb = daemon_dir.join(format!("daemon.out.{}.log", std::process::id()));
            let mut f = OpenOptions::new().create(true).append(true).open(fb)?;
            let _ = writeln!(f, "[tray] daemon.out.log unavailable - logging here instead");
            Ok(f)
        }
    }
}

/// Start `python -m daemon.swarm serve [port]` from the repo root, hidden.
pub fn spawn_daemon(root: &Path, python: &Path, port: u16) -> io::Result<Child> {
    let daemon_dir = root.join("daemon");
    let log = open_daemon_log(&daemon_dir)?;
    let log2 = log.try_clone()?;
    let mut cmd = Command::new(python);
    cmd.args(["-m", "daemon.swarm", "serve"]);
    if port != DEFAULT_PORT {
        cmd.arg(port.to_string());
    }
    cmd.current_dir(root)
        .env("PYTHONUNBUFFERED", "1")
        .creation_flags(CREATE_NO_WINDOW)
        .stdin(Stdio::null())
        .stdout(log)
        .stderr(log2)
        .spawn()
}

// ----------------------------------------------------------------- supervisor

/// Keeps exactly one daemon serving. `probe` and `spawn` are injected so the
/// state machine is tested against a stub server, never the live daemon.
pub struct Supervisor<P, S>
where
    P: FnMut() -> bool,
    S: FnMut() -> io::Result<Child>,
{
    probe: P,
    spawn: S,
    child: Option<Child>,
    /// polls to wait for a fresh daemon to bind, and the pause between them
    pub bind_polls: u32,
    pub bind_pause: Duration,
}

impl<P, S> Supervisor<P, S>
where
    P: FnMut() -> bool,
    S: FnMut() -> io::Result<Child>,
{
    pub fn new(probe: P, spawn: S) -> Self {
        Supervisor { probe, spawn, child: None, bind_polls: 20, bind_pause: Duration::from_secs(1) }
    }

    fn child_gone(&mut self) -> bool {
        match self.child.as_mut() {
            None => true,
            Some(c) => c.try_wait().map(|r| r.is_some()).unwrap_or(true),
        }
    }

    /// pid of the daemon WE started, if it is still ours and alive.
    pub fn our_pid(&mut self) -> Option<u32> {
        if self.child_gone() { None } else { self.child.as_ref().map(|c| c.id()) }
    }

    /// One beat. Returns whether a daemon is serving afterwards.
    pub fn tick(&mut self) -> bool {
        let mut up = (self.probe)();
        if !up && self.child_gone() {
            self.child = (self.spawn)().ok();
            if self.child.is_some() {
                for _ in 0..self.bind_polls {
                    if (self.probe)() {
                        break;
                    }
                    sleep(self.bind_pause);
                }
            }
            up = (self.probe)();
        }
        up
    }

    /// Stop OUR daemon (the next tick respawns it). An adopted daemon is not
    /// ours to stop - same as tray.py. Returns whether something was stopped.
    pub fn restart(&mut self) -> bool {
        let Some(mut c) = self.child.take() else {
            return false;
        };
        if c.try_wait().map(|r| r.is_none()).unwrap_or(false) {
            let _ = c.kill();
            let _ = c.wait();
            true
        } else {
            false
        }
    }
}

// ------------------------------------------------------------------ autostart

pub fn autostart_cmd(exe: &Path, root: &Path) -> String {
    format!("\"{}\" --root \"{}\"", exe.display(), root.display())
}

pub fn autostart_value() -> Option<String> {
    use winreg::{enums::HKEY_CURRENT_USER, RegKey};
    RegKey::predef(HKEY_CURRENT_USER)
        .open_subkey(RUN_KEY)
        .ok()?
        .get_value::<String, _>(RUN_NAME)
        .ok()
        .filter(|v| !v.is_empty())
}

pub fn set_autostart(on: bool, cmd: &str) -> io::Result<()> {
    use winreg::{enums::HKEY_CURRENT_USER, RegKey};
    let (key, _) = RegKey::predef(HKEY_CURRENT_USER).create_subkey(RUN_KEY)?;
    if on {
        key.set_value(RUN_NAME, &cmd)
    } else {
        match key.delete_value(RUN_NAME) {
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(()),
            r => r,
        }
    }
}

// ----------------------------------------------------------------------- icon

const SIZE: u32 = 64;

fn in_round_rect(x: f32, y: f32, l: f32, t: f32, r: f32, b: f32, rad: f32) -> bool {
    if x < l || x > r || y < t || y > b {
        return false;
    }
    let cx = x.clamp(l + rad, r - rad);
    let cy = y.clamp(t + rad, b - rad);
    (x - cx).powi(2) + (y - cy).powi(2) <= rad * rad
}

fn in_rect(x: f32, y: f32, l: f32, t: f32, r: f32, b: f32) -> bool {
    x >= l && x <= r && y >= t && y <= b
}

/// One sample of the badge: HelmDeck-blue rounded square, a 4 px ring that is
/// green when the daemon serves and red when it is down, a white blocky H.
fn sample(x: f32, y: f32, ok: bool) -> [f32; 4] {
    let blue = [47.0, 128.0, 237.0, 255.0];
    let ring = if ok { [52.0, 199.0, 89.0, 255.0] } else { [255.0, 69.0, 58.0, 255.0] };
    let white = [255.0, 255.0, 255.0, 255.0];
    // pixel-edge coordinates of PIL's inclusive [2, 2, 61, 61]
    let (l, t, r, b) = (2.0, 2.0, 62.0, 62.0);
    if !in_round_rect(x, y, l, t, r, b, 14.0) {
        return [0.0; 4];
    }
    if !in_round_rect(x, y, l + 4.0, t + 4.0, r - 4.0, b - 4.0, 10.0) {
        return ring;
    }
    let h = in_rect(x, y, 22.0, 18.0, 28.0, 47.0)
        || in_rect(x, y, 37.0, 18.0, 43.0, 47.0)
        || in_rect(x, y, 22.0, 29.0, 43.0, 36.0);
    if h { white } else { blue }
}

/// 64x64 RGBA, 4x4 supersampled so the 16/32 px tray scaling stays clean.
pub fn icon_rgba(ok: bool) -> (Vec<u8>, u32, u32) {
    const SS: u32 = 4;
    let mut out = Vec::with_capacity((SIZE * SIZE * 4) as usize);
    for py in 0..SIZE {
        for px in 0..SIZE {
            let (mut acc, mut a) = ([0.0f32; 3], 0.0f32);
            for sy in 0..SS {
                for sx in 0..SS {
                    let x = px as f32 + (sx as f32 + 0.5) / SS as f32;
                    let y = py as f32 + (sy as f32 + 0.5) / SS as f32;
                    let c = sample(x, y, ok);
                    let w = c[3] / 255.0;
                    for i in 0..3 {
                        acc[i] += c[i] * w;
                    }
                    a += w;
                }
            }
            let n = (SS * SS) as f32;
            if a > 0.0 {
                out.extend_from_slice(&[
                    (acc[0] / a) as u8,
                    (acc[1] / a) as u8,
                    (acc[2] / a) as u8,
                    (a / n * 255.0) as u8,
                ]);
            } else {
                out.extend_from_slice(&[0, 0, 0, 0]);
            }
        }
    }
    (out, SIZE, SIZE)
}

pub fn write_icon_png(path: &Path, ok: bool) -> io::Result<()> {
    let (rgba, w, h) = icon_rgba(ok);
    let f = File::create(path)?;
    let mut enc = png::Encoder::new(io::BufWriter::new(f), w, h);
    enc.set_color(png::ColorType::Rgba);
    enc.set_depth(png::BitDepth::Eight);
    let mut wr = enc.write_header().map_err(io::Error::other)?;
    wr.write_image_data(&rgba).map_err(io::Error::other)
}

pub fn tooltip(daemon: bool, relay: &str) -> String {
    format!("HelmDeck - Daemon: {} | Relay: {}", if daemon { "läuft" } else { "aus" }, relay)
}

// ---------------------------------------------------------------------- tests

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    fn stub_server(reply: &'static [u8]) -> u16 {
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = l.local_addr().unwrap().port();
        std::thread::spawn(move || {
            for s in l.incoming() {
                if let Ok(mut s) = s {
                    let mut b = [0u8; 256];
                    let _ = s.read(&mut b);
                    let _ = s.write_all(reply);
                }
            }
        });
        port
    }

    fn free_port() -> u16 {
        TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port()
    }

    #[test]
    fn any_http_reply_is_alive_even_401() {
        let p = stub_server(b"HTTP/1.0 401 Unauthorized\r\n\r\n");
        assert!(health(p), "an auth-gated reply must count as ALIVE");
    }

    #[test]
    fn closed_port_and_non_http_are_down() {
        assert!(!health(free_port()), "nothing listening");
        let p = stub_server(b"SSH-2.0-notahttpserver\r\n");
        assert!(!health(p), "a listener that is not speaking HTTP is not the daemon");
    }

    #[test]
    fn relay_status_matches_tray_py() {
        assert_eq!(relay_status_from_json(None), "unbekannt");
        assert_eq!(relay_status_from_json(Some("not json")), "unbekannt");
        assert_eq!(relay_status_from_json(Some("{}")), "nicht konfiguriert");
        assert_eq!(relay_status_from_json(Some(r#"{"url":"https://r","room":""}"#)), "nicht konfiguriert");
        assert_eq!(
            relay_status_from_json(Some(r#"{"url":"https://r","room":"x"}"#)),
            "wartet auf Kopplung"
        );
        assert_eq!(
            relay_status_from_json(Some(r#"{"url":"https://r","room":"x","phone_pub":"k"}"#)),
            "gekoppelt"
        );
        assert_eq!(
            relay_status_from_json(Some(r#"{"url":"https://r","room":"x","pubs":["a"]}"#)),
            "gekoppelt",
            "a device pinned after the first phone still counts as paired"
        );
    }

    #[test]
    fn icon_is_a_badge_with_a_state_coloured_ring() {
        let (up, w, h) = icon_rgba(true);
        let (down, _, _) = icon_rgba(false);
        assert_eq!((w, h, up.len()), (64, 64, 64 * 64 * 4));
        let px = |v: &Vec<u8>, x: usize, y: usize| {
            let i = (y * 64 + x) * 4;
            [v[i], v[i + 1], v[i + 2], v[i + 3]]
        };
        assert_eq!(px(&up, 0, 0)[3], 0, "outside the rounded square is transparent");
        assert_eq!(px(&up, 32, 3), [52, 199, 89, 255], "ring is green while up");
        assert_eq!(px(&down, 32, 3), [255, 69, 58, 255], "ring is red while down");
        assert_eq!(px(&up, 24, 30), [255, 255, 255, 255], "left bar of the H");
        assert_eq!(px(&up, 32, 32), [255, 255, 255, 255], "H crossbar");
        assert_eq!(px(&up, 32, 22), [47, 128, 237, 255], "badge blue between the bars");
    }

    fn python_http(port: u16) -> io::Result<Child> {
        Command::new("python")
            .args(["-m", "http.server", &port.to_string(), "--bind", "127.0.0.1"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
    }

    #[test]
    fn supervisor_spawns_when_quiet_adopts_when_serving_and_respawns_after_death() {
        let port = free_port();
        let mut sv = Supervisor::new(move || health(port), move || python_http(port));
        sv.bind_pause = Duration::from_millis(250);
        sv.bind_polls = 40;

        assert!(sv.tick(), "quiet port -> spawn -> serving");
        let first = sv.our_pid().expect("we own the child");
        assert!(sv.tick());
        assert_eq!(sv.our_pid(), Some(first), "a serving daemon is not respawned");

        // the daemon dies behind our back: next beat brings a new one
        let mut c = sv.child.take().unwrap();
        c.kill().unwrap();
        let _ = c.wait();
        sleep(Duration::from_millis(400));
        assert!(sv.tick(), "dead daemon is replaced");
        assert_ne!(sv.our_pid(), Some(first));

        assert!(sv.restart(), "restart stops OUR child");
        assert!(sv.tick(), "...and the next beat respawns it");
        sv.restart();
    }

    #[test]
    fn supervisor_adopts_an_external_daemon_and_never_spawns_a_rival() {
        let port = stub_server(b"HTTP/1.0 401 Unauthorized\r\n\r\n");
        let spawns = std::cell::Cell::new(0);
        let mut sv = Supervisor::new(move || health(port), || {
            spawns.set(spawns.get() + 1);
            Err(io::Error::other("must not be called"))
        });
        assert!(sv.tick());
        assert!(sv.our_pid().is_none(), "adopted, not ours");
        assert!(!sv.restart(), "an adopted daemon is not ours to stop");
        drop(sv);
        assert_eq!(spawns.get(), 0, "the spawn closure was never reached");
    }

    #[test]
    fn watch_only_survives_a_failing_spawn() {
        let port = free_port();
        let mut sv = Supervisor::new(move || health(port), || Err(io::Error::other("watch-only")));
        sv.bind_pause = Duration::from_millis(1);
        assert!(!sv.tick(), "nothing serving and nothing allowed to spawn -> down, no panic");
    }

    #[test]
    fn autostart_command_is_quoted_and_carries_the_root() {
        let c = autostart_cmd(Path::new(r"C:\Program Files\HelmDeck\helmdeck-tray.exe"), Path::new(r"C:\Users\x y\swarmdeck"));
        assert_eq!(
            c,
            r#""C:\Program Files\HelmDeck\helmdeck-tray.exe" --root "C:\Users\x y\swarmdeck""#
        );
    }

    #[test]
    fn root_is_found_by_walking_up() {
        let t = std::env::temp_dir().join(format!("hd-root-{}", std::process::id()));
        std::fs::create_dir_all(t.join("daemon")).unwrap();
        std::fs::write(t.join("daemon").join("swarm.py"), "").unwrap();
        assert_eq!(find_root(Some(t.to_str().unwrap())), Some(t.clone()));
        assert_eq!(find_root(Some(r"C:\definitely\not\here")), None);
        let _ = std::fs::remove_dir_all(&t);
    }
}
