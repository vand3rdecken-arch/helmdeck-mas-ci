import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "@/data/client";
import type { PeerLink, RoomMessage } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { TStep } from "@/ui/card_transcript";
import { ChatSurface } from "@/ui/chat_surface";
import { Empty, ScreenHeader } from "@/ui/kit";
import { useResponsive } from "@/ui/responsive";

// No timer: while the screen is open ONE request hangs on the other instance's
// room_wait (woken there by its chat cursor the moment a message lands) and is
// re-armed after each answer. After an error it waits this long, then re-arms.
const RETRY_MS = 5000;

// A room of ANOTHER HelmDeck instance, reached through a connection
// (spine/comms/peers.py -> its MCP door). Drawn with the same ChatSurface as
// our own rooms - one chat UI. What I write appears THERE under the name the
// connection gave me ("<label> (KI fuer <issuer>)"), so that name is "me" here.
export default function PeerRoomScreen() {
  const t = useTheme();
  const tr = useT();
  const router = useRouter();
  const qc = useQueryClient();
  const insets = useSafeAreaInsets();
  const { wide } = useResponsive();
  const { peer, room, name } = useLocalSearchParams<{ peer: string; room: string; name?: string }>();
  const pid = String(peer ?? ""), rid = String(room ?? "");
  const { data: peersData } = useQuery({ queryKey: ["peers"], queryFn: api.peers });
  const conn: PeerLink | undefined = (peersData?.peers ?? []).find((p) => p.id === pid);
  const entry = conn?.info.scope?.find((s) => s.kind === "room" && s.id === rid);
  const meAs = conn?.info.as ?? "";
  const { data, isLoading, error } = useQuery({
    queryKey: ["peerRoom", pid, rid], queryFn: () => api.peerRoom(pid, rid),
    enabled: !!pid && !!rid, retry: false,
  });
  const lastSeq = data?.messages?.length ? data.messages[data.messages.length - 1].seq : 0;
  const [arm, setArm] = useState(0);
  useEffect(() => {
    if (!pid || !rid || !data) return;
    const ctl = new AbortController();
    let alive = true;
    let to: ReturnType<typeof setTimeout> | undefined;
    (async () => {
      try {
        const r = await api.peerRoomWait(pid, rid, lastSeq, ctl.signal);
        if (!alive) return;
        if (r.messages?.length) {
          // fold the new messages in; the changed lastSeq re-arms this effect
          qc.setQueryData(["peerRoom", pid, rid], (old: typeof data) => {
            const have = new Set((old?.messages ?? []).map((m) => m.seq));
            return { room: rid, messages: [...(old?.messages ?? []), ...r.messages.filter((m) => !have.has(m.seq))] };
          });
        } else {
          setArm((n) => n + 1);   // nothing new within the hold: re-arm
        }
      } catch {
        if (alive) to = setTimeout(() => setArm((n) => n + 1), RETRY_MS);
      }
    })();
    return () => { alive = false; ctl.abort(); if (to) clearTimeout(to); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pid, rid, lastSeq, arm, !!data]);
  const messages: RoomMessage[] = Array.isArray(data?.messages) ? data!.messages : [];
  const [err, setErr] = useState("");
  const post = useMutation({
    mutationFn: (text: string) => api.peerRoomPost(pid, rid, text),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["peerRoom", pid, rid] }),
    onError: (e: Error) => setErr(e.message),
  });

  const steps: TStep[] = messages.map((x): TStep => {
    if (x.byKind === "henry") {
      return { role: "assistant", kind: "text", text: x.text, ts: x.ts, seq: x.seq, by: "Henry", byKind: "henry" };
    }
    if (x.byKind === "agent") {
      return { role: "user", kind: "text", text: x.text, ts: x.ts, seq: x.seq, by: x.by, byKind: "agent", onBehalf: x.on_behalf };
    }
    if (x.byKind === "system") return { role: "assistant", kind: "note", text: x.by + " " + x.text, ts: x.ts, seq: x.seq };
    return { role: "user", kind: "text", text: x.text, ts: x.ts, seq: x.seq, by: x.by, byKind: "human" };
  });

  const title = String(name ?? entry?.name ?? "");
  return (
    <View style={{ flex: 1, backgroundColor: t.canvas, paddingTop: wide ? 0 : insets.top }}>
      <ScreenHeader title={title} onBack={() => router.back()} />
      <Text numberOfLines={1} style={{ color: t.txtTertiary, fontSize: 12, paddingHorizontal: 16, paddingBottom: 8 }}>
        {[conn ? tr("peers.roomFrom", { name: conn.label }) : "", meAs ? tr("peers.youAre", { as: meAs, who: conn?.info.for ?? "?" }) : ""]
          .filter(Boolean).join(" · ")}
      </Text>
      {error && !messages.length ? (
        <View style={{ padding: 20 }}><Empty text={tr("peers.unreachable", { msg: (error as Error).message })} /></View>
      ) : (
        <ChatSurface steps={steps} me={meAs} loading={isLoading} empty={<Empty text={tr("rooms.noMessages")} />}
          onSend={(txt) => {
            if (!entry?.write) { setErr(tr("peers.readOnly")); return; }
            const v = txt.trim();
            if (v) { setErr(""); post.mutate(v); }
          }}
          placeholder={entry?.write ? tr("rooms.placeholder") : tr("peers.readOnly")} draftKey={"peer:" + pid + ":" + rid}
          error={err} minimal />
      )}
    </View>
  );
}
