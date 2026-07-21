"use client";
// ⌘K command palette: jump to any card or view; "> ..." sends the rest to the
// board copilot as an action.
import { useEffect, useMemo, useRef, useState } from "react";
import { post, Track } from "@/lib/api";
import { useBoard } from "@/lib/store";

interface Item { label: string; hint: string; run: () => void }

export default function Palette({ onOpen, onNav, onClose }: {
  onOpen: (t: Track) => void; onNav: (v: string) => void; onClose: () => void;
}) {
  const { tracks, toast, refresh } = useBoard();
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { inputRef.current?.focus(); }, []);

  const items = useMemo<Item[]>(() => {
    if (q.startsWith(">")) {
      const cmd = q.slice(1).trim();
      return cmd ? [{
        label: `Ask the copilot: “${cmd}”`, hint: "↵",
        run: async () => {
          onClose(); toast("Copilot working…", 8000);
          const r = await post<{ reply?: string; actions?: string[]; error?: string }>("/chat", { text: cmd });
          toast(r.error ? "⚠ " + r.error : (r.actions?.length ? r.actions.join(" · ") : r.reply ?? "done"), 6000);
          refresh();
        },
      }] : [];
    }
    const ql = q.toLowerCase();
    const views: Item[] = [
      ["Board", "board"], ["List", "list"], ["Timeline", "timeline"],
      ["Processes", "procs"], ["Dashboard", "dash"], ["Recordings", "recs"], ["Settings", "settings"],
    ].filter(([l]) => !ql || l.toLowerCase().includes(ql))
      .map(([l, v]) => ({ label: "Go to " + l, hint: "view", run: () => { onNav(v); onClose(); } }));
    const cards: Item[] = tracks
      .filter((t) => !ql || t.task.toLowerCase().includes(ql) || t.branch.toLowerCase().includes(ql)
        || (t.client ?? "").toLowerCase().includes(ql))
      .slice(0, 8)
      .map((t) => ({
        label: t.task.slice(0, 64), hint: `${t.lane}${t.client ? " · " + t.client : ""}`,
        run: () => { onOpen(t); onClose(); },
      }));
    return [...cards, ...views].slice(0, 12);
  }, [q, tracks, onNav, onOpen, onClose, toast, refresh]);

  useEffect(() => { setSel(0); }, [q]);

  return (
    <div id="palette" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div id="palcard" onKeyDown={(e) => {
        if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, items.length - 1)); }
        if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
        if (e.key === "Enter") items[sel]?.run();
        if (e.key === "Escape") onClose();
      }}>
        <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="Search cards, jump to views — or  >  to command the copilot" />
        <div id="pallist">
          {items.map((it, i) => (
            <div key={i} className={`palrow${i === sel ? " sel" : ""}`}
              onMouseEnter={() => setSel(i)} onClick={it.run}>
              {it.label}<span className="k">{it.hint}</span>
            </div>
          ))}
          {!items.length && <div className="palrow">nothing matches</div>}
        </div>
        <div className="palhint">↑↓ navigate · ↵ open · &gt; command (e.g. “&gt; move the draft to review”) · esc close</div>
      </div>
    </div>
  );
}
