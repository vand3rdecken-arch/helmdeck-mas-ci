import React, { createContext, useContext } from "react";
import { tokens, type ThemeName, type ThemeTokens } from "./tokens";

// Dark by default (the product is dark-first, app.json userInterfaceStyle:dark).
// A provider so we can add the light theme + the 5 backdrop variants later
// without touching call sites.
const ThemeContext = createContext<ThemeTokens>(tokens.dark);

export function ThemeProvider({ name = "dark", children }: { name?: ThemeName; children: React.ReactNode }) {
  return <ThemeContext.Provider value={tokens[name]}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeTokens {
  return useContext(ThemeContext);
}

// Lane / status / executor colours — 1:1 with web/lib/store.tsx + board.tsx,
// resolved against the active theme's tokens.
export function laneColor(t: ThemeTokens, lane?: string): string {
  return { backlog: t.txtTertiary, working: t.ai, review: t.human, done: t.ok }[lane ?? ""] ?? t.txtTertiary;
}
export function statusColor(t: ThemeTokens, status?: string): string {
  return ({
    queued: t.txtTertiary, running: t.ai, needs_you: t.warn, submitted: t.human,
    accepted: t.ok, bounced: t.danger, done: t.ok, failed: t.danger,
  } as Record<string, string>)[status ?? ""] ?? t.txtTertiary;
}
export function executor(mode?: string): "ai" | "human" | "both" {
  if (mode === "human" || mode === "teach") return "human";
  if (mode === "cowork") return "both";
  return "ai";
}
export function executorLabel(mode?: string): string {
  const e = executor(mode);
  return e === "human" ? "You" : e === "both" ? "AI + You" : "AI";
}
