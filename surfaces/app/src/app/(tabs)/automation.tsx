import { useEffect } from "react";
import { ActivityIndicator, View } from "react-native";
import { useRouter } from "expo-router";
import { useTheme } from "@/theme";

// settings-ia-redesign (ops/docs/backlog/settings-ia-redesign): this screen's
// content moved into the settings hub's "Agenten & Autonomie" door
// (settings.tsx, door === "automation") - schema-driven policy knobs,
// nightshift (now the ONLY edit surface, deduped), PMControls, and the
// harness editor all live there now. This file stays as a thin redirect so
// every existing /automation reference (nav rows, more.tsx, chat links,
// bookmarks) keeps working without a second edit surface behind it.
export default function AutomationRedirect() {
  const router = useRouter();
  const t = useTheme();
  useEffect(() => { router.replace("/settings?door=automation" as never); }, [router]);
  return (
    <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: t.canvas }}>
      <ActivityIndicator color={t.accent} />
    </View>
  );
}
