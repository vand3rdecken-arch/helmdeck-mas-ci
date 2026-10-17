fn main() {
    // The four bridge commands are the ONLY thing the web page may call (window.helmdeckNative).
    // Tauri 2 refuses an app command from a remote origin unless it has a permission of its own.
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&["app_info", "pick_folder", "login_item_get", "login_item_set", "update_status", "update_install"]),
        ),
    )
    .expect("failed to run tauri-build");
}
