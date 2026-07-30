import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { QueryClientProvider } from "@tanstack/react-query";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { queryClient } from "@/data/query";
import { ThemeProvider } from "@/theme";
import { tokens } from "@/theme/tokens";

export default function RootLayout() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider name="dark">
        <SafeAreaProvider>
          <StatusBar style="light" />
          <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: tokens.dark.canvas } }} />
        </SafeAreaProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
