import React, { createContext, useContext } from "react";
import {
  tokens, laneTokens, statusTokens, semanticFallback,
  type ThemeName, type ThemeTokens,
} from "./tokens";

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

// Lane / status colours. The MAPPINGS live in ops/tools/gen_tokens.py and are
// generated into tokens.ts, because the watch needs the same answers and a
// second hand-written copy in Kotlin is how "a running card is AI-blue" starts
// meaning two different things (owner, 2026-08-29: "Theme sollte auch
// zentralisiert sein"). These functions only RESOLVE a token name against the
// active theme, which is also what keeps a light theme possible.
export function laneColor(t: ThemeTokens, lane?: string): string {
  return t[laneTokens[lane ?? ""] ?? semanticFallback];
}
export function statusColor(t: ThemeTokens, status?: string): string {
  return t[statusTokens[status ?? ""] ?? semanticFallback];
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
