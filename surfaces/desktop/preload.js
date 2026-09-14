// The renderer is a plain web app loaded via loadURL (main.js's own comment:
// "NO token: the SPA logs in like any other client and keeps its own
// session") - deliberately no special Electron access, so this preload stays
// narrow: two read-only-plus-one-action channels, both closing the same gap
// (owner report 2026-08-26: the phone shows an "update available" banner,
// the desktop app showed nothing) for the app's TWO separate update
// mechanisms - the whole-shell installer (native-updater.js) and the JS
// bundle that ships everything else (updater.js, applies on quit/restart -
// invisible in the running window until then, which is what orphaned the
// settings-hub rollout this preload was added to fix). contextIsolation
// stays on; nothing here can reach fs/child_process/etc.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("helmdeckNative", {
  getUpdateStatus: () => ipcRenderer.invoke("native-update:get"),
  onUpdateStatus: (cb) => {
    const handler = (_event, status) => cb(status);
    ipcRenderer.on("native-update:changed", handler);
    return () => ipcRenderer.removeListener("native-update:changed", handler);
  },
  installUpdate: () => ipcRenderer.send("native-update:install"),

  getJsUpdateStatus: () => ipcRenderer.invoke("js-update:get"),
  onJsUpdateStatus: (cb) => {
    const handler = (_event, status) => cb(status);
    ipcRenderer.on("js-update:changed", handler);
    return () => ipcRenderer.removeListener("js-update:changed", handler);
  },
  applyJsUpdateNow: () => ipcRenderer.send("js-update:apply-now"),

  pickFolder: () => ipcRenderer.invoke("native:pick-folder"),
});
