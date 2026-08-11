// The worker's background tasks, as a clickable list (Paseo parity: each
// subagent/background job is a first-class descriptor with its own status and
// output, not just a count). Tap a row to see the command that launched it and
// how it ended - so "wartet auf N Hintergrund-Task" becomes inspectable instead
// of an opaque number that used to grow forever.
import { useState } from "react";
import { Pressable, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import type { BgTask } from "@/data/types";
import { useT } from "@/i18n";
import { useTheme } from "@/theme";
import type { ThemeTokens } from "@/theme/tokens";

function ago(sinceSec: number | undefined, now: number): string {
  if (!sinceSec) return "";
  const s = Math.max(0, Math.round(now / 1000 - sinceSec));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  return `${Math.round(s / 3600)}h`;
}

const ICON: Record<BgTask["status"], keyof typeof Ionicons.glyphMap> = {
  running: "hourglass-outline",
  completed: "checkmark-circle",
  failed: "alert-circle",
  canceled: "remove-circle-outline",
};

function color(status: BgTask["status"], t: ThemeTokens): string {
  if (status === "completed") return t.ok;
  if (status === "failed") return t.danger;
  if (status === "canceled") return t.txtTertiary;
  return t.ai;   // running
}

function Row({ task, t, tr, now }: {
  task: BgTask; t: ThemeTokens; tr: (k: string, p?: Record<string, string | number>) => string; now: number;
}) {
  const [open, setOpen] = useState(false);
  const col = color(task.status, t);
  const body = (task.result || task.detail || "").trim();
  return (
    <Pressable onPress={() => body ? setOpen(!open) : undefined}
      accessibilityRole="button"
      style={{ backgroundColor: t.surface2, borderColor: t.borderSubtle, borderWidth: 1,
        borderRadius: 9, paddingHorizontal: 10, paddingVertical: 8 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Ionicons name={ICON[task.status]} size={15} color={col} />
        <Text numberOfLines={1} style={{ flex: 1, color: t.txtPrimary, fontSize: 12.5,
          fontWeight: task.status === "running" ? "600" : "500" }}>
          {task.title}
        </Text>
        <Text style={{ color: col, fontSize: 10.5, fontWeight: "600" }}>
          {tr(`card.bg.status.${task.status}`)}
        </Text>
        <Text style={{ color: t.txtTertiary, fontSize: 10.5 }}>
          {ago(task.updated || task.since, now)}
        </Text>
        {body ? (
          <Ionicons name={open ? "chevron-up" : "chevron-down"} size={13} color={t.txtTertiary} />
        ) : null}
      </View>
      {open && body ? (
        <View style={{ marginTop: 7, gap: 5 }}>
          {task.detail ? (
            <Text style={{ color: t.txtSecondary, fontSize: 11, fontFamily: "monospace", lineHeight: 15 }}>
              {task.detail}
            </Text>
          ) : null}
          {task.result ? (
            <Text style={{ color: t.txtTertiary, fontSize: 11, lineHeight: 15 }}>
              {task.result}
            </Text>
          ) : null}
        </View>
      ) : null}
    </Pressable>
  );
}

export function BackgroundTasks({ tasks }: { tasks: Record<string, BgTask> }) {
  const t = useTheme();
  const tr = useT();
  const now = Date.now();
  const list = Object.values(tasks || {});
  if (!list.length) return null;
  // running first, then most-recently-updated - the live work is what the owner
  // is watching for; finished tasks are history below it.
  const order = { running: 0, failed: 1, completed: 2, canceled: 3 };
  list.sort((a, b) => (order[a.status] - order[b.status])
    || (b.updated || b.since || 0) - (a.updated || a.since || 0));
  const running = list.filter((x) => x.status === "running").length;
  return (
    <View style={{ paddingHorizontal: 12, paddingTop: 8, gap: 6 }}>
      <Text style={{ color: t.txtTertiary, fontSize: 11, fontWeight: "600", letterSpacing: 0.3 }}>
        {running > 0 ? tr("card.bg.headerLive", { n: running }) : tr("card.bg.header")}
      </Text>
      {list.map((task, i) => (
        <Row key={i} task={task} t={t} tr={tr} now={now} />
      ))}
    </View>
  );
}
