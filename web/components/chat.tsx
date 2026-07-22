"use client";
import { useEffect, useRef, useState } from "react";
import { get, post } from "@/lib/api";
import { useBoard } from "@/lib/store";
import { IconChat, IconX } from "./icons";
import Composer, { SendOpts } from "./composer";

interface Usage { in: number; out: number; cost?: number }
interface Msg { cls: "you" | "bot" | "act" | "think"; text: string }

export default function Chat({ open, setOpen, hideFab }: { open: boolean; setOpen: (b: boolean) => void; hideFab?: boolean }) {
  const { me, refresh } = useBoard();
  const [msgs, setMsgs] = useState<Msg[]>([{
    cls: "bot",
    text: 'Hi - tell me what to do with the board. e.g. "file a card: fix the invoice export, due Friday, €120", "what needs me right now?", "move the contract draft to review".',
  }]);
  const [busy, setBusy] = useState(false);
  // running context overview (Paseo-style): last turn's input tokens vs the
  // context window, plus cumulative session cost.
  const [ctx, setCtx] = useState<{ used: number; total: number; cost: number } | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const hydrated = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (hydrated.current || me?.role === "client") return;
    hydrated.current = true;
    get<{ messages: (Msg & { usage?: Usage })[] }>("/chat/history").then((h) => {
      if (h.messages?.length) setMsgs((m) => [...m, ...h.messages]);
      // seed the context overview from history so it shows on open, not only
      // after the next reply: last turn's tokens + summed session cost.
      const used = [...(h.messages ?? [])].reverse().find((x) => x.usage && (x.usage.in > 0 || x.usage.out > 0))?.usage;
      const cost = (h.messages ?? []).reduce((s, x) => s + (x.usage?.cost ?? 0), 0);
      if (used) setCtx({ used: used.in, total: 200000, cost });
    }).catch(() => {});
  }, [me]);

  useEffect(() => { logRef.current?.scrollTo(0, 1e9); }, [msgs]);

  if (me?.role === "client") return null;

  async function send(v: string, opts: SendOpts): Promise<{ usage?: Usage } | void> {
    if ((!v && !opts.attachments.length) || busy) return;
    setMsgs((m) => [...m, { cls: "you", text: v || "(attachment)" }, { cls: "think", text: "thinking + acting…" }]);
    setBusy(true);
    const ac = new AbortController();
    abortRef.current = ac;
    let usage: Usage | undefined;
    try {
      const r = await post<{ reply?: string; actions?: string[]; error?: string; usage?: Usage }>("/chat",
        { text: v, model: opts.model, thinking: opts.thinking, attachments: opts.attachments }, ac.signal);
      setMsgs((m) => {
        const out = m.filter((x) => x.cls !== "think");
        if (r.error) return [...out, { cls: "bot" as const, text: "⚠ " + r.error }];
        return [...out, { cls: "bot" as const, text: r.reply || "(done)" },
          ...(r.actions ?? []).map((a) => ({ cls: "act" as const, text: "⚙ " + a }))];
      });
      usage = r.usage;
      refresh();
    } catch {
      // aborted (Stop) or network error: drop the thinking bubble
      setMsgs((m) => m.filter((x) => x.cls !== "think"));
    }
    abortRef.current = null;
    setBusy(false);
    return usage ? { usage } : undefined;   // Composer folds this into the meter
  }

  function stop() {
    abortRef.current?.abort();       // drop the in-flight request client-side
    post("/chat/cancel", {});        // kill the copilot subprocess server-side
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
      <Composer onSend={send} busy={busy} onStop={stop} context={ctx ?? undefined} draftKey="swarm-draft:board"
        placeholder="Tell the board what to do…"
        slashCommands={[
          { name: "file", hint: "file a new card", insert: "File a card: " },
          { name: "next", hint: "what needs me right now?", insert: "What needs me right now?" },
          { name: "move", hint: "move a card to a lane", insert: "Move " },
          { name: "digest", hint: "summarize the board", insert: "Give me a short digest of the board - what's in flight, what's blocked, what's done." },
        ]} />
    </div>
  );
}
