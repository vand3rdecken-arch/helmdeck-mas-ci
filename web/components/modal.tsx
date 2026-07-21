"use client";
import { useState } from "react";
import { post } from "@/lib/api";
import { useBoard } from "@/lib/store";

const EXAMPLES = [
  { label: "🐛 bug fix", task: "Fix: the dashboard capacity gauge shows 0% when touch budget is 0 — guard the division and show a hint instead.", driver: "claude" },
  { label: "✨ feature", task: "Add a CSV export button to the dashboard work table (all columns, current filters applied).", driver: "claude" },
  { label: "🖥 desktop task", task: "Open the invoice tool, export June as PDF into Downloads, and verify the file exists.", driver: "claude-desktop" },
  { label: "🌐 browser task", task: "Go to the supplier portal, download the latest price list, and summarize what changed vs the file in data/prices.csv.", driver: "claude-desktop" },
  { label: "🔍 research", task: "Read the three competitor changelogs linked in docs/watchlist.md and write a one-page summary of what shipped this month.", driver: "claude" },
];

export default function NewRequestModal({ onClose }: { onClose: () => void }) {
  const { met, toast, refresh } = useBoard();
  const [task, setTask] = useState("");
  const [priority, setPriority] = useState("medium");
  const [due, setDue] = useState("");
  const [repo, setRepo] = useState("");
  const [branch, setBranch] = useState("");
  const [value, setValue] = useState("");
  const [client, setClient] = useState("");
  const [driver, setDriver] = useState("claude");
  const [adv, setAdv] = useState(false);
  const [followup, setFollowup] = useState<string[] | null>(null);
  const drivers = Object.keys(met?.settings?.drivers ?? { claude: {} });

  async function file() {
    const tv = task.trim();
    if (!tv) { toast("Describe the task"); return; }
    if (followup === null) {
      const asks: string[] = [];
      if (tv.length < 25) asks.push("the task is very short — an agent works better with a sentence of context (what, where, what does done look like)");
      if (!value.trim()) asks.push(`no value set — dashboard will use the €${met?.settings?.value_per_card ?? 50} default (margin/ROI will be generic)`);
      if (!due) asks.push("no due date — the card won’t show risk on the timeline");
      if (asks.length) { setFollowup(asks); if (!value.trim()) setAdv(true); return; }
    }
    const body: Record<string, unknown> = { task: tv, lane: "backlog", priority, due, driver };
    if (repo.trim()) body.repo = repo.trim();
    if (branch.trim()) body.branch = branch.trim();
    if (value.trim()) body.value = parseFloat(value);
    if (client.trim()) body.client = client.trim();
    const r = await post<{ error?: string }>("/tracks/new", body);
    if (r.error) { toast(r.error, 4000); return; }
    toast("Filed to Backlog");
    refresh();
    onClose();
  }

  return (
    <div id="modal" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div id="mcard">
        <h3>New request</h3>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
          {EXAMPLES.map((ex) => (
            <button key={ex.label} className="btn ghost" style={{ fontSize: 11, padding: "2px 9px" }}
              title={ex.task} onClick={() => { setTask(ex.task); setDriver(ex.driver); }}>
              {ex.label}
            </button>
          ))}
        </div>
        <textarea placeholder="What needs doing — that's all that's required. Repo comes from your preset."
          value={task} onChange={(e) => setTask(e.target.value)} autoFocus />
        <div className="row" style={{ alignItems: "center", marginTop: 10 }}>
          <select value={priority} onChange={(e) => setPriority(e.target.value)} style={{ width: 130 }}>
            <option value="urgent">urgent</option><option value="high">high</option>
            <option value="medium">medium</option><option value="low">low</option>
          </select>
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} style={{ width: 150 }} title="due date" />
          <span style={{ fontSize: 11, color: "var(--txt-tertiary)" }}>priority · due date</span>
        </div>
        {followup && followup.length > 0 && (
          <div id="m-followup">
            <b style={{ color: "var(--warn)" }}>Before filing:</b>
            <ul style={{ margin: "4px 0 4px 16px", padding: 0 }}>
              {followup.map((a, i) => <li key={i}>{a}</li>)}
            </ul>
            Fill them above, or click <b>File to Backlog</b> again to file as-is.
          </div>
        )}
        <div className="adv" onClick={() => setAdv(!adv)}>▸ advanced (repo / branch / value / client / driver)</div>
        {adv && <>
          <div className="row"><input style={{ flex: 1 }} placeholder="repo path (default preset used if empty)" value={repo} onChange={(e) => setRepo(e.target.value)} /></div>
          <div className="row">
            <input style={{ flex: 1 }} placeholder="branch (auto from task if empty)" value={branch} onChange={(e) => setBranch(e.target.value)} />
            <input style={{ width: 110 }} placeholder="value €" value={value} onChange={(e) => setValue(e.target.value)} />
            <input style={{ width: 130 }} placeholder="client" value={client} onChange={(e) => setClient(e.target.value)} />
          </div>
          <div className="row">
            <select style={{ flex: 1 }} value={driver} onChange={(e) => setDriver(e.target.value)}>
              {drivers.map((d) => (
                <option key={d} value={d}>
                  driver: {d}{met?.settings?.drivers?.[d]?.record ? " (screen-recorded)" : ""}
                </option>
              ))}
            </select>
          </div>
        </>}
        <div className="foot">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={file}>File to Backlog</button>
        </div>
      </div>
    </div>
  );
}
