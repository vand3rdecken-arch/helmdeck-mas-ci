"use client";
import { useCallback, useEffect, useState } from "react";
import { get, post, UserRow } from "@/lib/api";
import { useBoard } from "@/lib/store";

export default function SettingsView() {
  const { met, me, toast, refresh } = useBoard();
  const s = met?.settings;
  const [repo, setRepo] = useState(""); const [value, setValue] = useState("50");
  const [wip, setWip] = useState("6"); const [budget, setBudget] = useState("30");
  const [t1, setT1] = useState("1"); const [t2, setT2] = useState("1"); const [t3, setT3] = useState("3");
  const [regOpen, setRegOpen] = useState(false); const [regCode, setRegCode] = useState("");
  const [regRole, setRegRole] = useState("client");
  const [loaded, setLoaded] = useState(false);
  const [users, setUsers] = useState<UserRow[] | null>(null);
  const [uName, setUName] = useState(""); const [uPw, setUPw] = useState(""); const [uRole, setURole] = useState("operator");
  const [autoAccept, setAutoAccept] = useState(false);
  const [autoModes, setAutoModes] = useState<string[]>(["do", "prepare"]);
  const [autoPrio, setAutoPrio] = useState("");
  const [laneLabels, setLaneLabels] = useState<Record<string, string>>({
    backlog: "Backlog", working: "Working", review: "Review", done: "Done" });
  const [backdrop, setBackdrop] = useState("mesh");
  const [chatRoles, setChatRoles] = useState<string[]>(["owner"]);
  const [jBase, setJBase] = useState(""); const [jEmail, setJEmail] = useState("");
  const [jToken, setJToken] = useState(""); const [jJql, setJJql] = useState("");
  const [impUrl, setImpUrl] = useState(""); const [busyImp, setBusyImp] = useState(false);

  useEffect(() => {
    if (s && !loaded) {
      setRepo(s.default_repo ?? ""); setValue(String(s.value_per_card));
      setWip(String(s.capacity.wip_limit)); setBudget(String(s.capacity.touch_budget_day));
      setT1(String(s.capacity.tariff.steer)); setT2(String(s.capacity.tariff.review)); setT3(String(s.capacity.tariff.bounce));
      setRegOpen(!!s.registration?.open); setRegCode(s.registration?.invite_code ?? "");
      setRegRole(s.registration?.default_role ?? "client");
      setAutoAccept(!!s.policy?.auto_accept_green);
      setAutoModes(s.policy?.auto_dispatch_modes ?? ["do", "prepare"]);
      setAutoPrio(s.policy?.auto_dispatch_priority ?? "");
      setLaneLabels({ backlog: "Backlog", working: "Working", review: "Review", done: "Done", ...(s.policy?.lane_labels ?? {}) });
      setBackdrop(s.appearance?.backdrop ?? "mesh");
      setChatRoles(s.policy?.chat_configure_roles ?? ["owner"]);
      setJBase(s.jira?.base ?? ""); setJEmail(s.jira?.email ?? "");
      setJToken(s.jira?.api_token ?? ""); setJJql(s.jira?.default_jql ?? "");
      setLoaded(true);
    }
  }, [s, loaded]);

  const loadUsers = useCallback(() => {
    get<UserRow[]>("/users").then(setUsers).catch(() => setUsers([]));
  }, []);
  useEffect(() => { if (me?.role === "owner") loadUsers(); }, [me, loadUsers]);

  async function save() {
    await post("/settings", {
      default_repo: repo.trim(), value_per_card: parseFloat(value) || 50,
      capacity: { wip_limit: parseInt(wip) || 6, touch_budget_day: parseInt(budget) || 30,
        tariff: { steer: +t1 || 1, review: +t2 || 1, bounce: +t3 || 3 } },
    });
    toast("Settings saved"); refresh();
  }
  async function savePolicy() {
    await post("/settings", { policy: { auto_accept_green: autoAccept,
      auto_dispatch_modes: autoModes, auto_dispatch_priority: autoPrio,
      lane_labels: laneLabels, chat_configure_roles: chatRoles }, appearance: { backdrop } });
    toast("Policy saved"); refresh();
  }
  async function saveReg() {
    await post("/settings", { registration: { open: regOpen, invite_code: regCode.trim(), default_role: regRole } });
    toast("Registration settings saved");
  }
  async function addUser() {
    const r = await post<{ error?: string }>("/users", { name: uName.trim(), password: uPw, role: uRole });
    if (r.error) { toast(r.error, 3600); return; }
    toast("User created"); setUName(""); setUPw(""); loadUsers();
  }
  async function userAct(path: string, body: Record<string, unknown>, msg: string) {
    const r = await post<{ error?: string; token?: string }>(path, body);
    if (r.error) { toast(r.error, 3600); return; }
    if (r.token) prompt("Device token - copy it now:", r.token);
    else toast(msg);
    loadUsers();
  }

  if (!s) return <div className="panel">owner only</div>;
  return (
    <div id="settings">
      <div className="panel">
        <h3>Business settings</h3>
        <label>Default repo (tickets need no path when set)</label>
        <input value={repo} onChange={(e) => setRepo(e.target.value)} />
        <label>Value per card ({s.currency})</label>
        <input type="number" value={value} onChange={(e) => setValue(e.target.value)} />
        <label>WIP limit</label>
        <input type="number" value={wip} onChange={(e) => setWip(e.target.value)} />
        <label>Touch budget / day</label>
        <input type="number" value={budget} onChange={(e) => setBudget(e.target.value)} />
        <label>Touch tariff (steer / review / bounce)</label>
        <div style={{ display: "flex", gap: 8 }}>
          <input type="number" value={t1} onChange={(e) => setT1(e.target.value)} />
          <input type="number" value={t2} onChange={(e) => setT2(e.target.value)} />
          <input type="number" value={t3} onChange={(e) => setT3(e.target.value)} />
        </div>
        <div style={{ marginTop: 14 }}>
          <button className="btn primary" onClick={save}>Save</button>
        </div>
      </div>
      <div className="panel">
        <h3>Automation policy - the flexible half of the loop</h3>
        <div style={{ fontSize: 12, color: "var(--txt-tertiary)", marginBottom: 10 }}>
          How work flows is configurable (also via the copilot chat). What makes it trustable -
          auth, the audit trail, the gate itself, driver commands - is fixed in code.
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 7, margin: "6px 0", fontSize: 12.5, color: "var(--txt-primary)" }}>
          <input type="checkbox" checked={autoAccept}
            onChange={(e) => setAutoAccept(e.target.checked)} />
          Auto-accept on green gate (chain steps complete without a human; off = you accept everything)
        </label>
        <label>Which step modes may the chain start on its own?</label>
        <div style={{ display: "flex", gap: 12, fontSize: 12.5, flexWrap: "wrap" }}>
          {["do", "prepare", "cowork"].map((m) => (
            <label key={m} style={{ display: "flex", alignItems: "center", gap: 5, margin: 0, color: "var(--txt-primary)" }}>
              <input type="checkbox" checked={autoModes.includes(m)}
                onChange={(e) => setAutoModes(e.target.checked ? [...autoModes, m] : autoModes.filter((x) => x !== m))} />
              {m}
            </label>
          ))}
        </div>
        <label>Backlog self-dispatch (cards at/above this priority start themselves within WIP headroom)</label>
        <select style={{ width: 180 }} value={autoPrio} onChange={(e) => setAutoPrio(e.target.value)}>
          <option value="">never (default)</option>
          <option value="urgent">urgent only</option>
          <option value="high">high + urgent</option>
        </select>
        <label>Backdrop theme (ambient, behind the glass - data colors stay semantic)</label>
        <select style={{ width: 180 }} value={backdrop} onChange={async (e) => {
          const v = e.target.value;
          setBackdrop(v);
          document.documentElement.dataset.backdrop = v;   // instant preview
          await post("/settings", { appearance: { backdrop: v } });
          toast(`Backdrop: ${v}`);
          refresh();
        }}>
          {["mesh", "aurora", "ember", "forest", "mono"].map((b) => <option key={b}>{b}</option>)}
        </select>
        <label>Who may reconfigure the workspace from the copilot chat?</label>
        <div style={{ display: "flex", gap: 12, fontSize: 12.5 }}>
          {["owner", "operator"].map((r) => (
            <label key={r} style={{ display: "flex", alignItems: "center", gap: 5, margin: 0, color: "var(--txt-primary)" }}>
              <input type="checkbox" checked={chatRoles.includes(r)}
                onChange={(e) => setChatRoles(e.target.checked ? [...chatRoles, r] : chatRoles.filter((x) => x !== r))} />
              {r}
            </label>
          ))}
        </div>
        <label>Lane labels (rename the loop&apos;s states; semantics stay fixed)</label>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {(["backlog", "working", "review", "done"] as const).map((k) => (
            <input key={k} style={{ width: 130 }} value={laneLabels[k] ?? ""} title={k}
              onChange={(e) => setLaneLabels({ ...laneLabels, [k]: e.target.value })} />
          ))}
        </div>
        <div style={{ marginTop: 14 }}>
          <button className="btn primary" onClick={savePolicy}>Save policy</button>
        </div>
      </div>
      <div className="panel">
        <h3>Data flows - import work from other systems</h3>
        <label>Jira Cloud (base URL · account email · API token · default JQL)</label>
        <div className="inline">
          <input placeholder="https://your.atlassian.net" style={{ width: 220 }} value={jBase} onChange={(e) => setJBase(e.target.value)} />
          <input placeholder="email" style={{ width: 180 }} value={jEmail} onChange={(e) => setJEmail(e.target.value)} />
          <input type="password" placeholder="API token" style={{ width: 160 }} value={jToken} onChange={(e) => setJToken(e.target.value)} />
        </div>
        <div className="inline" style={{ marginTop: 8 }}>
          <input placeholder='JQL, e.g. project = ABC AND status = "To Do"' style={{ width: 380 }} value={jJql} onChange={(e) => setJJql(e.target.value)} />
          <button className="btn ghost" onClick={async () => {
            await post("/settings", { jira: { base: jBase.trim(), email: jEmail.trim(), api_token: jToken.trim(), default_jql: jJql.trim() } });
            toast("Jira connection saved");
          }}>Save connection</button>
          <button className="btn primary" disabled={busyImp} onClick={async () => {
            setBusyImp(true);
            const r = await post<{ imported?: number; error?: string }>("/import/jira", { jql: jJql.trim() });
            setBusyImp(false);
            toast(r.error ? r.error : `Imported ${r.imported} issues into the backlog`, 5000);
            refresh();
          }}>Import now</button>
        </div>
        <label style={{ marginTop: 16 }}>From a web page (agent derives a process from the page&apos;s content)</label>
        <div className="inline">
          <input placeholder="https://..." style={{ width: 380 }} value={impUrl} onChange={(e) => setImpUrl(e.target.value)} />
          <button className="btn primary" disabled={busyImp} onClick={async () => {
            if (!impUrl.trim()) return;
            setBusyImp(true);
            const r = await post<{ id?: string; error?: string }>("/import/url", { url: impUrl.trim() });
            setBusyImp(false);
            toast(r.error ? r.error : "Imported - the agent is proposing steps (see Processes)", 5000);
          }}>Import page</button>
        </div>
      </div>
      {me?.role === "owner" && (
        <div className="panel">
          <h3>Users</h3>
          {users === null && <div style={{ fontSize: 12.5, color: "var(--txt-tertiary)" }}>loading…</div>}
          {users && (
            <table>
              <thead><tr><th>user</th><th>role</th><th>device tokens</th><th /></tr></thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.name}>
                    <td><b>{u.name}</b>
                      <div style={{ fontSize: 10.5, color: "var(--txt-tertiary)" }}>{u.created}</div></td>
                    <td>
                      <select value={u.role}
                        onChange={(e) => userAct(`/users/${u.name}/role`, { role: e.target.value }, "Role updated")}>
                        {["owner", "operator", "client"].map((r) => <option key={r}>{r}</option>)}
                      </select>
                    </td>
                    <td>
                      {u.tokens.map((tk) => (
                        <div key={tk.token} style={{ display: "flex", gap: 6, alignItems: "center", margin: "2px 0" }}>
                          <span className="chip" title={tk.token}>{tk.label} · …{tk.token.slice(-6)}</span>
                          <button className="btn ghost" style={{ padding: "0 7px", fontSize: 11 }}
                            onClick={() => userAct(`/users/${u.name}/revoke`, { token: tk.token }, "Token revoked")}>revoke</button>
                        </div>
                      ))}
                      <button className="btn ghost" style={{ padding: "1px 8px", fontSize: 11, marginTop: 3 }}
                        onClick={() => {
                          const l = prompt("Token label (e.g. glasses, apk):", "device");
                          if (l !== null) userAct(`/users/${u.name}/tokens`, { label: l }, "");
                        }}>+ token</button>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <button className="btn ghost" style={{ fontSize: 11 }}
                        onClick={() => {
                          const p = prompt(`New password for ${u.name} (8+ chars):`);
                          if (p) userAct(`/users/${u.name}/password`, { password: p }, "Password set");
                        }}>reset pw</button>{" "}
                      <button className="btn ghost" style={{ fontSize: 11, color: "var(--danger)", borderColor: "var(--danger)" }}
                        onClick={() => {
                          if (confirm(`Delete user ${u.name}? Their sessions and tokens die immediately.`))
                            userAct(`/users/${u.name}/delete`, {}, "User deleted");
                        }}>delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
            <input placeholder="username" style={{ width: 130 }} value={uName} onChange={(e) => setUName(e.target.value)} />
            <input type="password" placeholder="password (8+)" style={{ width: 150 }} value={uPw} onChange={(e) => setUPw(e.target.value)} />
            <select value={uRole} onChange={(e) => setURole(e.target.value)}>
              <option>operator</option><option>client</option><option>owner</option>
            </select>
            <button className="btn primary" onClick={addUser}>Add user</button>
          </div>
          <h3 style={{ marginTop: 20 }}>Registration</h3>
          <div style={{ fontSize: 12, color: "var(--txt-tertiary)", marginBottom: 8 }}>
            Lets people create their own account on the sign-in screen. Share the invite code; new accounts get the default role.
          </div>
          <div className="inline">
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, margin: 0 }}>
              <input type="checkbox" checked={regOpen} onChange={(e) => setRegOpen(e.target.checked)} /> open (no code needed)
            </label>
            <input placeholder="invite code (empty = registration off)" style={{ width: 220 }}
              value={regCode} onChange={(e) => setRegCode(e.target.value)} />
            <button className="btn ghost" onClick={() => setRegCode(Math.random().toString(36).slice(2, 10))}>generate</button>
            <select value={regRole} onChange={(e) => setRegRole(e.target.value)}>
              <option>client</option><option>operator</option>
            </select>
            <button className="btn primary" onClick={saveReg}>Save registration</button>
          </div>
        </div>
      )}
    </div>
  );
}
