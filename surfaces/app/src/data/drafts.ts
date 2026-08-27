import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

// Composer draft persistence — per surface (board / each card). Mirrors the
// storage strategy in config.ts: localStorage on web, expo-secure-store on
// native. Keyed by a caller-supplied draftKey (e.g. "card:<id>").
const isWeb = Platform.OS === "web";
const PREFIX = "helmdeck.draft.";

// SecureStore keys must be [A-Za-z0-9._-]; localStorage is unrestricted but we
// keep one canonical key shape across platforms.
function storeKey(draftKey: string): string {
  return PREFIX + draftKey.replace(/[^A-Za-z0-9._-]/g, "_");
}

export async function loadDraft(draftKey: string): Promise<string> {
  try {
    if (isWeb) return globalThis.localStorage?.getItem(storeKey(draftKey)) ?? "";
    return (await SecureStore.getItemAsync(storeKey(draftKey))) ?? "";
  } catch { return ""; }
}

export async function saveDraft(draftKey: string, text: string): Promise<void> {
  const k = storeKey(draftKey);
  try {
    if (!text) {
      if (isWeb) globalThis.localStorage?.removeItem(k);
      else await SecureStore.deleteItemAsync(k);
      return;
    }
    if (isWeb) globalThis.localStorage?.setItem(k, text);
    else await SecureStore.setItemAsync(k, text);
  } catch { /* storage unavailable */ }
}

// Composer picker state (model / thinking level / agent-permission mode) — same
// per-surface key, separate namespace so it never collides with the plain-text
// draft above. Without this the pickers were bare useState: any remount of the
// Composer (e.g. the card screen's `!k ? <Spinner> : <Chat>` branch flips for a
// tick whenever /tracks races back a non-array error object over the relay,
// which every turn triggers via invalidateQueries) silently reset the chosen
// model back to "auto" — reported as "model choice doesn't survive a turn".
export interface ComposerOpts { model?: string; thinking?: string; mode?: string }

export async function loadOpts(draftKey: string): Promise<ComposerOpts> {
  try {
    const raw = isWeb
      ? globalThis.localStorage?.getItem(storeKey("opts." + draftKey))
      : await SecureStore.getItemAsync(storeKey("opts." + draftKey));
    return raw ? (JSON.parse(raw) as ComposerOpts) : {};
  } catch { return {}; }
}

export async function saveOpts(draftKey: string, opts: ComposerOpts): Promise<void> {
  const k = storeKey("opts." + draftKey);
  try {
    const hasAny = opts.model || opts.thinking || opts.mode;
    if (!hasAny) {
      if (isWeb) globalThis.localStorage?.removeItem(k);
      else await SecureStore.deleteItemAsync(k);
      return;
    }
    const raw = JSON.stringify(opts);
    if (isWeb) globalThis.localStorage?.setItem(k, raw);
    else await SecureStore.setItemAsync(k, raw);
  } catch { /* storage unavailable */ }
}
