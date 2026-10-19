// GUI binary in release; console in debug.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! HelmDeck desktop window in Tauri - PROTOTYPE of the Electron shell (surfaces/desktop/main.js).
//!
//! What it does, in the same terms as main.js:
//!   * serves the exported web app on http://localhost:3300 (ui_server, same caching rules);
//!   * opens ONE window on it, handing the app the daemon URL in the `#cfg` hash (no token: the
//!     web app logs in like any other client);
//!   * exposes `window.helmdeckNative` - app info, folder picker, login item - with the same
//!     shapes the web app already expects from the Electron preload;
//!   * opens external links in the real browser; one instance at a time.
//!
//! What it deliberately does NOT do: start or supervise the daemon (the tray owns that), the
//! first-run setup wizard (setup.js), the two updaters. See README.

mod setup;
mod store;
mod ui_server;
mod updater;

use std::path::PathBuf;
use std::sync::Arc;

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

const DAEMON_PORT: u16 = 8140;

/// `window.helmdeckNative` on top of Tauri's invoke. The whole-app updater is `updater.rs`; the UI
/// bundle is refreshed by the tray's update thread, so the JS-update calls answer "current".
const BRIDGE_JS: &str = r#"
(function () {
  var inv = function (c, a) { return window.__TAURI_INTERNALS__.invoke(c, a); };
  var current = function () { return Promise.resolve({ state: "current", version: null, message: null }); };
  var off = function () { return function () {}; };
  // the shell PUSHES each native-update status here (window.eval), the page never polls
  var listeners = [];
  window.__hdNativeUpdate = function (s) { listeners.slice().forEach(function (cb) { try { cb(s); } catch (e) {} }); };
  window.helmdeckNative = {
    getUpdateStatus: function () { return inv("update_status"); },
    onUpdateStatus: function (cb) {
      listeners.push(cb);
      return function () { listeners = listeners.filter(function (x) { return x !== cb; }); };
    },
    installUpdate: function () { inv("update_install"); },
    getJsUpdateStatus: current, onJsUpdateStatus: off, applyJsUpdateNow: function () {},
    pickFolder: function () { return inv("pick_folder"); },
    getAppInfo: function () { return inv("app_info"); },
    getLoginItem: function () { return inv("login_item_get"); },
    setLoginItem: function (enabled) { return inv("login_item_set", { enabled: !!enabled }); }
  };
})();
"#;

fn base64(input: &[u8]) -> String {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::new();
    for c in input.chunks(3) {
        let n = (c[0] as u32) << 16 | (*c.get(1).unwrap_or(&0) as u32) << 8 | *c.get(2).unwrap_or(&0) as u32;
        out.push(T[(n >> 18) as usize & 63] as char);
        out.push(T[(n >> 12) as usize & 63] as char);
        out.push(if c.len() > 1 { T[(n >> 6) as usize & 63] as char } else { '=' });
        out.push(if c.len() > 2 { T[n as usize & 63] as char } else { '=' });
    }
    out
}

/// encodeURIComponent for the base64 alphabet
fn url_component(s: &str) -> String {
    s.replace('+', "%2B").replace('/', "%2F").replace('=', "%3D")
}

fn window_url(setup: Option<(u16, &str)>) -> String {
    // like main.js: the daemon URL plus, when the control plane is up, its port and nonce (no credential)
    let cfg = match setup {
        Some((port, nonce)) => format!("{{\"baseUrl\":\"http://localhost:{DAEMON_PORT}\",\"setup\":{{\"port\":{port},\"nonce\":\"{nonce}\"}}}}"),
        None => format!("{{\"baseUrl\":\"http://localhost:{DAEMON_PORT}\"}}"),
    };
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    format!(
        "http://localhost:{}/?v={ts}#cfg={}",
        ui_server::UI_PORT,
        url_component(&base64(cfg.as_bytes()))
    )
}

