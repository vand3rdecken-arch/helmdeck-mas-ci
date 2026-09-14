// window.helmdeckNative.pickFolder is the desktop-only native folder dialog
// (surfaces/desktop/preload.js -> main.js's "native:pick-folder" IPC handler).
// Everywhere else (phone, plain web, Mac web view) that bridge is undefined
// and the caller falls back to the existing free-text field - same guard
// shape as desktop_update.tsx's nativeBridge(). Kept react-native-free so
// it's unit-testable under the repo's plain-node selftest convention (see
// prompt_fallback.ts / __prompt_fallback_selftest__.ts).

export type FolderPicker = () => Promise<string | null>;

/** Returns the native picker function, or null when the bridge (or its
 *  pickFolder channel) isn't present - the caller uses this to decide
 *  whether to render the folder-browse button at all. */
export function getFolderPicker(): FolderPicker | null {
  if (typeof window === "undefined") return null;
  const bridge = (window as unknown as { helmdeckNative?: { pickFolder?: FolderPicker } }).helmdeckNative;
  return bridge?.pickFolder ?? null;
}
