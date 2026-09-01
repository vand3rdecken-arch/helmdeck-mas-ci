// The ACCOUNT's profile, client side (accounts-boards-prd phase 1).
//
// THE BOUNDARY this file exists to hold: config = account, credentials =
// device. Everything here is a CACHE of something the daemon owns, never the
// original. Pairing material (relay room, keypairs, tokens) lives in config.ts
// and expo-secure-store and must never travel to the server; a language does
// the exact opposite - it belongs to the account and follows the person to
// every device they sign in on.
//
// Three jobs:
//
//  1. HYDRATION ORDER. The cache renders instantly on launch (offline, or
//     before /me answers), then GET /me overwrites it. That order is why the
//     cache exists at all: without it, every cold start on a slow relay paints
//     the workspace default language for a second and then snaps to the
//     account's - a visible flicker on the most-looked-at surface there is.
//
//  2. THE ONE-TIME DEVICE -> ACCOUNT PUSH. `migrateIfLegacy` offers the
//     cache's values to an account that has none. It reads the CACHE, never
//     the OS locale: a locale is what the device happens to be set to, not a
//     preference the person expressed in HelmDeck, and pushing it up would
//     both invent a choice nobody made and suppress the first-login language
//     step (which exists precisely to ask). A device with no cache has nothing
//     to migrate, and says so by writing nothing.
//     "Exactly once" is NOT enforced here. The daemon's `migrate: true` only
//     fills absent keys, so a re-run is a no-op even if this code runs twice,
//     the app is reinstalled, or two devices race. A client-side "did I
//     already migrate" flag would be exactly the stored-flag reconstruction
//     the no-monkey-patch law forbids.
//
//  3. WRITE-THROUGH. A profile edit goes to the daemon AND the cache, so the
//     next cold start is already right.
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

import { api } from "@/data/client";
import type { Me, Profile } from "@/data/types";

const isWeb = Platform.OS === "web";
const KEY = "helmdeck.profile";

let memo: Profile | null = null;   // survives a remount; the store is async on native

/** Last-known account profile. Synchronous by design - the render path cannot
 *  await, and a missing cache must degrade to "no opinion" (null), never to a
 *  guessed default that would out-rank the daemon's answer. */
export function cachedProfile(): Profile | null {
  if (memo) return memo;
  try {
    if (isWeb) {
      const raw = globalThis.localStorage?.getItem(KEY);
      if (raw) memo = JSON.parse(raw) as Profile;
    }
  } catch { /* storage unavailable or corrupt - no opinion */ }
  return memo;
}

/** Native's SecureStore is async, so the cache is warmed once at boot; on web
 *  cachedProfile() already reads synchronously and this is a no-op. */
export async function warmProfileCache(): Promise<void> {
  if (isWeb || memo) return;
  try {
    const raw = await SecureStore.getItemAsync(KEY);
    if (raw) memo = JSON.parse(raw) as Profile;
  } catch { /* storage unavailable */ }
}

export async function cacheProfile(p: Profile | undefined | null): Promise<void> {
  if (!p) return;
  memo = p;
  try {
    const raw = JSON.stringify(p);
    if (isWeb) globalThis.localStorage?.setItem(KEY, raw);
    else await SecureStore.setItemAsync(KEY, raw);
  } catch { /* storage unavailable - the daemon still has the truth */ }
}

/** Forget the cache. Called on logout: the next person to sign in on this
 *  device must not inherit the previous account's view for the one frame
 *  before /me answers. */
export async function clearProfileCache(): Promise<void> {
  memo = null;
  try {
    if (isWeb) globalThis.localStorage?.removeItem(KEY);
    else await SecureStore.deleteItemAsync(KEY);
  } catch { /* storage unavailable */ }
}

/** Write my own profile rows and keep the cache in step. */
export async function saveProfile(patch: Partial<Profile>): Promise<Profile> {
  const r = await api.saveMyConfig(patch);
  await cacheProfile(r.profile);
  return r.profile;
}

/** The one-time device->account push (job 2 above). Returns the keys that
 *  actually landed - empty when there was nothing to offer OR when the account
 *  already had a profile, which are both correct outcomes and neither an
 *  error. */
export async function migrateIfLegacy(me: Me | undefined): Promise<string[]> {
  if (!me || (me.profile_keys?.length ?? 0) > 0) return [];   // account already speaks for itself
  const local = cachedProfile();
  if (!local) return [];                                      // nothing local to hand up
  const patch: Partial<Profile> = {};
  if (local.lang) patch.lang = local.lang;
  if (local.appearance) patch.appearance = local.appearance;
  if (!Object.keys(patch).length) return [];
  try {
    const r = await api.migrateMyConfig(patch);
    await cacheProfile(r.profile);
    return r.written;
  } catch {
    // A failed migration is not a failed login. The values stay in the cache
    // and the next sign-in offers them again - the daemon's absent-keys-only
    // rule makes retrying free.
    return [];
  }
}
