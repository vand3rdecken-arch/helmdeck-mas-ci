"use client";
import { useEffect, useRef, useState } from "react";
import { post, Track } from "@/lib/api";
import { LANES, STATUS, PRIO_ORD, useBoard, Spot } from "@/lib/store";
import { IconBriefcase, IconCalendar, IconChain, IconMonitor, ModeIcon, MODE_LABEL } from "./icons";
import LiveThumb from "./live";

export function prioChip(t: Track) {
  const p = t.priority ?? "medium";
  if (p === "medium") return null;
  const map: Record<string, [string, string]> = {
    urgent: ["⚠ urgent", "var(--danger)"], high: ["↑ high", "var(--warn)"], low: ["↓ low", "var(--txt-tertiary)"],
  };
  const [label, color] = map[p] ?? [p, "var(--txt-tertiary)"];
  return <span className="chip" style={{ color }}>{label}</span>;
}

export function dueChip(t: Track) {
  if (!t.due) return null;
  const overdue = t.lane !== "done" && t.due < new Date().toISOString().slice(0, 10);
  return (
    <span className="chip" title="due date"
      style={overdue ? { color: "var(--danger)", borderColor: "var(--danger)" } : undefined}>
      <IconCalendar /> {t.due.slice(5)}{overdue ? " overdue" : ""}
    </span>
  );
}

function clientHues(key: string): [string, string] {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  const h1 = h % 360, h2 = (h1 + 80) % 360;
  return [`oklch(.72 .27 ${h1})`, `oklch(.65 .29 ${h2})`];
}

export function Card({ t, onOpen }: { t: Track; onOpen: (t: Track) => void }) {
  const { met, spot, setSpot } = useBoard();
  const [g1, g2] = t.client ? clientHues(t.client)
    : ["var(--accent)", "var(--accent-2)"];
  const spotKey: Spot | null = t.process ? { type: "process", value: t.process }
    : t.client ? { type: "client", value: t.client } : null;
  const related = spot ? (spot.type === "client" ? t.client === spot.value : t.process === spot.value) : false;
  const alive = t.status === "running";
  const e = met?.cards.find((x) => x.id === t.id);
  let maxA = 0.01, maxH = 1;
  met?.cards.forEach((x) => { if (x.ai_cost > maxA) maxA = x.ai_cost; if (x.touches > maxH) maxH = x.touches; });
  const st = STATUS[t.status] ?? [t.status, "var(--txt-tertiary)"];
  return (
    <div className="gwrap" style={{ "--g1": g1, "--g2": g2 } as React.CSSProperties}>
      <span className="gpanel" aria-hidden />
      <span className="gpanel gblur" aria-hidden />
      <div className={`card${spot ? (related ? " spot" : " dim") : ""}${alive ? " alive" : ""}`} draggable
        onDragStart={(ev) => ev.dataTransfer.setData("text", t.id)}
        onMouseEnter={() => spotKey && setSpot(spotKey)}
        onMouseLeave={() => setSpot(null)}
        onClick={() => onOpen(t)}>
      <div className="cid">{t.branch} · {t.turns} turns</div>
      <div className="title">{t.task}</div>
      <div className="chips">
        <span className="chip"><span className="sdot" style={{ background: st[1] }} />{st[0]}</span>
        {prioChip(t)}{dueChip(t)}
        {t.mode && <span className="chip" title="execution mode"><ModeIcon mode={t.mode} />{MODE_LABEL[t.mode] ?? t.mode}</span>}
        {t.client && <span className="chip" title="client"><IconBriefcase />{t.client}</span>}
        {t.process && <span className="chip" title={t.process_title} style={{ color: "var(--accent-txt)" }}><IconChain />process</span>}
        {t.driver && t.driver !== "claude" && (
          <span className="chip" title="execution driver" style={{ color: "var(--accent-txt)" }}><IconMonitor />{t.driver}</span>
        )}
        {e && <>
          <span className="chip" title="deliverable value">€{e.value}</span>
          <span className="chip" title="AI cost so far">AI ${e.ai_cost.toFixed(2)}</span>
          <span className="chip" title="your touch units">{e.touches}t</span>
          {e.mode && <span className="chip">{e.mode}</span>}
        </>}
      </div>
      {e && (e.ai_cost > 0 || e.touches > 0) && (
        <div className="splitbars" title="AI $ (top) vs human touches (bottom)">
          <i className="ab" style={{ width: `${Math.max(2, Math.round(100 * e.ai_cost / maxA))}%` }} />
          <i className="hb" style={{ width: `${Math.max(2, Math.round(100 * e.touches / maxH))}%` }} />
        </div>
      )}
      {alive && met?.settings?.drivers?.[t.driver]?.record && <LiveThumb trackId={t.id} />}
        {t.gate_report && (
          <div style={{ marginTop: 7, fontSize: 11.5, color: "var(--warn)" }}>
            gate: {t.gate_report.join(" | ").slice(0, 140)}
          </div>
        )}
      </div>
    </div>
  );
}

