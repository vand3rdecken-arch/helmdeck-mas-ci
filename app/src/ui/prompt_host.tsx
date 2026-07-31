import React from "react";
import { Modal, Platform, Pressable, Text, TextInput, View } from "react-native";

import { useTheme } from "@/theme";

// A promise-based single-field prompt that works on every platform, including
// Android (which has no native Alert.prompt). The <PromptHost/> is mounted once
// at the app root; promptText() drives it through this module-level controller.
type PromptReq = { title: string; def: string; resolve: (v: string | null) => void };
let controller: ((req: PromptReq) => void) | null = null;

/** Returns true when a modal-based prompt host is mounted and usable. */
export function hasPromptHost() {
  return controller !== null;
}

/** Open the modal prompt. Only valid when hasPromptHost() is true. */
export function openPrompt(title: string, def = ""): Promise<string | null> {
  return new Promise((resolve) => {
    if (!controller) return resolve(null);
    controller({ title, def, resolve });
  });
}

export function PromptHost() {
  const t = useTheme();
  const [req, setReq] = React.useState<PromptReq | null>(null);
  const [val, setVal] = React.useState("");

  React.useEffect(() => {
    controller = (r) => { setReq(r); setVal(r.def); };
    return () => { controller = null; };
  }, []);

  const close = (result: string | null) => {
    req?.resolve(result);
    setReq(null);
  };

  if (!req) return null;
  return (
    <Modal transparent animationType="fade" visible onRequestClose={() => close(null)}>
      <Pressable
        onPress={() => close(null)}
        style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.6)", justifyContent: "center", padding: 24 }}
      >
        <Pressable
          onPress={(e) => e.stopPropagation()}
          style={{ backgroundColor: t.surface1, borderColor: t.borderSubtle, borderWidth: 1,
            borderRadius: 16, padding: 18, gap: 12 }}
        >
          <Text style={{ color: t.txtPrimary, fontSize: 15, fontWeight: "600" }}>{req.title}</Text>
          <TextInput
            value={val}
            onChangeText={setVal}
            autoFocus
            onSubmitEditing={() => close(val)}
            style={{ color: t.txtPrimary, backgroundColor: t.surface2, borderColor: t.borderSubtle,
              borderWidth: 1, borderRadius: 8, padding: 10, fontSize: 14 }}
          />
          <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 8 }}>
            <Pressable onPress={() => close(null)} style={{ paddingVertical: 8, paddingHorizontal: 14 }}>
              <Text style={{ color: t.txtSecondary, fontWeight: "500" }}>Abbrechen</Text>
            </Pressable>
            <Pressable
              onPress={() => close(val)}
              style={{ paddingVertical: 8, paddingHorizontal: 14, borderRadius: 8, backgroundColor: t.accent }}
            >
              <Text style={{ color: "#fff", fontWeight: "600" }}>OK</Text>
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

export const promptHostIsNative = Platform.OS !== "web";
