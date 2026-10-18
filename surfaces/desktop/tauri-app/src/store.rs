//! The Microsoft Store build: what changes when this exe runs from an MSIX package.
//!
//! Store mode is DERIVED from the runtime - the process has a package identity
//! (`GetCurrentPackageFullName`) - never configured. Same split as Electron's `process.windowsStore`:
//!
//! * no self-update (the Store updates the package; policy 10.2.4 forbids replacing it) - updater.rs;
//! * setup only DETECTS prerequisites, it installs nothing (no npm, winget, Python fetch) - setup.rs;
//! * the package directory is read-only, so the daemon's data lives in `data_root()`;
//! * there is no tray in a Store install, so the window starts the daemon itself (adopt-or-detach).

use std::path::{Path, PathBuf};

/// True when running from an MSIX/AppX package.
pub fn packaged() -> bool {
    #[cfg(windows)]
    {
        #[link(name = "kernel32")]
        extern "system" {
            fn GetCurrentPackageFullName(len: *mut u32, name: *mut u16) -> i32;
        }
        const APPMODEL_ERROR_NO_PACKAGE: i32 = 15700;
        let mut len = 0u32;
        let rc = unsafe { GetCurrentPackageFullName(&mut len, std::ptr::null_mut()) };
        rc != APPMODEL_ERROR_NO_PACKAGE
    }
    #[cfg(not(windows))]
    false
}

/// Writable home of the daemon's state in a Store install (the package dir is read-only).
/// %LOCALAPPDATA% of a packaged app is redirected into the package's own storage by Windows,
/// so this is also removed with the app.
pub fn data_root() -> PathBuf {
    let base = std::env::var("LOCALAPPDATA").map(PathBuf::from).unwrap_or_else(|_| std::env::temp_dir());
    base.join("HelmDeck").join("daemon-data")
}

/// The windowless twin of a python command (`find_python` form, tab-separated): python.exe is a
/// console binary, and with Windows Terminal as the default terminal its window shows up as a tab.
pub fn windowless(py: &str) -> String {
    let mut parts: Vec<String> = py.split('\t').map(str::to_string).collect();
    let Some(first) = parts.first().cloned() else { return py.to_string() };
    let p = Path::new(&first);
    let name = p.file_name().and_then(|n| n.to_str()).unwrap_or("").to_ascii_lowercase();
    let swapped = match name.as_str() {
        "py" | "py.exe" => Some(p.with_file_name(if name.ends_with(".exe") { "pyw.exe" } else { "pyw" })),
        "python.exe" => Some(p.with_file_name("pythonw.exe")),
        _ => None,
    };
    if let Some(w) = swapped {
        // a bare launcher name has no file to check; an absolute python.exe must have its twin
        if !w.is_absolute() || w.is_file() {
            parts[0] = w.to_string_lossy().into_owned();
        }
    }
    parts.join("\t")
}

/// Spawn the daemon DETACHED (it holds the phone's relay; closing the window must not take it
/// down) from `root`, data in `data`, output appended to `<data>/daemon.out.log`.
pub fn spawn_daemon(py: &str, root: &Path, data: &Path, port: u16) -> std::io::Result<u32> {
    let (program, lead) = crate::setup::daemon_argv(&windowless(py));
    std::fs::create_dir_all(data)?;
    let log = std::fs::OpenOptions::new().create(true).append(true).open(data.join("daemon.out.log"))?;
    let log2 = log.try_clone()?;
    let mut c = std::process::Command::new(program);
    c.args(lead)
        .args(["-m", "daemon.swarm", "serve", &port.to_string()])
        .current_dir(root)
        .env("PYTHONUNBUFFERED", "1")
        .env("HELMDECK_DATA_ROOT", data)
        .stdin(std::process::Stdio::null())
        .stdout(log)
        .stderr(log2);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
        c.creation_flags(CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP);
    }
    Ok(c.spawn()?.id())
}

/// TaskId of the StartupTask the MSIX manifest declares (ops/deploy/build_msix_tauri.py).
pub const STARTUP_TASK_ID: &str = "HelmDeckStartup";

