import "react-native-gesture-handler";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { QueryClientProvider } from "@tanstack/react-query";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { queryClient } from "@/data/query";
import { ThemeProvider } from "@/theme";
import { tokens } from "@/theme/tokens";

export default function RootLayout() {
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
          </SafeAreaProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </GestureHandlerRootView>
  );
}
