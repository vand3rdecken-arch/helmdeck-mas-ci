"use client";
import { useEffect, useState } from "react";
import { get, post, HistoryRow, Track } from "@/lib/api";
import { STATUS, useBoard } from "@/lib/store";
import LiveThumb from "./live";

export default function Peek({ t, onClose }: { t: Track; onClose: () => void }) {
  const { met, toast, refresh } = useBoard();
  const [hist, setHist] = useState<HistoryRow[]>([]);
  const [steer, setSteer] = useState("");
  const [task, setTask] = useState(t.task);
  const e = met?.cards.find((x) => x.id === t.id);
  const st = STATUS[t.status] ?? [t.status, "var(--txt-tertiary)"];
  const drivers = Object.keys(met?.settings?.drivers ?? { claude: {} });

  useEffect(() => { setTask(t.task); }, [t.id, t.task]);
  useEffect(() => {
    get<HistoryRow[]>(`/tracks/${t.id}/history`).then(setHist).catch(() => setHist([]));
  }, [t.id, t.updated]);

  async function edit(patch: Record<string, unknown>) {
    const r = await post<{ error?: string }>(`/tracks/${t.id}/update`, patch);
    if (r.error) { toast(r.error, 3600); return; }
    toast("Saved");
    refresh();
  }

  async function sendSteer() {
    const v = steer.trim();
    if (!v) return;
    await post(`/tracks/${t.id}/steer`, { text: v });
    setSteer("");
    toast("Steer sent — session resuming");
    setTimeout(refresh, 1500);
  }

  const sel = { width: "auto", fontSize: 12 } as const;
  return (
    <>
      <div id="backdrop" onClick={onClose} />
      <div id="peek">
        <div className="ph">
          <span className="pid">{t.branch} · {t.id}</span>
          <button className="x" onClick={onClose}>✕</button>
        </div>
        <textarea
          value={task}
          onChange={(ev) => setTask(ev.target.value)}
          onBlur={() => task.trim() && task !== t.task && edit({ task: task.trim() })}
          style={{
            margin: "12px 16px 4px", fontSize: 15, fontWeight: 600, lineHeight: 1.4,
            minHeight: 96, resize: "vertical",
          }}
          title="the request — editable, saves on blur"
        />
        <div id="props">
          <span className="k">State</span>
          <span><span className="chip"><span className="sdot" style={{ background: st[1] }} />{st[0]}</span></span>
          <span className="k">Priority</span>
          <span>
            <select style={sel} value={t.priority ?? "medium"} onChange={(ev) => edit({ priority: ev.target.value })}>
              {["urgent", "high", "medium", "low"].map((p) => <option key={p}>{p}</option>)}
            </select>
          </span>
          <span className="k">Due</span>
          <span><input type="date" style={sel} value={t.due ?? ""} onChange={(ev) => edit({ due: ev.target.value })} /></span>
          <span className="k">Value</span>
          <span>
            <input type="number" style={{ ...sel, width: 90 }} defaultValue={t.value}
              onBlur={(ev) => parseFloat(ev.target.value) !== t.value && edit({ value: parseFloat(ev.target.value) || t.value })} />
          </span>
          <span className="k">Client</span>
          <span>
            <input style={{ ...sel, width: 140 }} defaultValue={t.client ?? ""}
              placeholder="—" onBlur={(ev) => ev.target.value.trim() !== (t.client ?? "") && edit({ client: ev.target.value.trim() })} />
          </span>
          <span className="k">Driver</span>
          <span>
            <select style={sel} value={t.driver ?? "claude"} onChange={(ev) => edit({ driver: ev.target.value })}>
              {drivers.map((d) => <option key={d}>{d}</option>)}
            </select>
          </span>
          <span className="k">Repo</span><span style={{ fontSize: 12 }}>{t.repo}</span>
          <span className="k">Session</span><span style={{ fontSize: 12 }}>{t.session_id ?? "not started"}</span>
          {e && <>
            <span className="k">Economics</span>
            <span>€{e.value} · AI ${e.ai_cost.toFixed(2)} · {e.touches} touches{e.mode ? ` · ${e.mode}` : ""}</span>
            <span className="k">Tokens</span>
            <span>{e.tokens_in} in / {e.tokens_out} out{e.models.length ? ` · ${e.models.join(", ")}` : ""}</span>
          </>}
        </div>
        {t.status === "running" && met?.settings?.drivers?.[t.driver]?.record && (
          <div style={{ padding: "10px 16px 0" }}><LiveThumb trackId={t.id} big /></div>
        )}
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
