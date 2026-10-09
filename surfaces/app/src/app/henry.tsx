import { Ionicons } from "@expo/vector-icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import { chatFallbackInterval, useStreamCaps } from "@/data/stream";
import type { PrivateHenryEntry } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { TStep } from "@/ui/card_transcript";
import { ChatSurface } from "@/ui/chat_surface";
import { Empty, ScreenHeader } from "@/ui/kit";
import { useResponsive } from "@/ui/responsive";

const WAIT_MS = 3 * 60 * 1000;      // a message without an answer stops reading as "answering" after this

// A restricted role's PRIVATE Henry (cells/copilot/chat/private_henry.py): he
// knows this person's own and shared cards and the notes he kept about them -
// nothing else - and advises without acting. The conversation is the person's
// own; an admin reads it only if they allow it (Chat-Freigabe). Refreshes from
// the chat cursor (data/stream.ts), no timer of its own. Drawn by the shared
// ChatSurface - the same body as the board chat and the rooms.
export default function PrivateHenryScreen() {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const qc = useQueryClient();
  const insets = useSafeAreaInsets();
  const { wide } = useResponsive();
  const chatEvents = useStreamCaps((s) => s.chatEvents);
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  const { data, isLoading } = useQuery({
    queryKey: ["henry"], queryFn: api.henryHistory, refetchInterval: chatFallbackInterval(chatEvents), retry: false,
  });
  const entries: PrivateHenryEntry[] = Array.isArray(data?.entries) ? data!.entries : [];

  const [err, setErr] = useState("");
  const post = useMutation({
    mutationFn: (body: string) => api.henryPost(body),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["henry"] }); },
    onError: (e: Error) => setErr(tr("rooms.sendFailed", { msg: e.message })),
  });

  // Henry is "answering" while the last line is the person's own and still fresh
  const pending = useMemo(() => {
    const last = entries[entries.length - 1];
    if (!last || last.role !== "user") return false;
    const at = last.date && last.ts ? Date.parse(`${last.date}T${last.ts}:00`) : NaN;
    return Number.isNaN(at) ? true : Date.now() - at < WAIT_MS;
  }, [entries]);

  const steps: TStep[] = entries.map((x): TStep => x.role === "user"
    ? { role: "user", kind: "text", text: x.text, ts: x.ts, seq: x.seq, by: me?.name, byKind: "human" }
    : { role: "assistant", kind: x.error ? "error" : "text", text: x.text, ts: x.ts, seq: x.seq, by: "Henry", byKind: "henry" });
  if (pending) steps.push({ role: "assistant", kind: "text", text: tr("rooms.henryWorking"), streaming: true, by: "Henry", byKind: "henry" });

  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: wide ? 0 : insets.top }}>
      <ScreenHeader title={tr("henry.title")} onBack={() => router.back()} />
      <ChatSurface steps={steps} me={me?.name} loading={isLoading} minimal
        empty={(
          <View style={{ paddingTop: 24, alignItems: "center", gap: 10 }}>
            <Ionicons name="sparkles" size={30} color={t.ai} />
            <Empty text={tr("henry.empty")} />
          </View>
        )}
        onSend={(txt) => { const v = txt.trim(); if (v) { setErr(""); post.mutate(v); } }}
        placeholder={tr("henry.placeholder")} draftKey="private-henry" error={err} />
    </View>
  );
}
