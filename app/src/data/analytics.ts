import AsyncStorage from "@react-native-async-storage/async-storage";
import PostHog from "posthog-react-native";
import { create } from "zustand";

// Product analytics (PostHog, EU cloud). ONE owner for the whole app: every
// event goes through track() below, so the opt-IN toggle and the no-PII rule
// hold everywhere by construction. Events carry ONLY coarse action names and
// enum-ish props (a lane, a mode) - never card ids, titles, chat text, tokens
// or user names.
//
// OPT-IN, not opt-out (fixed 2026-08-23, GXP-S11 / A3): the privacy policy
// (relay/relay.py) says HelmDeck ships no analytics/tracking SDK, and this
// shipped enabled by default regardless - a real gap between the promise and
// the code, not a hypothetical one. Nothing fires until the user turns it on
// in More -> Datenschutz.
//
// The key is PostHog's *project token*: write-only, made to ship inside public
// client bundles (it cannot read data), so it lives in source like any other
// client constant. EXPO_PUBLIC_* env vars override it for another project.
const POSTHOG_KEY =
  process.env.EXPO_PUBLIC_POSTHOG_API_KEY ?? "phc_oda4H49MaYwqP2f64F8XkGuyxbsxACEeBYcb9JWhQ25D";
const POSTHOG_HOST = process.env.EXPO_PUBLIC_POSTHOG_HOST ?? "https://eu.i.posthog.com";

const PREF_KEY = "helmdeck.analytics";   // AsyncStorage: "1" = on, "0" = opted out

// Lazy singleton: constructed on first use so an opted-out session never even
// builds the client. posthog-react-native is JS-only here (persistence via
// AsyncStorage, device info via the already-installed expo modules) - OTA-safe.
let client: PostHog | null = null;
function posthog(): PostHog {
  if (!client) {
    client = new PostHog(POSTHOG_KEY, {
      host: POSTHOG_HOST,
      // Lifecycle autocapture needs native wiring we don't ship; app_open is
      // tracked explicitly in the root layout instead.
      captureAppLifecycleEvents: false,
      // The SDK's OWN opt-in switch, not just the `enabled` gate in track()
      // below. Before this, a freshly constructed client defaulted to opted
      // IN, so anything the SDK does at construction time (session start,
      // feature-flag fetch) could run before hydrate()'s async optOut() ever
      // reached it. A client is inert from the instant it exists now;
      // hydrate()/setEnabled() call optIn() explicitly when the user has
      // actually turned analytics on.
      defaultOptIn: false,
    });
  }
  return client;
}

interface AnalyticsState {
  enabled: boolean;
  hydrated: boolean;
  hydrate: () => Promise<void>;
  setEnabled: (v: boolean) => void;
}

// Opt-IN model (anonymous events, no profiles): OFF until the user turns it on
// in More -> Datenschutz. The choice persists per device. Defaulting to false
// here (not just relying on the async hydrate() below) means an install that
// somehow never reaches hydrate() stays silent, not silently tracking.
export const useAnalytics = create<AnalyticsState>((set, get) => ({
  enabled: false,
  hydrated: false,
  hydrate: async () => {
    try {
      const raw = await AsyncStorage.getItem(PREF_KEY);
      if (raw !== null) set({ enabled: raw === "1" });
    } catch { /* unavailable -> keep default (off) */ }
    set({ hydrated: true });
    if (get().enabled) posthog().optIn();
  },
  setEnabled: (v) => {
    set({ enabled: v });
    AsyncStorage.setItem(PREF_KEY, v ? "1" : "0").catch(() => { /* best effort */ });
    if (v) posthog().optIn();
    else posthog().optOut();
  },
}));

/** Fire-and-forget product event. Safe to call from anywhere (transport,
 *  stores, screens); silently a no-op when the owner opted out. */
export function track(event: string, props?: Record<string, string | number | boolean>) {
  try {
    if (!useAnalytics.getState().enabled) return;
    posthog().capture(event, props);
  } catch { /* analytics must never break the app */ }
}