/// What the web app's login-item toggle reads, from a Windows.ApplicationModel.StartupTaskState
/// (0 Disabled, 1 DisabledByUser, 2 Enabled, 3 DisabledByPolicy, 4 EnabledByPolicy). `status` tells the
/// UI WHY it is off: a task the user disabled in Windows Settings cannot be re-enabled by the app -
/// RequestEnableAsync leaves it off - so the toggle must not pretend.
pub fn login_item_json(state: Option<i32>) -> serde_json::Value {
    let (on, status) = match state {
        Some(2) => (true, "enabled"),
        Some(4) => (true, "enabled-by-policy"),
        Some(0) => (false, "disabled"),
        Some(1) => (false, "disabled-by-user"),
        Some(3) => (false, "disabled-by-policy"),
        _ => (false, "unavailable"),
    };
    serde_json::json!({ "openAtLogin": on, "status": status, "isMas": false })
}

/// The task's current state; None when there is no package or no such task.
pub fn startup_task_state() -> Option<i32> {
    #[cfg(windows)]
    {
        use windows::ApplicationModel::StartupTask;
        let task = StartupTask::GetAsync(&windows::core::HSTRING::from(STARTUP_TASK_ID)).ok()?.join().ok()?;
        task.State().ok().map(|s| s.0)
    }
    #[cfg(not(windows))]
    None
}

/// Enable (asks Windows; may show nothing and stay off if the user disabled it in Settings) or disable.
/// Returns the state afterwards.
pub fn startup_task_set(enable: bool) -> Option<i32> {
    #[cfg(windows)]
    {
        use windows::ApplicationModel::StartupTask;
        let task = StartupTask::GetAsync(&windows::core::HSTRING::from(STARTUP_TASK_ID)).ok()?.join().ok()?;
        if enable {
            let _ = task.RequestEnableAsync().ok()?.join();
        } else {
            let _ = task.Disable();
        }
        task.State().ok().map(|s| s.0)
    }
    #[cfg(not(windows))]
    {
        let _ = enable;
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn this_test_process_is_not_packaged() {
        assert!(!packaged(), "cargo test runs unpackaged; a false positive would switch off setup and updates");
    }

    #[test]
    fn the_launcher_becomes_its_windowless_twin() {
        assert_eq!(windowless("py\t-3.12"), "pyw\t-3.12");
        assert_eq!(windowless("python3"), "python3", "unknown names are left alone");
    }

    #[test]
    fn an_absolute_python_switches_only_when_pythonw_exists() {
        let d = std::env::temp_dir().join(format!("hd-pyw-{}", std::process::id()));
        std::fs::create_dir_all(&d).unwrap();
        let py = d.join("python.exe");
        std::fs::write(&py, "").unwrap();
        assert_eq!(windowless(&py.to_string_lossy()), py.to_string_lossy(), "no pythonw.exe: keep python.exe");
        std::fs::write(d.join("pythonw.exe"), "").unwrap();
        assert_eq!(windowless(&py.to_string_lossy()), d.join("pythonw.exe").to_string_lossy());
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn the_data_root_is_outside_any_package_dir() {
        let r = data_root();
        assert!(r.ends_with("HelmDeck\\daemon-data") || r.ends_with("HelmDeck/daemon-data"));
        assert!(!r.to_string_lossy().contains("WindowsApps"));
    }

    #[test]
    fn every_startup_task_state_maps_to_what_the_toggle_reads() {
        assert_eq!(login_item_json(Some(2))["openAtLogin"], true);
        assert_eq!(login_item_json(Some(4))["status"], "enabled-by-policy");
        assert_eq!(login_item_json(Some(0))["openAtLogin"], false);
        let user_off = login_item_json(Some(1));
        assert_eq!((user_off["openAtLogin"].clone(), user_off["status"].clone()), (false.into(), "disabled-by-user".into()));
        assert_eq!(login_item_json(None)["status"], "unavailable");
        assert_eq!(login_item_json(Some(2))["isMas"], false);
    }

    #[test]
    fn without_a_package_the_startup_task_is_simply_absent() {
        // unpackaged (cargo test): the WinRT call fails cleanly instead of panicking or faking a state
        assert_eq!(startup_task_state(), None);
        assert_eq!(startup_task_set(false), None);
    }
}
