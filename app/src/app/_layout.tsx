import "react-native-gesture-handler";
import { Stack } from "expo-router";
import type { ErrorBoundaryProps } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { QueryClientProvider } from "@tanstack/react-query";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";

import * as Notifications from "expo-notifications";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { AppState, Platform, Pressable, Text, View } from "react-native";
import { queryClient, restoreCache, startCachePersist } from "@/data/query";
import { track, useAnalytics } from "@/data/analytics";
import { api } from "@/data/client";
import { useConfig } from "@/data/config";
import { useDemo } from "@/data/demo";
import { useSilentOta } from "@/data/ota";
import { usePresenceHeartbeat } from "@/data/presence";
import { decryptPush, presentDecrypted, registerForPush } from "@/data/push";
import { t as i18nT } from "@/i18n/core";
import { ThemeProvider } from "@/theme";
import { tokens } from "@/theme/tokens";
import { HealthBanner } from "@/ui/health_banner";
import { DemoBanner } from "@/ui/demo_banner";
import { Onboard, useShowOnboard } from "@/ui/onboard";
import { CommandPalette, usePalette } from "@/ui/palette";
import { PromptHost } from "@/ui/prompt_host";
import { WebStyles } from "@/ui/webstyles";

// Global live updates: LONG-POLL the daemon's data version (api.boardWait). It
// blocks until the board changes, then we invalidate the active queries so
// every screen updates near-instantly. Works over BOTH the sealed relay and
// direct (unlike SSE, which can't tunnel the relay) — the per-screen
// refetchInterval is now just a slow safety fallback.
// Reconnect with EXPONENTIAL backoff (3s→30s, reset on success): a dead relay
// isn't hammered, a blip recovers in one short pause. Failures land in the
// health store via client.ts, so the HealthBanner shows them — never silent.
function useGlobalStream() {
  useEffect(() => {
    let alive = true;
    let v = 0;
    let delay = 3000;
    (async () => {
      while (alive) {
        try {
          const r = await api.boardWait(v);
          if (!alive) break;
          delay = 3000;
          if (typeof r?.v === "number") {
            if (r.v !== v) queryClient.invalidateQueries();
            v = r.v;
          }
        } catch {
          if (!alive) break;
          await new Promise((res) => setTimeout(res, delay));
          delay = Math.min(delay * 2, 30000);
        }
      }
    })();
    return () => { alive = false; };
  }, []);
}

// Desktop/web power-nav: Cmd/Ctrl-K toggles the command palette, Esc closes it.
// No-op on native (no DOM); on native the palette is opened via the tab bar / a button.
function usePaletteHotkeys() {
  useEffect(() => {
    if (Platform.OS !== "web" || typeof document === "undefined") return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        usePalette.getState().toggle();
      } else if (e.key === "Escape") {
        usePalette.getState().hide();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
}

// Product analytics: hydrate the persisted opt-out FIRST, then log the launch -
// so an opted-out device never sends even the app_open.
function useAnalyticsBoot() {
  useEffect(() => {
    (async () => {
      await useAnalytics.getState().hydrate();
      track("app_open", { platform: Platform.OS });
    })();
  }, []);
}

function usePushWiring() {
  const router = useRouter();
  useEffect(() => {
    (async () => {
      await useConfig.getState().hydrate();
      await useDemo.getState().hydrate();   // demo survives a restart, like pairing
      // hydrate() flips `active` AFTER the first queries may have fetched real
      // (empty/401) data - refetch so a returning demo session actually shows the
      // sample board instead of the stale pre-hydrate payload.
      if (useDemo.getState().active) queryClient.invalidateQueries();
      if (useConfig.getState().relayMode()) registerForPush();
    })();
    // foreground: decrypt sealed data pushes and present them locally
    const recv = Notifications.addNotificationReceivedListener((n) => {
      const data = n.request.content.data as Record<string, string>;
      if (data?.cipher) presentDecrypted(data);
    });
    // tap: deep-link to the card (or the PM chat if the push has no card). The
    // track is sealed in the cipher (zero-knowledge), so decrypt on tap to route.
    const resp = Notifications.addNotificationResponseReceivedListener((r) => {
      const data = r.notification.request.content.data as Record<string, string>;
      let track: string | undefined = data?.track;      // local notif already carries it
      if (!track && data?.cipher) track = decryptPush(data)?.track;   // system notif: decrypt
      if (track) router.push(`/card/${track}`);
      else router.push("/(tabs)/dashboard" as never);   // PM status w/o a card -> the PM summary/overview
    });
    return () => { recv.remove(); resp.remove(); };
  }, [router]);
}

// expo-router renders THIS instead of crashing to native when the tree throws
// during render. The classic case: an OTA JS bundle references a native module
// the installed APK doesn't ship (e.g. "Cannot find native module
// 'ExpoDocumentPicker'") - without a boundary that becomes a full app crash on
// every launch. We now bump runtimeVersion on native changes so old APKs reject
// incompatible JS, but this is the belt-and-suspenders: a clear "update the app"
// screen instead of a crash loop. No provider hooks here (this renders ABOVE the
// providers), so styling is static tokens only.
export function ErrorBoundary({ error, retry }: ErrorBoundaryProps) {
  const t = tokens.dark;
  const needsUpdate = /native module|requireNativeModule|Cannot find native/i.test(error?.message ?? "");
  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, alignItems: "center", justifyContent: "center", padding: 28, gap: 14 }}>
      <Text style={{ color: t.txtPrimary, fontSize: 20, fontWeight: "700", textAlign: "center" }}>
        {needsUpdate ? i18nT("err.updateNeeded") : i18nT("err.generic")}
      </Text>
      <Text style={{ color: t.txtSecondary, fontSize: 14, textAlign: "center", lineHeight: 20 }}>
        {needsUpdate
          ? i18nT("err.updateBody")
          : (error?.message ?? i18nT("err.unknown"))}
      </Text>
      <Pressable onPress={retry} style={{ marginTop: 6, backgroundColor: t.accent, paddingHorizontal: 20, paddingVertical: 11, borderRadius: 12 }}>
        <Text style={{ color: "#fff", fontWeight: "600" }}>{i18nT("err.retry")}</Text>
      </Pressable>
    </View>
  );
}

