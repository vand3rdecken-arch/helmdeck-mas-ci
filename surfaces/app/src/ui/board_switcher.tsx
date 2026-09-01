import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { Pressable, Text } from "react-native";

import { useBoards } from "@/data/boards";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { useActionSheet } from "./action_sheet";

/** WHICH BOARD (accounts-boards-prd phase 2).
 *
 *  It shows even with a single board, because the sheet is also the only way
 *  to REACH the editor - hiding the control until a second board exists would
 *  leave no path to creating one. The editor is the last entry of the sheet
 *  rather than a second header button, so the header keeps one affordance.
 *
 *  Editing lives on /boards, not here: this is navigation, nothing else. It
 *  renders nothing at all when the daemon serves no boards (an older daemon,
 *  the demo fixture) - there is then nothing to switch to and nothing to
 *  edit, and the board falls back to the four stations as it always did. */
export function BoardSwitcher() {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const sheet = useActionSheet();
  const { boards, active, setBoardId } = useBoards();

  const manage = {
    label: tr("boards.manage"),
    onPress: () => router.push("/boards" as never),
  };
  // With no boards at all (an older daemon, or the demo fixture) the whole
  // control is absent - there is nothing to switch and nothing to edit.
  if (!boards.length) return null;

  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={tr("boards.switch")}
        onPress={() => sheet.show({
          title: tr("boards.switch"),
          options: [
            ...boards.map((b) => ({
              // The active board is marked in the list rather than removed from
              // it: a sheet that silently omits where you already are makes the
              // list a different length every time you open it.
              label: (b.id === active.id ? "✓  " : "     ") + b.name,
              onPress: () => setBoardId(b.id),
            })),
            manage,
          ],
        })}
        style={({ pressed }) => ({
          flexDirection: "row", alignItems: "center", gap: 5,
          borderRadius: 9, paddingHorizontal: 9, paddingVertical: 4,
          backgroundColor: pressed ? t.layer2 : t.layer1,
        })}>
        <Text numberOfLines={1} style={{ color: t.txtSecondary, fontSize: 13, fontWeight: "600", maxWidth: 180 }}>
          {active.name || tr("nav.board")}
        </Text>
        <Ionicons name="chevron-down" size={13} color={t.txtTertiary} />
      </Pressable>
      {sheet.node}
    </>
  );
}