fn open_external(url: &str) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        let _ = std::process::Command::new("rundll32")
            .args(["url.dll,FileProtocolHandler", url])
            .creation_flags(0x0800_0000)
            .spawn();
    }
    #[cfg(target_os = "macos")]
    {
        let _ = std::process::Command::new("open").arg(url).spawn();
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        let _ = std::process::Command::new("xdg-open").arg(url).spawn();
    }
}

#[tauri::command]
fn app_info() -> serde_json::Value {
    serde_json::json!({
        "shellVersion": env!("CARGO_PKG_VERSION"),
        // node's process.platform names, which is what the web app compares against
        "platform": if cfg!(windows) { "win32" } else if cfg!(target_os = "macos") { "darwin" } else { "linux" },
        "packaged": !cfg!(debug_assertions),
    })
}

#[tauri::command]
async fn pick_folder(app: tauri::AppHandle) -> Option<String> {
    use tauri_plugin_dialog::DialogExt;
    app.dialog().file().blocking_pick_folder().map(|p| p.to_string())
}

const RUN_KEY: &str = r"Software\Microsoft\Windows\CurrentVersion\Run";
const RUN_NAME: &str = "HelmDeckDesktop";

fn login_item() -> serde_json::Value {
    if store::packaged() {
        // the manifest's StartupTask (declared Enabled="false": opt-in by the user, never at first launch)
        return store::login_item_json(store::startup_task_state());
    }
    #[cfg(windows)]
    let on = {
        use winreg::{enums::HKEY_CURRENT_USER, RegKey};
        RegKey::predef(HKEY_CURRENT_USER)
            .open_subkey(RUN_KEY)
            .ok()
            .and_then(|k| k.get_value::<String, _>(RUN_NAME).ok())
            .is_some()
    };
    #[cfg(not(windows))]
    let on = false;
    serde_json::json!({ "openAtLogin": on, "status": null, "isMas": false })
}

#[tauri::command]
fn update_status(state: tauri::State<Arc<updater::Updater>>) -> serde_json::Value {
    state.status()
}

#[tauri::command]
fn update_install(app: tauri::AppHandle, state: tauri::State<Arc<updater::Updater>>) {
    state.install(&app);
}

#[tauri::command]
fn login_item_get() -> serde_json::Value {
    login_item()
}

#[tauri::command]
fn login_item_set(enabled: bool) -> serde_json::Value {
    if store::packaged() {
        // a Store app must not write the Run key: the toggle drives the StartupTask instead
        return store::login_item_json(store::startup_task_set(enabled));
    }
    #[cfg(windows)]
    {
        use winreg::{enums::HKEY_CURRENT_USER, RegKey};
        if let Ok((k, _)) = RegKey::predef(HKEY_CURRENT_USER).create_subkey(RUN_KEY) {
            if enabled {
                if let Ok(exe) = std::env::current_exe() {
                    let _ = k.set_value(RUN_NAME, &format!("\"{}\"", exe.display()));
                }
            } else {
                let _ = k.delete_value(RUN_NAME);
            }
        }
    }
    #[cfg(not(windows))]
    let _ = enabled;
    login_item()
}

/// Repo root: HELMDECK_ROOT, else walk up from the exe and the cwd until `daemon/swarm.py` exists.
fn find_root() -> Option<PathBuf> {
    let ok = |p: &std::path::Path| p.join("daemon").join("swarm.py").is_file();
    if let Ok(r) = std::env::var("HELMDECK_ROOT") {
        let p = PathBuf::from(r);
        if ok(&p) {
            return Some(p);
        }
    }
    // a macOS .app keeps the daemon sources in Contents/Resources (the exe is in Contents/MacOS)
    if let Some(res) = std::env::current_exe().ok().and_then(|e| e.parent().map(|d| d.join("..").join("Resources"))) {
        if ok(&res) {
            return Some(res);
        }
    }
    for start in [std::env::current_exe().ok(), std::env::current_dir().ok()].into_iter().flatten() {
        let mut d = start.parent().map(|p| p.to_path_buf());
        while let Some(cur) = d {
            if ok(&cur) {
                return Some(cur);
            }
            d = cur.parent().map(|p| p.to_path_buf());
        }
    }
    None
}

