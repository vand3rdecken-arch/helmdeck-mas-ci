"use client";
// List + Timeline layouts (Plane's alternate work views).
import { Track } from "@/lib/api";
import { LANES, PRIO_ORD, STATUS, laneColor, useBoard } from "@/lib/store";
import { dueChip, prioChip } from "./board";
import { IconChain } from "./icons";

export function ListView({ filter, onOpen }: { filter: string; onOpen: (t: Track) => void }) {
  const { tracks: all, met } = useBoard();
  const base = filter === "archived" ? all.filter((t) => t.archived) : all.filter((t) => !t.archived);
  const tracks = filter.startsWith("client:") ? base.filter((t) => t.client === filter.slice(7)) : base;
  return (
    <div className="panel" style={{ padding: 0 }}>
      {LANES.map(([key, defName, color]) => {
        const name = met?.settings?.policy?.lane_labels?.[key] ?? defName;
        const inLane = tracks.filter((t) => (t.lane || "working") === key);
        if (!inLane.length) return null;
        return (
          <div key={key}>
            <div className="lgroup">
              <span className="ldot" style={{ background: color, width: 8, height: 8 }} />
              {name}<span className="lcount">{inLane.length}</span>
            </div>
            {inLane.map((t) => {
              const st = STATUS[t.status] ?? [t.status, "var(--txt-tertiary)"];
              const e = met?.cards.find((x) => x.id === t.id);
              return (
                <div key={t.id} className="lrow" onClick={() => onOpen(t)}>
                  <span className="lbranch">{t.branch}</span>
                  <span className="ltask">{t.task}</span>
                  <span className="chip"><span className="sdot" style={{ background: st[1] }} />{st[0]}</span>
                  {prioChip(t)}{dueChip(t)}
                  {e && <>
                    <span className="chip">€{e.value}</span>
                    <span className="chip">AI ${e.ai_cost.toFixed(2)}</span>
                    <span className="chip">{e.touches}t</span>
                  </>}
                  <span style={{ fontSize: 11, color: "var(--txt-tertiary)", width: 118, textAlign: "right" }}>{t.updated}</span>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

const DAY = 86400e3;
const parseTs = (s?: string) => (s ? new Date(s.replace(" ", "T")).getTime() : null);

export function TimelineView({ filter, onOpen }: { filter: string; onOpen: (t: Track) => void }) {
  const { tracks: all } = useBoard();
  const base = filter === "archived" ? all.filter((t) => t.archived) : all.filter((t) => !t.archived);
  const tracks = filter.startsWith("client:") ? base.filter((t) => t.client === filter.slice(7)) : base;
  const now = Date.now();
  const ts = tracks.map((t) => ({
    t,
    a: parseTs(t.created) ?? now,
    b: (t.lane === "done" ? parseTs(t.updated) : now) ?? now,
    due: t.due ? parseTs(t.due + " 23:59:59") : null,
  }));
  if (!ts.length) return <div className="panel">no work yet</div>;
  let min = Math.min(...ts.map((x) => x.a));
  const max = Math.max(now, ...ts.map((x) => Math.max(x.b, x.due ?? 0)));
  const d0 = new Date(min); d0.setHours(0, 0, 0, 0); min = d0.getTime();
  const days = Math.max(1, Math.ceil((max - min) / DAY));
  const pxday = Math.max(64, Math.floor(900 / days));
  const W = days * pxday;
  const x = (t: number) => Math.round((t - min) / DAY * pxday);

  const sorted = [...ts].sort((a, b) => {
    const pa = a.t.process ?? "~", pb = b.t.process ?? "~";
    return pa < pb ? -1 : pa > pb ? 1 : a.a - b.a;
  });
  const hasProc = sorted.some((r) => r.t.process);
  let lastProc: string | null | undefined = undefined;

  return (
    <>
      <div id="gantt">
        <div className="g-head">
          <div className="g-side">card</div>
          <div className="g-days" style={{ width: W }}>
            {Array.from({ length: days }, (_, i) => {
              const d = new Date(min + i * DAY);
              return <div key={i} className="g-day" style={{ width: pxday }}>{d.getMonth() + 1}/{d.getDate()}</div>;
            })}
          </div>
        </div>
        {sorted.map((r) => {
          const t = r.t;
          const proc = t.process ?? null;
          const hdr = proc !== lastProc ? (lastProc = proc, proc ? (
            <div className="g-row" style={{ background: "var(--bg-layer-1)" }}>
              <div className="g-side" style={{ color: "var(--accent-txt)", display: "flex", alignItems: "center", gap: 5 }}>
                <IconChain size={13} /> {t.process_title ?? proc}{t.client ? ` · ${t.client}` : ""}
              </div>
              <div className="g-track" style={{ width: W, height: 22 }} />
            </div>
          ) : hasProc ? (
            <div className="g-row" style={{ background: "var(--bg-layer-1)" }}>
              <div className="g-side" style={{ color: "var(--txt-tertiary)" }}>single cards</div>
              <div className="g-track" style={{ width: W, height: 22 }} />
            </div>
          ) : null) : null;
          const l = x(r.a), w = Math.max(14, x(r.b) - l);
          const late = r.due != null && t.lane !== "done" && now > r.due;
          return (
            <div key={t.id}>
              {hdr}
              <div className="g-row click" onClick={() => onOpen(t)}>
                <div className="g-side" title={t.task}>{t.task}</div>
                <div className="g-track" style={{ width: W }}>
                  <div className="g-today" style={{ left: x(now) }} />
                  {r.due != null && (
                    <div title={`due ${t.due}`} style={{
                      position: "absolute", left: x(r.due) - 5, top: 11, width: 10, height: 10,
                      transform: "rotate(45deg)", background: late ? "var(--danger)" : "var(--txt-tertiary)",
                    }} />
                  )}
                  <div className="g-bar" style={{ left: l, width: w, background: laneColor(t.lane) }}
                    title={`${t.branch} · ${t.lane}`}>
                    <span>{t.branch} · {t.lane}{late && <b style={{ color: "var(--danger)" }}> · overdue</b>}</span>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ marginTop: 10, fontSize: 11.5, color: "var(--txt-tertiary)" }}>
        bar = filed → last activity (done cards freeze at acceptance) ·{" "}
        <span style={{ color: "var(--ai)" }}>■</span> working · <span style={{ color: "var(--human)" }}>■</span> review ·{" "}
        <span style={{ color: "var(--ok)" }}>■</span> done · blue line = now · ◆ = due
      </div>
    </>
  );
}
