// The renderer is a plain web app loaded via loadURL (main.js's own comment:
// "NO token: the SPA logs in like any other client and keeps its own
// session") - deliberately no special Electron access, so this preload stays
// narrow: ONE read-only channel, the native desktop-shell update status that
// native-updater.js already tracks but never surfaced past a log file (owner
// report 2026-08-26: the phone shows an "update available" banner, the
// desktop app showed nothing). contextIsolation stays on; nothing here can
// reach fs/child_process/etc - only get/onChange/install for this one thing.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("helmdeckNative", {
  getUpdateStatus: () => ipcRenderer.invoke("native-update:get"),
  onUpdateStatus: (cb) => {
    const handler = (_event, status) => cb(status);
    ipcRenderer.on("native-update:changed", handler);
    return () => ipcRenderer.removeListener("native-update:changed", handler);
  },
  installUpdate: () => ipcRenderer.send("native-update:install"),
});
