import { useQuery } from "@tanstack/react-query";

import { api } from "@/data/client";
import type { Me } from "@/data/types";

/** True when this workspace's AI runs on the flat Claude Max subscription:
 *  a turn burns quota, not cash, so every cost surface must show consumption
 *  (tokens) instead of a $-amount - the measured dollar figure is only the
 *  API-equivalent reference. Rides /me's public ui slice because every role
 *  renders cost chips (the full settings blob stays owner-only). */
export function useAiFlat(): boolean {
  const { data } = useQuery<Me>({ queryKey: ["me"], queryFn: api.me, staleTime: 60000 });
  return data?.ui?.ai_billing === "flat";
}

/** Compact token count for chips/tiles: 950 · 12.4k · 3.1M. */
export function fmtTok(n: number): string {
  const f = (v: number) => v.toFixed(1).replace(/\.0$/, "");
  if (n >= 1e6) return f(n / 1e6) + "M";
  if (n >= 1e3) return f(n / 1e3) + "k";
  return String(Math.round(n));
}

/** Share of the subscription: the flat plan's real cost unit. Calibrated from
 *  the live quota window (daemon: events.plan_calibration), so it is an
 *  estimate and always carries the "~". Sub-0.01% work still reads "<0.01 %"
 *  rather than a bare 0 - it consumed something, just not much. */
export function fmtPlanPct(pct: number): string {
  if (!(pct > 0)) return "~0 %";
  if (pct < 0.01) return "~<0.01 %";           // consumed something, just not much
  return "~" + (pct >= 10 ? pct.toFixed(0) : pct.toFixed(2).replace(/\.?0+$/, "")) + " %";
}

type Tr = (key: string, vars?: Record<string, string | number>) => string;

/** The flat plan's cost chip: share of the subscription when the daemon could
 *  calibrate it, else the raw token count. Tokens are the FALLBACK, not the
 *  answer - "% of plan" is what the owner can act on. */
export function planLabel(tr: Tr, pct: number | null | undefined, tokens: number): string {
  return pct != null && pct > 0
    ? tr("board.aiPlan", { pct: fmtPlanPct(pct) })
    : tr("board.aiTok", { tok: fmtTok(tokens) });
}
