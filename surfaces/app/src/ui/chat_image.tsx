import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import React, { useEffect, useState } from "react";
import { ActivityIndicator, Image, Modal, Platform, Pressable, Text, View } from "react-native";

import { api } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

/**
 * AN IMAGE IN THE CHAT (owner 2026-10-18: "chat kann keine Bilder, screenshot etc zeigen").
 *
 * The shape every chat settled on (Paseo, Open WebUI, Slack, ChatGPT): a fixed-size thumbnail with a
 * placeholder while it loads, tap -> full size over a dimmed screen, closed by tapping outside, the close
 * button, Escape or the back gesture.
 *
 * The bytes come as JSON {mime, data} (spine/agent/images.py), not as a plain <img src>: the phone reaches
 * the daemon only through the E2EE relay, and an authenticated JSON request is the one transport that works
 * on desktop, web and phone alike. Image names are content hashes, so a fetched image never changes -
 * cached for the session (staleTime Infinity) and fetched only when its row is drawn.
 */
const THUMB_W = 280;
const THUMB_H = 200;

export function ChatImage({ url, alt }: { url: string; alt?: string }) {
  const t = useTheme();
  const tr = useT();
  const [open, setOpen] = useState(false);
  const [ratio, setRatio] = useState<number | null>(null);
  const { data, isError, isLoading } = useQuery({
    queryKey: ["chat-image", url],
    queryFn: () => api.get<{ mime: string; data: string }>(url),
    staleTime: Infinity,
    gcTime: 30 * 60 * 1000,
    retry: 1,
  });
  const src = data?.data ? `data:${data.mime};base64,${data.data}` : null;

  useEffect(() => {
    if (!src) return;
    Image.getSize(src, (w, h) => { if (w > 0 && h > 0) setRatio(w / h); }, () => setRatio(null));
  }, [src]);

  // Escape closes the full view on the web/desktop (the back gesture does it on the phone via onRequestClose)
  useEffect(() => {
    if (!open || Platform.OS !== "web") return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // thumbnail box keeps the image's own aspect ratio inside THUMB_W x THUMB_H
  const w = ratio ? Math.min(THUMB_W, THUMB_H * ratio) : THUMB_W;
  const h = ratio ? Math.min(THUMB_H, THUMB_W / ratio) : 140;
  return (
    <>
      <Pressable onPress={() => src && setOpen(true)} accessibilityRole="imagebutton" testID="chat-image"
        accessibilityLabel={alt || tr("chat.image")}
        style={{ width: w, height: h, borderRadius: 10, overflow: "hidden", borderWidth: 1, borderColor: t.borderSubtle,
          backgroundColor: t.surface1, alignItems: "center", justifyContent: "center" }}>
        {src ? <Image source={{ uri: src }} style={{ width: "100%", height: "100%" }} resizeMode="cover" accessibilityIgnoresInvertColors />
          : isError ? (
            <View style={{ alignItems: "center", gap: 4 }}>
              <Ionicons name="image-outline" size={20} color={t.txtTertiary} />
              <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{tr("chat.imageUnavailable")}</Text>
            </View>)
          : isLoading ? <ActivityIndicator color={t.txtTertiary} /> : null}
      </Pressable>
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable onPress={() => setOpen(false)} accessibilityLabel={tr("chat.close")}
          style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.88)", alignItems: "center", justifyContent: "center", padding: 24 }}>
          {src ? <Image source={{ uri: src }} style={{ width: "100%", height: "100%" }} resizeMode="contain" testID="chat-image-full" /> : null}
          <Pressable onPress={() => setOpen(false)} hitSlop={12} accessibilityRole="button" accessibilityLabel={tr("chat.close")}
            style={{ position: "absolute", top: 18, right: 18, backgroundColor: "rgba(255,255,255,0.12)", borderRadius: 18, padding: 8 }}>
            <Ionicons name="close" size={20} color="#fff" />
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}
