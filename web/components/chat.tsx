"use client";
import { useEffect, useRef, useState } from "react";
import { get, post } from "@/lib/api";
import { useBoard } from "@/lib/store";
import { IconChat, IconX } from "./icons";
import Composer, { SendOpts } from "./composer";

interface Msg { cls: "you" | "bot" | "act" | "think"; text: string }

export default function Chat({ open, setOpen, hideFab }: { open: boolean; setOpen: (b: boolean) => void; hideFab?: boolean }) {
  const { me, refresh } = useBoard();
  const [msgs, setMsgs] = useState<Msg[]>([{
    cls: "bot",
    text: 'Hi — tell me what to do with the board. e.g. "file a card: fix the invoice export, due Friday, €120", "what needs me right now?", "move the contract draft to review".',
  }]);
  const [busy, setBusy] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const hydrated = useRef(false);

  useEffect(() => {
    if (hydrated.current || me?.role === "client") return;
    hydrated.current = true;
    get<{ messages: Msg[] }>("/chat/history").then((h) => {
      if (h.messages?.length) setMsgs((m) => [...m, ...h.messages]);
    }).catch(() => {});
  }, [me]);

  useEffect(() => { logRef.current?.scrollTo(0, 1e9); }, [msgs]);

  if (me?.role === "client") return null;

  async function send(v: string, opts: SendOpts) {
    if ((!v && !opts.attachments.length) || busy) return;
    setMsgs((m) => [...m, { cls: "you", text: v || "(attachment)" }, { cls: "think", text: "thinking + acting…" }]);
    setBusy(true);
    try {
      const r = await post<{ reply?: string; actions?: string[]; error?: string }>("/chat",
        { text: v, model: opts.model, thinking: opts.thinking, attachments: opts.attachments });
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

  if (!open) return hideFab ? null : <button id="chatfab" title="Chat with the board (k)" onClick={() => setOpen(true)}><IconChat size={20} /></button>;
  return (
    <div id="chat">
      <div className="ch">
        <b>Board copilot</b>
        <button className="x" style={{ marginLeft: "auto", color: "var(--txt-tertiary)", padding: "2px 8px" }}
          onClick={() => setOpen(false)}><IconX size={13} /></button>
      </div>
      <div id="chatlog" ref={logRef}>
        {msgs.map((m, i) => <div key={i} className={`cb ${m.cls}`}>{m.text}</div>)}
      </div>
      <Composer onSend={send} busy={busy} draftKey="swarm-draft:board"
        placeholder="Tell the board what to do…"
        slashCommands={[
          { name: "file", hint: "file a new card", insert: "File a card: " },
          { name: "next", hint: "what needs me right now?", insert: "What needs me right now?" },
          { name: "move", hint: "move a card to a lane", insert: "Move " },
          { name: "digest", hint: "summarize the board", insert: "Give me a short digest of the board — what's in flight, what's blocked, what's done." },
        ]} />
    </div>
  );
}
