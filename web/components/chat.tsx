"use client";
import { useEffect, useRef, useState } from "react";
import { post } from "@/lib/api";
import { useBoard } from "@/lib/store";

interface Msg { cls: "you" | "bot" | "act" | "think"; text: string }

export default function Chat({ open, setOpen }: { open: boolean; setOpen: (b: boolean) => void }) {
  const { me, refresh } = useBoard();
  const [msgs, setMsgs] = useState<Msg[]>([{
    cls: "bot",
    text: 'Hi — tell me what to do with the board. e.g. "file a card: fix the invoice export, due Friday, €120", "what needs me right now?", "move the contract draft to review".',
  }]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => { logRef.current?.scrollTo(0, 1e9); }, [msgs]);

  if (me?.role === "client") return null;

  async function send() {
    const v = text.trim();
    if (!v || busy) return;
    setText("");
    setMsgs((m) => [...m, { cls: "you", text: v }, { cls: "think", text: "thinking + acting…" }]);
    setBusy(true);
    try {
      const r = await post<{ reply?: string; actions?: string[]; error?: string }>("/chat", { text: v });
      setMsgs((m) => {
        const out = m.filter((x) => x.cls !== "think");
        if (r.error) return [...out, { cls: "bot" as const, text: "⚠ " + r.error }];
        return [...out, { cls: "bot" as const, text: r.reply || "(done)" },
          ...(r.actions ?? []).map((a) => ({ cls: "act" as const, text: "⚙ " + a }))];
      });
      refresh();
    } catch {
      setMsgs((m) => m.filter((x) => x.cls !== "think"));
    }
    setBusy(false);
  }

  if (!open) return <button id="chatfab" title="Chat with the board (k)" onClick={() => setOpen(true)}>💬</button>;
  return (
    <div id="chat">
      <div className="ch">
        <b>Board copilot</b>
        <span style={{ fontSize: 11, color: "var(--txt-tertiary)", marginLeft: 8 }}>chat steers the board</span>
        <button className="x" style={{ marginLeft: "auto", color: "var(--txt-tertiary)", padding: "2px 8px" }}
          onClick={() => setOpen(false)}>✕</button>
      </div>
      <div id="chatlog" ref={logRef}>
        {msgs.map((m, i) => <div key={i} className={`cb ${m.cls}`}>{m.text}</div>)}
      </div>
      <div className="crow">
        <textarea id="chatbox" placeholder="Tell the board what to do…" value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
        <button className="btn primary" disabled={busy} onClick={send}>Send</button>
      </div>
    </div>
  );
}
