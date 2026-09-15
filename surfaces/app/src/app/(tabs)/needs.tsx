import { Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { BoardList } from "@/ui/board";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

export default function NeedsTab() {
  const t = useTheme();
  const tr = useT();
  const insets = useSafeAreaInsets();
  return (
    <View style={{ flex: 1, backgroundColor: t.canvas }}>
      <Text style={{ color: t.txtPrimary, fontSize: 22, fontWeight: "700", paddingTop: insets.top + 10, paddingHorizontal: 16, paddingBottom: 6 }}>
        {tr("nav.needsYou")}
      </Text>
      <BoardList filter="needs_you" />
    </View>
  );
}