fn daemon_data_dir() -> Option<PathBuf> {
    if store::packaged() {
        return Some(store::data_root()); // the package dir is read-only
    }
    find_root().map(|r| std::env::var("HELMDECK_DATA_ROOT").ok().filter(|s| !s.trim().is_empty()).map(PathBuf::from).unwrap_or_else(|| r.join("daemon")))
}

/// Start `<python> -m daemon.swarm serve` hidden from the repo root (the tray does this for a
/// running install; this is the first-run path, before any tray exists).
fn start_daemon(python: &str) -> bool {
    if store::packaged() {
        return match find_root() {
            Some(root) => store::spawn_daemon(python, &root, &store::data_root(), DAEMON_PORT).is_ok(),
            None => false,
        };
    }
    let Some(root) = find_root() else { return false };
    let (program, lead) = setup::daemon_argv(python);
    if program.is_empty() {
        return false;
    }
    let mut c = std::process::Command::new(program);
    c.args(lead).args(["-m", "daemon.swarm", "serve"]).current_dir(&root).env("PYTHONUNBUFFERED", "1").stdin(std::process::Stdio::null());
    if let Some(dir) = daemon_data_dir() {
        if let Ok(f) = std::fs::OpenOptions::new().create(true).append(true).open(dir.join("daemon.out.log")) {
            if let Ok(f2) = f.try_clone() {
                c.stdout(f).stderr(f2);
            }
        }
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        c.creation_flags(0x0800_0000);
    }
    c.spawn().is_ok()
}

