"use client";
import { useState } from "react";
import { post, Track } from "@/lib/api";
import { LANES, STATUS, PRIO_ORD, MODE_EMOJI, MODE_ICON, useBoard } from "@/lib/store";

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
      📅 {t.due.slice(5)}{overdue ? " overdue" : ""}
    </span>
  );
}

export function Card({ t, onOpen }: { t: Track; onOpen: (t: Track) => void }) {
  const { met } = useBoard();
  const e = met?.cards.find((x) => x.id === t.id);
  let maxA = 0.01, maxH = 1;
  met?.cards.forEach((x) => { if (x.ai_cost > maxA) maxA = x.ai_cost; if (x.touches > maxH) maxH = x.touches; });
  const st = STATUS[t.status] ?? [t.status, "var(--txt-tertiary)"];
  return (
    <div className="card" draggable
      onDragStart={(ev) => ev.dataTransfer.setData("text", t.id)}
      onClick={() => onOpen(t)}>
      <div className="cid">{t.branch} · {t.turns} turns</div>
      <div className="title">{t.task}</div>
      <div className="chips">
        <span className="chip"><span className="sdot" style={{ background: st[1] }} />{st[0]}</span>
        {prioChip(t)}{dueChip(t)}
        {t.mode && <span className="chip" title="execution mode">{MODE_ICON[t.mode] ?? t.mode}</span>}
        {t.process && <span className="chip" title={t.process_title} style={{ color: "var(--accent-txt)" }}>⛓ process</span>}
        {t.driver && t.driver !== "claude" && (
          <span className="chip" title="execution driver" style={{ color: "var(--accent-txt)" }}>🖥 {t.driver}</span>
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
      {t.gate_report && (
        <div style={{ marginTop: 7, fontSize: 11.5, color: "var(--warn)" }}>
          gate: {t.gate_report.join(" | ").slice(0, 140)}
        </div>
      )}
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
          {t.mode ? MODE_EMOJI[t.mode] : ""} {t.task.replace(/^(PREPARE|COWORK|TEACH|HUMAN STEP)[^:]*: /, "").slice(0, 48)}
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
  const { tracks, toast, refresh } = useBoard();
  const [dragLane, setDragLane] = useState<string | null>(null);

  async function drop(lane: string, ev: React.DragEvent) {
    ev.preventDefault();
    setDragLane(null);
    const id = ev.dataTransfer.getData("text");
    const res = await post<Track>(`/tracks/${id}/lane`, { lane });
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
      <div id="board">
        {LANES.map(([key, name, color]) => {
          let inLane = tracks.filter((t) => (t.lane || "working") === key &&
            (filter !== "needs_you" || t.status === "needs_you" || t.status === "bounced"));
          if (key === "backlog") {
            inLane = [...inLane].sort((a, b) =>
              (PRIO_ORD[a.priority ?? "medium"] - PRIO_ORD[b.priority ?? "medium"]) ||
              ((a.due ?? "9999") < (b.due ?? "9999") ? -1 : 1));
          }
          return (
            <div key={key} className={`lane${dragLane === key ? " drag" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setDragLane(key); }}
              onDragLeave={() => setDragLane(null)}
              onDrop={(e) => drop(key, e)}>
              <div className="lane-h">
                <span className="ldot" style={{ background: color }} />
                <span className="lname">{name}</span>
                <span className="lcount">{inLane.length}</span>
              </div>
              <div className="lane-body">
                {inLane.map((t) => <Card key={t.id} t={t} onOpen={onOpen} />)}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}
