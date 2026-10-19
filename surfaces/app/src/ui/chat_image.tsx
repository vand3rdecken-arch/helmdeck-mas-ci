import { Ionicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import React, { useEffect, useState } from "react";
import { ActivityIndicator, Image, Modal, Platform, Pressable, Text, View, useWindowDimensions } from "react-native";
import { Gesture, GestureDetector, GestureHandlerRootView } from "react-native-gesture-handler";
import Animated, { runOnJS, useAnimatedStyle, useSharedValue, withTiming } from "react-native-reanimated";

import { api } from "@/data/client";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";

/**
 * AN IMAGE IN THE CHAT (owner 2026-10-18: "chat kann keine Bilder, screenshot etc zeigen").
 *
 * The shape every chat settled on (Paseo, Open WebUI, Slack, ChatGPT): a fixed-size thumbnail with a
 * placeholder while it loads, tap -> full size over a dimmed screen, closed by tapping outside, the close
 * button, Escape or the back gesture. The full view zooms like a gallery (owner 2026-10-19: "kann nicht
 * reinzoomen, Screenshots zu klein"): pinch, double-tap 1x <-> 2.5x, pan while zoomed, edge to edge.
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
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)} statusBarTranslucent>
        {/* a Modal is its own root on Android - gestures need their own root view inside it */}
        <GestureHandlerRootView style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.92)" }}>
          {src ? <ZoomableImage src={src} onClose={() => setOpen(false)} /> : null}
          <Pressable onPress={() => setOpen(false)} hitSlop={12} accessibilityRole="button" accessibilityLabel={tr("chat.close")}
            style={{ position: "absolute", top: 36, right: 18, backgroundColor: "rgba(255,255,255,0.12)", borderRadius: 18, padding: 8 }}>
            <Ionicons name="close" size={20} color="#fff" />
          </Pressable>
        </GestureHandlerRootView>
      </Modal>
    </>
  );
}

const MAX_ZOOM = 6;
const TAP_ZOOM = 2.5;

/** Full-screen image: pinch to zoom, double-tap toggles zoom, pan while zoomed, single tap at 1x closes. */
function ZoomableImage({ src, onClose }: { src: string; onClose: () => void }) {
  const { width: W, height: H } = useWindowDimensions();
  const scale = useSharedValue(1), savedScale = useSharedValue(1);
  const tx = useSharedValue(0), ty = useSharedValue(0), savedX = useSharedValue(0), savedY = useSharedValue(0);

  // keep the zoomed image covering the screen - never pan it out of view
  const clamp = (v: number, s: number, size: number) => {
    "worklet";
    const max = (size * (s - 1)) / 2;
    return Math.min(max, Math.max(-max, v));
  };
  const reset = () => {
    "worklet";
    scale.value = withTiming(1); savedScale.value = 1;
    tx.value = withTiming(0); ty.value = withTiming(0); savedX.value = 0; savedY.value = 0;
  };

  const pinch = Gesture.Pinch()
    .onUpdate((e) => { scale.value = Math.min(MAX_ZOOM, Math.max(0.8, savedScale.value * e.scale)); })
    .onEnd(() => {
      if (scale.value <= 1) { reset(); return; }
      savedScale.value = scale.value;
      tx.value = withTiming(clamp(tx.value, scale.value, W)); ty.value = withTiming(clamp(ty.value, scale.value, H));
      savedX.value = clamp(tx.value, scale.value, W); savedY.value = clamp(ty.value, scale.value, H);
    });
  const pan = Gesture.Pan().averageTouches(true)
    .onUpdate((e) => {
      if (savedScale.value <= 1) return;
      tx.value = clamp(savedX.value + e.translationX, scale.value, W);
      ty.value = clamp(savedY.value + e.translationY, scale.value, H);
    })
    .onEnd(() => { savedX.value = tx.value; savedY.value = ty.value; });
  const doubleTap = Gesture.Tap().numberOfTaps(2)
    .onEnd((e) => {
      if (savedScale.value > 1) { reset(); return; }
      // zoom in towards the tapped point
      const x = clamp((W / 2 - e.x) * (TAP_ZOOM - 1), TAP_ZOOM, W), y = clamp((H / 2 - e.y) * (TAP_ZOOM - 1), TAP_ZOOM, H);
      scale.value = withTiming(TAP_ZOOM); savedScale.value = TAP_ZOOM;
      tx.value = withTiming(x); ty.value = withTiming(y); savedX.value = x; savedY.value = y;
    });
  const singleTap = Gesture.Tap().requireExternalGestureToFail(doubleTap)
    .onEnd(() => { if (savedScale.value <= 1) runOnJS(onClose)(); });

  const style = useAnimatedStyle(() => ({
    transform: [{ translateX: tx.value }, { translateY: ty.value }, { scale: scale.value }],
  }));
  return (
    <GestureDetector gesture={Gesture.Simultaneous(pinch, pan, Gesture.Exclusive(doubleTap, singleTap))}>
      <Animated.View style={[{ width: W, height: H }, style]}>
        <Image source={{ uri: src }} style={{ width: W, height: H }} resizeMode="contain" testID="chat-image-full" />
      </Animated.View>
    </GestureDetector>
  );
}