fn error_page(msg: &str) -> String {
    let html = format!(
        "<body style='background:#0b0f14;color:#e6edf3;font:16px system-ui;padding:48px'><h2>HelmDeck</h2><p>{msg}</p></body>"
    );
    let enc: String = html
        .bytes()
        .map(|b| if b.is_ascii_alphanumeric() { (b as char).to_string() } else { format!("%{b:02X}") })
        .collect();
    format!("data:text/html;charset=utf-8,{enc}")
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![app_info, pick_folder, login_item_get, login_item_set, update_status, update_install])
        .setup(|app| {
            let in_store = store::packaged();
            let upd = updater::Updater::new(in_store);
            app.manage(upd.clone());
            updater::start(app.handle().clone(), upd, in_store);
            let mut problem: Option<String> = None;
            if !ui_server::already_serving(ui_server::UI_PORT) {
                match ui_server::resolve_app_dist() {
                    Some(dist) => {
                        if let Err(e) = ui_server::serve(dist, ui_server::UI_PORT) {
                            problem = Some(format!("The UI server could not start on port {}: {e}", ui_server::UI_PORT));
                        }
                    }
                    None => {
                        problem = Some("The built web app (surfaces/app/dist) was not found. Set HELMDECK_APP_DIST.".into());
                    }
                }
            }
            // the first-run control plane: probes + provisioning, behind a per-launch nonce
            let resources = std::env::current_exe().ok().and_then(|e| e.parent().map(|p| p.to_path_buf())).unwrap_or_default();
            let env = setup::Env {
                resources: resources.clone(),
                daemon_root: find_root(),
                daemon_log: daemon_data_dir().map(|d| d.join("daemon.out.log")),
                store: in_store,
            };
            let setup = setup::Setup::with_env(setup::Probes::real(DAEMON_PORT, resources.clone()), env);
            let started = setup::serve(setup.clone(), setup::SETUP_PORT, Arc::new(start_daemon));
            // a Store install has no tray: the window starts the daemon itself (adopt-or-detach - one that
            // already answers is adopted, never a second one spawned; a spawned one outlives the window)
            // macOS has no tray at all (tray-rs is Windows-only), so there the window always owns the start
            if (in_store || cfg!(target_os = "macos")) && !setup::daemon_up(DAEMON_PORT) {
                if let (Some(root), Some(py)) = (find_root(), setup::find_python(&resources)) {
                    let _ = store::spawn_daemon(&py, &root, &store::data_root(), DAEMON_PORT);
                }
            }
            let url = match &problem {
                Some(p) => error_page(p),
                None => window_url(started.ok().map(|_| (setup::SETUP_PORT, setup.nonce.as_str()))),
            };
            let target: tauri::Url = url.parse().expect("window url");
            // Closing the window and reopening it at once (exactly what "close to load the update" asks
            // for) meets the previous WebView2 browser process still shutting down on the same user-data
            // folder: creation fails with 0x800700AA "requested resource is in use" and the setup hook
            // used to panic - the app simply did not start (2026-10-19). Wait for the folder, up to 10 s.
            let mut tries = 0;
            loop {
                match build_main_window(app, target.clone()) {
                    Ok(()) => return Ok(()),
                    Err(e) if tries < 20 && webview_busy(&e.to_string()) => {
                        tries += 1;
                        std::thread::sleep(std::time::Duration::from_millis(500));
                    }
                    Err(e) => return Err(e),
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running HelmDeck");
}

/// WebView2's "user-data folder still held by a browser process that is exiting" failure.
fn webview_busy(err: &str) -> bool {
    err.contains("0x800700AA") || err.contains("requested resource is in use")
}

fn build_main_window(app: &mut tauri::App, target: tauri::Url) -> Result<(), Box<dyn std::error::Error>> {
    WebviewWindowBuilder::new(app, "main", WebviewUrl::External(target))
                .title("HelmDeck")
                .inner_size(1360.0, 900.0)
                .background_color(tauri::window::Color(0x0b, 0x0f, 0x14, 0xff))
                .initialization_script(BRIDGE_JS)
                .on_navigation(|u| {
                    let local = matches!(u.host_str(), Some("localhost") | Some("127.0.0.1"));
                    if local || matches!(u.scheme(), "data" | "about" | "tauri") {
                        true
                    } else {
                        open_external(u.as_str());
                        false
                    }
                })
                .build()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base64_matches_the_standard_encoding() {
        assert_eq!(base64(b""), "");
        assert_eq!(base64(b"f"), "Zg==");
        assert_eq!(base64(b"fo"), "Zm8=");
        assert_eq!(base64(b"foo"), "Zm9v");
        assert_eq!(base64(b"foobar"), "Zm9vYmFy");
    }

    #[test]
    fn the_cfg_hash_decodes_to_the_daemon_url_like_main_js_builds_it() {
        let url = window_url(None);
        assert!(url.starts_with("http://localhost:3300/?v="), "{url}");
        let hash = url.split("#cfg=").nth(1).unwrap().replace("%2B", "+").replace("%2F", "/").replace("%3D", "=");
        // the same payload main.js base64-encodes: {"baseUrl":"http://localhost:8140"}
        assert_eq!(hash, base64(b"{\"baseUrl\":\"http://localhost:8140\"}"));
        assert!(!url.contains("token"), "no credential rides in the URL");
    }

    #[test]
    fn app_info_has_the_shape_the_web_app_reads() {
        let v = app_info();
        assert!(v["shellVersion"].is_string() && v["platform"].is_string() && v["packaged"].is_boolean());
        assert!(["win32", "darwin", "linux"].contains(&v["platform"].as_str().unwrap()));
    }

    #[test]
    fn the_error_page_is_a_data_url() {
        let p = error_page("boom <b>");
        assert!(p.starts_with("data:text/html;charset=utf-8,") && !p.contains('<') && p.contains("boom"));
    }
}
