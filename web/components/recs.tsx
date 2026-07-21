"use client";
import { useEffect, useState } from "react";
import { API, get, HistoryRow, Run } from "@/lib/api";

function RunRow({ m }: { m: Run }) {
  const [open, setOpen] = useState(false);
  const [tl, setTl] = useState<HistoryRow[] | null>(null);
  useEffect(() => {
    if (open && tl === null) {
      get<HistoryRow[]>(`/runs/${m.id}/timeline`).then(setTl).catch(() => setTl([]));
    }
  }, [open, tl, m.id]);
  return (
    <div className={`run${open ? " open" : ""}`}>
      <div className="run-h" onClick={() => setOpen(!open)}>
        <span className="rkind">{m.kind}</span>
        <span className="rt">{m.title}</span>
        <span className="rm">{m.id} · {m.status} · {m.steps ?? 0} steps</span>
        <span className="chev">▸</span>
      </div>
      {open && (
        <div className="run-body">
          {tl === null && <div style={{ color: "var(--txt-tertiary)" }}>loading…</div>}
          {tl && <>
            <ul className="steps">
              {tl.map((s, i) => (
                <li key={i} className={s.kind === "flag" ? "flag" : ""}>
                  <span className="st">{(s.t ?? 0).toFixed(1)}s</span>
                  <span className="sk">{s.kind}</span>
                  <span>{s.detail}</span>
                </li>
              ))}
            </ul>
            <video controls preload="none" src={`${API}/runs/${m.id}/video`} />
          </>}
        </div>
      )}
    </div>
  );
}

export default function RecsView() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  useEffect(() => { get<Run[]>("/runs").then(setRuns).catch(() => setRuns([])); }, []);
  if (runs === null) return <div style={{ color: "var(--txt-tertiary)", fontSize: 12.5 }}>loading…</div>;
  if (!runs.length) {
    return (
      <div className="panel" style={{ maxWidth: 560 }}>
        <h3>No recordings yet</h3>
        <div style={{ fontSize: 12.5, color: "var(--txt-secondary)" }}>
          Record a demo (<b>swarm.py teach</b>), run a task, or dispatch a card — every agent run lands here
          as a step timeline with drill-down video.
        </div>
      </div>
    );
  }
  return <>{runs.map((m) => <RunRow key={m.id} m={m} />)}</>;
}
