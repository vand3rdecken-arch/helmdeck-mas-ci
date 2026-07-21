"use client";
import { useEffect, useState } from "react";
import { get, post, HistoryRow, Track } from "@/lib/api";
import { STATUS, useBoard } from "@/lib/store";

export default function Peek({ t, onClose }: { t: Track; onClose: () => void }) {
  const { met, toast, refresh } = useBoard();
  const [hist, setHist] = useState<HistoryRow[]>([]);
  const [steer, setSteer] = useState("");
  const e = met?.cards.find((x) => x.id === t.id);
  const st = STATUS[t.status] ?? [t.status, "var(--txt-tertiary)"];

  useEffect(() => {
    get<HistoryRow[]>(`/tracks/${t.id}/history`).then(setHist).catch(() => setHist([]));
  }, [t.id, t.updated]);

  async function sendSteer() {
    const v = steer.trim();
    if (!v) return;
    await post(`/tracks/${t.id}/steer`, { text: v });
    setSteer("");
    toast("Steer sent — session resuming");
    setTimeout(refresh, 1500);
  }

  return (
    <>
      <div id="backdrop" onClick={onClose} />
      <div id="peek">
        <div className="ph">
          <span className="pid">{t.branch} · {t.id}</span>
          <button className="x" onClick={onClose}>✕</button>
        </div>
        <div className="ptitle">{t.task}</div>
        <div id="props">
          <span className="k">State</span>
          <span><span className="chip"><span className="sdot" style={{ background: st[1] }} />{st[0]}</span></span>
          <span className="k">Repo</span><span style={{ fontSize: 12 }}>{t.repo}</span>
          <span className="k">Session</span><span style={{ fontSize: 12 }}>{t.session_id ?? "not started"}</span>
          <span className="k">Driver</span><span style={{ fontSize: 12 }}>{t.driver ?? "claude"}</span>
          {e && <>
            <span className="k">Economics</span>
            <span>€{e.value} · AI ${e.ai_cost.toFixed(2)} · {e.touches} touches{e.mode ? ` · ${e.mode}` : ""}</span>
            <span className="k">Tokens</span>
            <span>{e.tokens_in} in / {e.tokens_out} out{e.models.length ? ` · ${e.models.join(", ")}` : ""}</span>
          </>}
        </div>
        <div id="feed">
          {hist.map((r, i) =>
            r.kind === "steer" ? <div key={i} className="f-steer">{r.detail}</div> :
            r.kind === "reply" ? <div key={i} className="f-reply">{r.detail}</div> :
            <div key={i} className="f-note">{r.detail}</div>
          )}
        </div>
        <div id="steer-row">
          <textarea id="steer-box" placeholder="Steer this session — context continues, no rebuild"
            value={steer} onChange={(e2) => setSteer(e2.target.value)} />
          <button className="btn primary" onClick={sendSteer}>Send</button>
        </div>
      </div>
    </>
  );
}