// Resume-refetch: when the app returns to the foreground, refetch everything so
// the board doesn't sit on a spinner waiting out the slow relay poll interval
// ("paired but takes very long"). We ONLY invalidate on "active" - deliberately
// NOT focusManager.setFocused(false) on background: pausing queries risks leaving
// them stuck loading if the balancing "active" event is ever missed (chat, already
// cached, still shows - the board would hang). invalidateQueries alone forces the
// refetch on return without any pause hazard.
function useResumeRefetch() {
  useEffect(() => {
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "active") queryClient.invalidateQueries();
    });
    return () => sub.remove();
  }, []);
}

// Hydrate the persisted board BEFORE the screens mount, so a cold start paints
// last-known data instead of an empty spinner (then queries revalidate in the
// background). Gated with a short timeout so a slow/blocked AsyncStorage read can
// never hang the launch - after 1s we render regardless and hydrate is a no-op.
function useCacheGate() {
  const [restored, setRestored] = useState(false);
  useEffect(() => {
    let done = false;
    const timer = setTimeout(() => { if (!done) setRestored(true); }, 1000);
    restoreCache().finally(() => { done = true; clearTimeout(timer); setRestored(true); });
    const stop = startCachePersist();
    return () => { clearTimeout(timer); stop(); };
  }, []);
  return restored;
}

export default function RootLayout() {
  useAnalyticsBoot();
  usePushWiring();
  usePaletteHotkeys();
  useGlobalStream();
  useResumeRefetch();
  useSilentOta();
  usePresenceHeartbeat();
  const restored = useCacheGate();
  // Desktop first run: the instance isn't serving yet, so onboarding owns the
  // window instead of dropping the user on a board that cannot load.
  const showOnboard = useShowOnboard();
  // Hold the tree one tick until the persisted board is hydrated, so screens
  // mount onto last-known data (instant paint) instead of an empty spinner.
  if (!restored) {
    return <View style={{ flex: 1, backgroundColor: tokens.dark.canvas }} />;
  }
  if (showOnboard) {
    return (
      <GestureHandlerRootView style={{ flex: 1 }}>
        <QueryClientProvider client={queryClient}>
          <ThemeProvider name="dark">
            <SafeAreaProvider>
              <StatusBar style="light" />
              <Onboard />
              <WebStyles />
            </SafeAreaProvider>
          </ThemeProvider>
        </QueryClientProvider>
      </GestureHandlerRootView>
    );
  }
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider name="dark">
          <SafeAreaProvider>
            <StatusBar style="light" />
            <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: tokens.dark.canvas } }}>
              <Stack.Screen name="(tabs)" />
              <Stack.Screen name="card/[id]" />
              <Stack.Screen name="chat" options={{ presentation: "transparentModal", animation: "fade" }} />
              <Stack.Screen name="new" options={{ presentation: "modal" }} />
            </Stack>
            <WebStyles />
            <HealthBanner />
            <DemoBanner />
            <CommandPalette />
            <PromptHost />
          </SafeAreaProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </GestureHandlerRootView>
  );
}