function NextUp({ onOpen }: { onOpen: (t: Track) => void }) {
  const { tracks, toast, refresh } = useBoard();
  const items = tracks
    .filter((t) => t.lane !== "done" && (t.status === "needs_you" || t.status === "bounced" || (t.up_next && t.lane === "backlog")))
    .sort((a, b) => (PRIO_ORD[a.priority ?? "medium"] - PRIO_ORD[b.priority ?? "medium"]) || ((a.due ?? "9999") < (b.due ?? "9999") ? -1 : 1));
  if (!items.length) return null;
  const why = (t: Track) =>
    t.status === "bounced" ? "gate bounced — fix" :
    t.status === "needs_you" ? "agent needs you" :
    t.mode === "human" ? "your step in the process" :
    t.mode === "teach" ? "demonstrate this once" :
    t.mode === "cowork" ? "cowork — start together" : "next in process";
  async function markDone(ev: React.MouseEvent, tid: string) {
    ev.stopPropagation();
    await post(`/tracks/${tid}/lane`, { lane: "done" });
    toast("Step done — the chain advances");
    setTimeout(refresh, 600);
  }
  return (
    <div id="nextup">
      <b style={{ fontSize: 12, color: "var(--warn)" }}>▶ NEXT UP</b>
      {items.slice(0, 4).map((t) => (
        <span key={t.id} className="nu" onClick={() => onOpen(t)}>
          <ModeIcon mode={t.mode} /> {t.task.replace(/^(PREPARE|COWORK|TEACH|HUMAN STEP)[^:]*: /, "").slice(0, 48)}
          <span className="why">{why(t)}</span>
          {t.mode === "human" && t.lane === "backlog" && (
            <button className="btn ghost" style={{ fontSize: 10.5, padding: "1px 7px" }}
              onClick={(ev) => markDone(ev, t.id)}>✓ done</button>
          )}
        </span>
      ))}
      {items.length > 4 && <span style={{ fontSize: 11.5, color: "var(--txt-tertiary)" }}>+{items.length - 4} more</span>}
    </div>
  );
}

export default function BoardView({ filter, onOpen }: { filter: string; onOpen: (t: Track) => void }) {
  const { tracks, met, toast, refresh, spot } = useBoard();
  const [dragLane, setDragLane] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [fx, setFx] = useState<Record<string, string>>({});
  const prevRef = useRef<Record<string, { status: string; lane: string }>>({});
  const total = tracks.length || 1;

  // completion choreography: diff each poll against the last and stage the
  // right transition - agent finished (shimmer), reached done (shockwave),
  // chain woke the next card (pulse).
  useEffect(() => {
    const prev = prevRef.current;
    const next: Record<string, { status: string; lane: string }> = {};
    const stage: Record<string, string> = {};
    for (const t of tracks) {
      next[t.id] = { status: t.status, lane: t.lane };
      const p = prev[t.id];
      if (!p) continue;
      if (p.lane !== "done" && t.lane === "done") stage[t.id] = "fx-done";
      else if (p.status === "running" && t.status === "needs_you") stage[t.id] = "fx-finished";
      else if (p.lane === "backlog" && t.lane === "working" && t.status === "running") stage[t.id] = "fx-woken";
    }
    prevRef.current = next;
    if (Object.keys(stage).length) {
      setFx((f) => ({ ...f, ...stage }));
      setTimeout(() => setFx((f) => {
        const g = { ...f };
        for (const k of Object.keys(stage)) delete g[k];
        return g;
      }), 1800);
    }
  }, [tracks]);

  async function drop(lane: string, ev: React.DragEvent) {
    ev.preventDefault();
    setDragLane(null);
    const id = ev.dataTransfer.getData("text");
    const res = await post<Track>(`/tracks/${id}/lane`, { lane });
    if (!res?.gate_failed && (lane === "done" || lane === "review")) {
      setFlash(lane); setTimeout(() => setFlash(null), 900);
    }
    if (res?.gate_failed) {
      toast("GATE FAILED — bounced back: " + (res.gate_report ?? []).map((p) => p.split("\n")[0]).join(" | "), 5200);
    } else {
      toast(lane === "working" ? "Dispatched — session starting" : lane === "review" ? "Gate green — submitted" : lane === "done" ? "Accepted" : "Queued");
    }
    setTimeout(refresh, 600);
  }

  return (
    <>
      <NextUp onOpen={onOpen} />
      <div id="board" className={spot ? "spotlighting" : ""}>
        {LANES.map(([key, defName, color]) => {
          const name = met?.settings?.policy?.lane_labels?.[key] ?? defName;
          let inLane = tracks.filter((t) => (t.lane || "working") === key &&
            (filter === "all" ||
             (filter === "needs_you" ? (t.status === "needs_you" || t.status === "bounced")
              : t.client === filter.slice(7))));
          if (key === "backlog") {
            inLane = [...inLane].sort((a, b) =>
              (PRIO_ORD[a.priority ?? "medium"] - PRIO_ORD[b.priority ?? "medium"]) ||
              ((a.due ?? "9999") < (b.due ?? "9999") ? -1 : 1));
          }
          return (
            <div key={key} className={`lane${dragLane === key ? " drag" : ""}${flash === key ? " flash" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setDragLane(key); }}
              onDragLeave={() => setDragLane(null)}
              onDrop={(e) => drop(key, e)}>
              <div className="lane-h">
                <span className="ldot" style={{ background: color }} />
                <span className="lname">{name}</span>
                <span className="lcount">{inLane.length}</span>
                <span className="lprog"><i style={{ width: `${Math.round(100 * inLane.length / total)}%`, background: color }} /></span>
              </div>
              <div className="lane-body">
                {inLane.map((t) => (
                  <div key={t.id} className={fx[t.id] ?? ""}>
                    <Card t={t} onOpen={onOpen} />
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
