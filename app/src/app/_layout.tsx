import "react-native-gesture-handler";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { QueryClientProvider } from "@tanstack/react-query";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";

import * as Notifications from "expo-notifications";
import { useRouter } from "expo-router";
import { useEffect } from "react";
import { Platform } from "react-native";
import { queryClient } from "@/data/query";
import { api } from "@/data/client";
import { useConfig } from "@/data/config";
import { decryptPush, presentDecrypted, registerForPush } from "@/data/push";
import { ThemeProvider } from "@/theme";
import { tokens } from "@/theme/tokens";
import { CommandPalette, usePalette } from "@/ui/palette";
import { PromptHost } from "@/ui/prompt_host";
import { WebStyles } from "@/ui/webstyles";

// Global live updates: LONG-POLL the daemon's data version (api.boardWait). It
// blocks until the board changes, then we invalidate the active queries so
// every screen updates near-instantly. Works over BOTH the sealed relay and
// direct (unlike SSE, which can't tunnel the relay) — the per-screen
// refetchInterval is now just a slow safety fallback.
function useGlobalStream() {
  useEffect(() => {
    let alive = true;
    let v = 0;
    (async () => {
      while (alive) {
        try {
          const r = await api.boardWait(v);
          if (!alive) break;
          if (typeof r?.v === "number") {
            if (r.v !== v) queryClient.invalidateQueries();
            v = r.v;
          }
        } catch {
          if (!alive) break;
          await new Promise((res) => setTimeout(res, 3000));   // backoff, retry
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

function usePushWiring() {
  const router = useRouter();
  useEffect(() => {
    (async () => {
      await useConfig.getState().hydrate();
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
      else router.push("/chat");                        // PM message w/o a card -> conversation
    });
    return () => { recv.remove(); resp.remove(); };
  }, [router]);
}

export default function RootLayout() {
  usePushWiring();
  usePaletteHotkeys();
  useGlobalStream();
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider name="dark">
          <SafeAreaProvider>
            <StatusBar style="light" />
            <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: tokens.dark.canvas } }}>
              <Stack.Screen name="(tabs)" />
              <Stack.Screen name="card/[id]" />
              <Stack.Screen name="chat" options={{ presentation: "modal" }} />
              <Stack.Screen name="new" options={{ presentation: "modal" }} />
            </Stack>
            <WebStyles />
            <CommandPalette />
            <PromptHost />
          </SafeAreaProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </GestureHandlerRootView>
  );
}
