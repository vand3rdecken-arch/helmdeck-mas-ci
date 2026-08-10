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
