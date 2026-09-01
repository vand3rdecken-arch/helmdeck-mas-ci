import { useEffect } from "react";
import { ActivityIndicator, View } from "react-native";
import { useRouter } from "expo-router";
import { useTheme } from "@/theme";

// accounts-boards-prd phase 4 / settings-ia-redesign phase 3: this screen's
// content moved into the settings hub's "Zellen" door (settings.tsx,
// door === "cells") as @/ui/cells_catalog.tsx - the cell catalog, the six
// seeded laws, the engines/surfaces lists and the reconfiguration journal all
// render there now. Door 3 used to LINK here, which left "Zellen" as a door
// that was not a door; the hub now owns it and this file stays as a thin
// redirect so every existing /modules reference (nav rows, chat links,
// bookmarks) keeps working without a second surface behind it.
//
// Same shape as automation.tsx, deliberately: a deep link must land where the
// setting actually lives, and neither route may become a second edit surface.
export default function ModulesRedirect() {
  const router = useRouter();
  const t = useTheme();
  useEffect(() => { router.replace("/settings?door=cells" as never); }, [router]);
  return (
    <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: t.canvas }}>
      <ActivityIndicator color={t.accent} />
    </View>
  );
}
