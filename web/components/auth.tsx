"use client";
import { useEffect, useState } from "react";
import { post, get, Me } from "@/lib/api";
import { useBoard } from "@/lib/store";

interface AuthState { setup_needed: boolean; registration: boolean; registration_open: boolean }

export default function AuthGate() {
  const { setAuthed } = useBoard();
  const [st, setSt] = useState<AuthState | null>(null);
  const [mode, setMode] = useState<"in" | "up" | "setup">("in");
  const [name, setName] = useState("");
  const [pw, setPw] = useState("");
  const [invite, setInvite] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    get<AuthState & { user: Me | null }>("/auth/state").then((s) => {
      setSt(s);
      if (s.setup_needed) setMode("setup");
    }).catch(() => setSt({ setup_needed: false, registration: false, registration_open: false }));
  }, []);

  async function go() {
    setBusy(true); setErr("");
    const url = mode === "setup" ? "/auth/setup" : mode === "up" ? "/auth/register" : "/auth/login";
    try {
      const r = await post<{ ok?: boolean; error?: string }>(url, { name: name.trim(), password: pw, invite: invite.trim() });
      if (r.error) { setErr(r.error); setBusy(false); return; }
      const m = await get<Me>("/me");
      setAuthed(m);
    } catch {
      setErr("wrong name or password"); setBusy(false);
    }
  }

  if (!st) return null;
  const setup = mode === "setup";
  return (
    <div id="authwrap">
      <div id="authcard" onKeyDown={(e) => e.key === "Enter" && go()}>
        <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 14 }}>
          <span style={{ width: 26, height: 26, borderRadius: 7, background: "var(--accent)", display: "grid", placeItems: "center", color: "#fff", fontWeight: 700, fontSize: 13 }}>S</span>
          <b style={{ fontSize: 15 }}>SwarmDeck</b>
        </div>
        {setup ? (
          <>
            <h3 style={{ margin: "0 0 4px", fontSize: 14 }}>Create the owner account</h3>
            <div style={{ fontSize: 12, color: "var(--txt-tertiary)", marginBottom: 12 }}>
              First run — this account manages everything, including other users.
            </div>
          </>
        ) : (
          <div className="authtabs">
            <span className={mode === "in" ? "on" : ""} onClick={() => setMode("in")}>Sign in</span>
            {st.registration && (
              <span className={mode === "up" ? "on" : ""} onClick={() => setMode("up")}>Create account</span>
            )}
          </div>
        )}
        <input placeholder="username" autoComplete="username" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        <input type="password" placeholder={mode === "in" ? "password" : "password (min 8 chars)"}
          autoComplete={mode === "in" ? "current-password" : "new-password"}
          value={pw} onChange={(e) => setPw(e.target.value)} />
        {mode === "up" && !st.registration_open && (
          <input placeholder="invite code" value={invite} onChange={(e) => setInvite(e.target.value)} />
        )}
        <div style={{ fontSize: 12, color: "var(--danger)", marginTop: 8, minHeight: 16 }}>{err}</div>
        <button className="btn primary" disabled={busy} onClick={go}
          style={{ width: "100%", justifyContent: "center", padding: 8 }}>
          {setup ? "Create & sign in" : mode === "up" ? "Create account" : "Sign in"}
        </button>
      </div>
    </div>
  );
}
