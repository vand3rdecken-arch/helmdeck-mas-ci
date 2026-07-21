"use client";
import { useBoard } from "@/lib/store";

export default function DashView() {
  const { met } = useBoard();
  if (!met) return <div className="panel">no access</div>;
  const cur = met.settings?.currency === "USD" ? "$" : "€";
  const [y0, y1] = met.yield_first_pass;
  const [a0, a1] = met.automation;
  const T = met.totals, c = met.capacity;
  const pct = Math.min(100, Math.round(100 * c.touches_today / (c.touch_budget_day || 1)));
  let maxA = 0.01, maxH = 1;
  met.cards.forEach((x) => { if (x.ai_cost > maxA) maxA = x.ai_cost; if (x.touches > maxH) maxH = x.touches; });
  // tile/panel composition is workspace config (settings.dashboard) - the
  // owner rearranges it in Settings or by telling the copilot.
  const TILE: Record<string, [string, string]> = {
    value_delivered: [cur + T.value_delivered, "value delivered"],
    ai_spend: ["$" + T.ai_spend.toFixed(2), "AI spend"],
    margin: [cur + T.margin, "margin (value − AI)"],
    yield: [y1 ? Math.round(100 * y0 / y1) + "%" : "—", `first-pass yield (${y0}/${y1})`],
    automation: [a1 ? Math.round(100 * a0 / a1) + "%" : "—", `automation rate (${a0}/${a1} auto)`],
    leverage: [cur + T.leverage_per_touch, "value per touch unit"],
  };
  const tileKeys = (met.settings?.dashboard?.tiles ?? Object.keys(TILE)).filter((k) => TILE[k]);
  const panels = met.settings?.dashboard?.panels ?? ["capacity", "gates", "work"];
  const gmax = met.gate_failures[0]?.[1] ?? 1;
  const actors = Object.entries(c.actors ?? {});
  return (
    <>
      {tileKeys.length > 0 && (
        <div id="tiles">
          {tileKeys.map((k) => (
            <div key={k} className="tile"><div className="v">{TILE[k][0]}</div><div className="l">{TILE[k][1]}</div></div>
          ))}
        </div>
      )}
      {panels.includes("capacity") && <div className="panel">
        <h3>Capacity — take more work, or automate?</h3>
        <div style={{ fontSize: 12.5, color: "var(--txt-secondary)" }}>
          today {c.touches_today}/{c.touch_budget_day} touch units ({pct}%) · WIP {c.wip}/{c.wip_limit} · headroom{" "}
          <b style={{ color: "var(--ok)" }}>{c.headroom} cards</b>
        </div>
        <div className="meter"><i style={{ width: `${pct}%` }} /></div>
        {actors.length > 1 && (
          <div style={{ fontSize: 12, color: "var(--txt-secondary)", margin: "4px 0" }}>
            {actors.map(([a, n]) => `${a}: ${n}t`).join(" · ")}
          </div>
        )}
        <div style={{ fontSize: 11.5, color: "var(--txt-tertiary)" }}>
          {pct < 80 && c.headroom > 0
            ? "Below capacity → intake more: marginal cost of one more card is tokens only."
            : "At capacity → automate: fixing the top gate failure below frees the most headroom."}
        </div>
      </div>}
      {panels.includes("gates") && <div className="panel">
        <h3>Gate failures — what to fix in the harness next</h3>
        {!met.gate_failures.length && <div style={{ color: "var(--txt-tertiary)", fontSize: 12.5 }}>none recorded yet</div>}
        {met.gate_failures.map(([k, n]) => (
          <div key={k} className="hbar">
            <div className="lbl" title={k}>{k}</div>
            <div className="trk"><i style={{ width: `${Math.max(3, Math.round(100 * n / gmax))}%` }} /></div>
            <div className="n">{n}</div>
          </div>
        ))}
      </div>}
      {panels.includes("work") && <div className="panel">
        <h3>Work done — <span style={{ color: "var(--ai)" }}>■</span> AI ($) · <span style={{ color: "var(--human)" }}>■</span> human (touch units)</h3>
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr><th>card</th><th>lane</th><th>model</th><th className="num">tok in/out</th>
                <th className="num">AI $</th><th className="num">touches</th><th>split</th>
                <th className="num">value</th><th className="num">margin</th><th>mode</th></tr>
            </thead>
            <tbody>
              {met.cards.map((x) => (
                <tr key={x.id}>
                  <td>{x.task}</td><td>{x.lane}</td>
                  <td>{(x.models[0] ?? "—").replace("claude-", "")}</td>
                  <td className="num">{x.tokens_in}/{x.tokens_out}</td>
                  <td className="num">{x.ai_cost.toFixed(2)}</td>
                  <td className="num">{x.touches}</td>
                  <td>
                    <span className="msplit" title={`AI $${x.ai_cost.toFixed(2)} vs ${x.touches} touch units`}>
                      <i style={{ background: "var(--ai)", width: `${Math.max(2, Math.round(100 * x.ai_cost / maxA))}%` }} />
                      <i style={{ background: "var(--human)", width: `${Math.max(2, Math.round(100 * x.touches / maxH))}%`, marginTop: 2 }} />
                    </span>
                  </td>
                  <td className="num">{cur}{x.value}</td>
                  <td className="num">{cur}{(x.value - x.ai_cost).toFixed(2)}</td>
                  <td>{x.mode ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>}
    </>
  );
}
