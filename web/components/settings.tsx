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

  useEffect(() => {
    if (s && !loaded) {
      setRepo(s.default_repo ?? ""); setValue(String(s.value_per_card));
      setWip(String(s.capacity.wip_limit)); setBudget(String(s.capacity.touch_budget_day));
      setT1(String(s.capacity.tariff.steer)); setT2(String(s.capacity.tariff.review)); setT3(String(s.capacity.tariff.bounce));
      setRegOpen(!!s.registration?.open); setRegCode(s.registration?.invite_code ?? "");
      setRegRole(s.registration?.default_role ?? "client");
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
    if (r.token) prompt("Device token — copy it now:", r.token);
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
