"use client";
// The flight recorder surfacing on the board: while a screen-recorded agent
// works a card, its newest frame plays inside the card. 404 (no fresh frame)
// hides it automatically - zero config, it appears exactly when there is
// something to watch.
import { useEffect, useState } from "react";
import { API } from "@/lib/api";

export default function LiveThumb({ trackId, big = false }: { trackId: string; big?: boolean }) {
  const [tick, setTick] = useState(0);
  const [dead, setDead] = useState(false);
  useEffect(() => {
    setDead(false);
    const iv = setInterval(() => setTick((t) => t + 1), 1600);
    return () => clearInterval(iv);
  }, [trackId]);
  if (dead) return null;
  return (
    <div style={{ position: "relative", marginTop: big ? 0 : 8 }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={`${API}/tracks/${trackId}/live?t=${tick}`} alt="live agent screen"
        onError={() => setDead(true)} onLoad={() => setDead(false)}
        style={{
          width: "100%", borderRadius: big ? 10 : 8, display: "block",
          border: "1px solid var(--glass-border)",
        }} />
      <span style={{
        position: "absolute", top: 6, left: 6, display: "inline-flex", alignItems: "center",
        gap: 5, fontSize: 9.5, fontWeight: 700, letterSpacing: ".08em", color: "#fff",
        background: "oklch(0 0 0/55%)", backdropFilter: "blur(6px)",
        borderRadius: 5, padding: "1.5px 7px",
      }}>
        <span style={{
          width: 6, height: 6, borderRadius: "50%", background: "var(--danger)",
          animation: "pulse 1.4s infinite",
        }} />
        LIVE
      </span>
    </div>
  );
}
