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
