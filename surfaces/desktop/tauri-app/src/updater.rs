//! The whole-app updater (what `native-updater.js` + electron-updater do for the Electron shell).
//!
//! States are the ones the web app already renders (`ui/desktop_update.tsx`): unavailable,
//! checking, downloading, downloaded, current, error. A check runs at start and then every
//! 30 minutes; an update is DOWNLOADED in the background and only INSTALLED when the owner taps
//! "restart now" (`update_install`). Every update is verified against the public key in
//! `tauri.conf.json` before it is installed - the private half signs releases only.
//!
//! Status changes are PUSHED into the page (`window.__hdNativeUpdate`), not polled, and not through
//! Tauri events: the page is deliberately not allowed `event:listen` (see the e2e's least-privilege
//! check), so the shell evaluates one call in the window instead.

use std::sync::{Arc, Mutex};
use std::time::Duration;

use tauri::{AppHandle, Manager};
use tauri_plugin_updater::{Update, UpdaterExt};

pub const CHECK_EVERY: Duration = Duration::from_secs(30 * 60);

pub fn status_json(state: &str, version: Option<&str>, message: Option<&str>) -> serde_json::Value {
    serde_json::json!({ "state": state, "version": version, "message": message })
}

/// JS that hands one status to the bridge in the page (a no-op until the bridge exists).
pub fn push_script(status: &serde_json::Value) -> String {
    format!("window.__hdNativeUpdate&&window.__hdNativeUpdate({status})")
}

pub struct Updater {
    status: Mutex<serde_json::Value>,
    ready: Mutex<Option<(Update, Vec<u8>)>>,
}

impl Updater {
    pub fn new() -> Arc<Updater> {
        // a debug build has no installed location to replace and no release to compare with
        let first = if cfg!(debug_assertions) { "unavailable" } else { "checking" };
        Arc::new(Updater { status: Mutex::new(status_json(first, None, None)), ready: Mutex::new(None) })
    }

    pub fn status(&self) -> serde_json::Value {
        self.status.lock().unwrap().clone()
    }

    fn set(&self, app: &AppHandle, state: &str, version: Option<&str>, message: Option<&str>) {
        let s = status_json(state, version, message);
        *self.status.lock().unwrap() = s.clone();
        if let Some(w) = app.get_webview_window("main") {
            let _ = w.eval(push_script(&s));
        }
    }

    /// One check; downloads (not installs) when something newer is published.
    pub async fn check_once(&self, app: &AppHandle) {
        if self.ready.lock().unwrap().is_some() {
            return; // already downloaded and waiting for the owner's tap
        }
        self.set(app, "checking", None, None);
        let updater = match app.updater() {
            Ok(u) => u,
            Err(e) => return self.set(app, "error", None, Some(&e.to_string())),
        };
        match updater.check().await {
            Ok(Some(update)) => {
                let v = update.version.clone();
                self.set(app, "downloading", Some(&v), None);
                match update.download(|_, _| {}, || {}).await {
                    Ok(bytes) => {
                        *self.ready.lock().unwrap() = Some((update, bytes));
                        self.set(app, "downloaded", Some(&v), None);
                    }
                    Err(e) => self.set(app, "error", Some(&v), Some(&e.to_string())),
                }
            }
            Ok(None) => self.set(app, "current", None, None),
            Err(e) => self.set(app, "error", None, Some(&e.to_string())),
        }
    }

    /// The owner tapped "restart now": install the verified download and relaunch.
    pub fn install(&self, app: &AppHandle) {
        let taken = self.ready.lock().unwrap().take();
        if let Some((update, bytes)) = taken {
            if update.install(bytes).is_ok() {
                app.restart();
            }
        }
    }
}

/// Start the periodic check (release builds only).
pub fn start(app: AppHandle, u: Arc<Updater>) {
    if cfg!(debug_assertions) {
        return;
    }
    std::thread::spawn(move || loop {
        tauri::async_runtime::block_on(u.check_once(&app));
        std::thread::sleep(CHECK_EVERY);
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_status_has_the_shape_the_web_app_reads() {
        let s = status_json("downloaded", Some("0.2.0"), None);
        assert_eq!(s["state"], "downloaded");
        assert_eq!(s["version"], "0.2.0");
        assert!(s["message"].is_null());
        let e = status_json("error", None, Some("no feed"));
        assert_eq!(e["message"], "no feed");
        assert!(e["version"].is_null());
    }

    #[test]
    fn the_push_is_one_guarded_call_with_valid_json() {
        let js = push_script(&status_json("current", None, None));
        assert!(js.starts_with("window.__hdNativeUpdate&&window.__hdNativeUpdate("));
        let arg = js.trim_start_matches("window.__hdNativeUpdate&&window.__hdNativeUpdate(").trim_end_matches(')');
        assert_eq!(serde_json::from_str::<serde_json::Value>(arg).unwrap()["state"], "current");
    }

    #[test]
    fn a_debug_build_reports_unavailable_without_checking() {
        let u = Updater::new();
        assert_eq!(u.status()["state"], if cfg!(debug_assertions) { "unavailable" } else { "checking" });
    }
}
