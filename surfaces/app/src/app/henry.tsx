import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { Keyboard, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { chatFallbackInterval, useStreamCaps } from "@/data/stream";
import type { PrivateHenryEntry } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import { Empty, ScreenHeader } from "@/ui/kit";
import { useResponsive } from "@/ui/responsive";

const WAIT_MS = 3 * 60 * 1000;      // a message without an answer stops reading as "answering" after this

// A restricted role's PRIVATE Henry (cells/copilot/chat/private_henry.py): he
// knows this person's own and shared cards and the notes he kept about them -
// nothing else - and advises without acting. The conversation is the person's
// own; an admin reads it only if they allow it (Chat-Freigabe). Refreshes from
// the chat cursor (data/stream.ts), no timer of its own.
export default function PrivateHenryScreen() {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const qc = useQueryClient();
  const insets = useSafeAreaInsets();
  const { wide } = useResponsive();
  const chatEvents = useStreamCaps((s) => s.chatEvents);
  const { data, isLoading } = useQuery({
    queryKey: ["henry"], queryFn: api.henryHistory, refetchInterval: chatFallbackInterval(chatEvents), retry: false,
  });
  const entries: PrivateHenryEntry[] = Array.isArray(data?.entries) ? data!.entries : [];

  const [kb, setKb] = useState(0);
  useEffect(() => {
    const show = Keyboard.addListener("keyboardDidShow", (e) => setKb(e.endCoordinates.height));
    const hide = Keyboard.addListener("keyboardDidHide", () => setKb(0));
    return () => { show.remove(); hide.remove(); };
  }, []);
  const scroller = useRef<ScrollView>(null);
  useEffect(() => { const h = setTimeout(() => scroller.current?.scrollToEnd({ animated: true }), 60); return () => clearTimeout(h); },
    [entries.length]);

  const [text, setText] = useState("");
  const [err, setErr] = useState("");
  const post = useMutation({
    mutationFn: (body: string) => api.henryPost(body),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["henry"] }); },
    onError: (e: Error, body) => { setText(body); setErr(tr("rooms.sendFailed", { msg: e.message })); },
  });
  const send = () => {
    const body = text.trim();
    if (!body || post.isPending) return;
    setErr(""); setText("");
    post.mutate(body);
  };

  // Henry is "answering" while the last line is the person's own and still fresh
  const pending = useMemo(() => {
    const last = entries[entries.length - 1];
    if (!last || last.role !== "user") return false;
    const at = last.date && last.ts ? Date.parse(`${last.date}T${last.ts}:00`) : NaN;
    return Number.isNaN(at) ? true : Date.now() - at < WAIT_MS;
  }, [entries]);

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: wide ? 0 : insets.top }}>
      <ScreenHeader title={tr("henry.title")} onBack={() => router.back()} />
      <ScrollView ref={scroller} style={{ flex: 1 }} keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ paddingHorizontal: 12, paddingBottom: 12, gap: 8,
          width: "100%", maxWidth: wide ? 760 : undefined, alignSelf: "center" }}>
        {entries.length === 0 && !isLoading ? (
          <View style={{ paddingTop: 24, alignItems: "center", gap: 10 }}>
            <Ionicons name="sparkles" size={30} color={t.ai} />
            <Empty text={tr("henry.empty")} />
          </View>
        ) : null}
        {entries.map((x, i) => {
          const mine = x.role === "user";
          return (
            <View key={x.seq ?? i} style={{ alignSelf: mine ? "flex-end" : "flex-start", maxWidth: "86%", gap: 3 }}>
              {!mine ? (
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingLeft: 4 }}>
                  <Ionicons name="sparkles" size={12} color={t.ai} />
                  <Text style={{ color: t.ai, fontSize: 12, fontWeight: "700" }}>{tr("rooms.henry")}</Text>
                  <Text style={{ color: t.txtTertiary, fontSize: 11 }}>{x.ts ?? ""}</Text>
                </View>
              ) : null}
              <View style={{ backgroundColor: mine ? t.accent : x.error ? t.warn + "30" : t.ai + "26", borderRadius: 16,
                borderTopRightRadius: mine ? 4 : 16, borderTopLeftRadius: mine ? 16 : 4, paddingHorizontal: 12, paddingVertical: 8 }}>
                <Text selectable style={{ color: mine ? "#fff" : t.txtPrimary, fontSize: 14.5, lineHeight: 20 }}>{x.text}</Text>
              </View>
            </View>
          );
        })}
        {pending ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingLeft: 4 }}>
            <Ionicons name="sparkles" size={12} color={t.ai} />
            <Text style={{ color: t.txtTertiary, fontSize: 12 }}>{tr("rooms.henryWorking")}</Text>
          </View>
        ) : null}
      </ScrollView>
      {err ? <Text style={{ color: t.danger, fontSize: 12, paddingHorizontal: 16, paddingBottom: 4 }}>{err}</Text> : null}
      <View style={{ flexDirection: "row", alignItems: "flex-end", gap: 8, paddingHorizontal: 12, paddingTop: 8,
        paddingBottom: kb > 0 ? insets.bottom + 10 : insets.bottom + 8, borderTopWidth: 1, borderTopColor: t.glassBorder,
        backgroundColor: t.surface1 }}>
        <TextInput value={text} onChangeText={setText} placeholder={tr("henry.placeholder")} multiline
          placeholderTextColor={t.txtPlaceholder}
          style={{ flex: 1, maxHeight: 120, color: t.txtPrimary, fontSize: 15, backgroundColor: t.surface2, borderRadius: 18,
            paddingHorizontal: 14, paddingTop: 9, paddingBottom: 9 }} />
        <Pressable onPress={send} disabled={!text.trim() || post.isPending} accessibilityLabel={tr("rooms.send")}
          style={{ width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center",
            backgroundColor: text.trim() ? t.accent : t.surface2 }}>
          <Ionicons name="send" size={17} color={text.trim() ? "#fff" : t.txtTertiary} />
        </Pressable>
      </View>
      {kb > 0 ? <View style={{ height: kb }} /> : null}
    </View>
  );
}
