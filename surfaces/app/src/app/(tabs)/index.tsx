import { useQuery } from "@tanstack/react-query";
import { Redirect } from "expo-router";
import { ActivityIndicator, View } from "react-native";

import { api } from "@/data/client";
import type { Me } from "@/data/types";
import { isRestricted } from "@/kernel";
import { useTheme } from "@/theme";
import { HenryHome } from "@/ui/henry_home";

// The default tab (Expo Router: index.tsx opens first) is HENRY, not a dashboard
// (owner decree 2026-10-05): one ask bar + one thread list, see ui/henry_home.tsx.
// The old owner StatusPanel / operator metric panels (ui/dash_panels.tsx) are no
// longer mounted here; the operator panels were already unreachable, since an
// operator is `isRestricted` and was redirected before they rendered.
export default function HenryTab() {
  const t = useTheme();
  // No timer: every writer moves the daemon's `v`, which reaches the phone as a
  // pushed event that invalidates every query (app/_layout.tsx useGlobalStream).
  const { data: me } = useQuery<Me>({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  // A guest (client) or operator has no Henry home: /chat/threads answers 403.
  // Their home is the team rooms.
  if (isRestricted(me)) return <Redirect href={"/rooms" as never} />;
  if (!me) return <View style={{ flex: 1, backgroundColor: t.canvas, justifyContent: "center" }}><ActivityIndicator color={t.accent} /></View>;
  return <HenryHome />;
}
