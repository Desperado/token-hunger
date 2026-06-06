/* costbench — Results: leaderboard ranked by cost per success.
 * Three views (table / chart / cards) selected via a Tweak.
 * Each target shows tokens used and can be expanded to its per-case classifications.
 */

const { useState: useResState } = React;

// Normalize backend values: cost/success is null when a target had no priced
// case, and Infinity (sent as costSuccessInf) when it was priced but passed
// nothing. Both should sort to the bottom — same for an unknown cost/run.
function normResult(r) {
  const cps = r.costSuccessInf ? Infinity : (r.costSuccess == null ? Infinity : r.costSuccess);
  const cpr = r.costRun == null ? Infinity : r.costRun;
  return { ...r, costSuccess: cps, costRun: cpr };
}

function rankResults(rows) {
  const norm = rows.map(normResult);
  const bySuccess = [...norm].sort((a, b) => a.costSuccess - b.costSuccess);
  const byRunOrder = [...norm].sort((a, b) => a.costRun - b.costRun).map((r) => r.id);
  return bySuccess.map((r, i) => {
    const runRank = byRunOrder.indexOf(r.id);
    return { ...r, successRank: i, runRank };
  });
}

function findFlip(ranked) {
  const cheapestCall = [...ranked].sort((a, b) => a.costRun - b.costRun)[0];
  if (!cheapestCall || cheapestCall.successRank === 0) return null;
  return { cheapestCall, winner: ranked[0] };
}

function Insight({ ranked }) {
  const flip = findFlip(ranked);
  if (!flip) return null;
  const { cheapestCall, winner } = flip;
  return (
    <div className="cb-insight">
      <b className="mono">{cheapestCall.id}</b> has the cheapest call at <span className="mono">{fmtCost(cheapestCall.costRun)}</span>,
      but it passes {fmtPct(cheapestCall.passRate)} of cases — so each correct answer costs <span className="mono">{fmtCost(cheapestCall.costSuccess)}</span>,
      ranking it <b>#{cheapestCall.successRank + 1}</b>. The actual leader is <b className="mono">{winner.id}</b> at <span className="mono">{fmtCost(winner.costSuccess)}</span> per correct answer.
    </div>
  );
}

function basisShort(b) {
  if (b === "vendor $/token") return "token";
  if (b === "amortized GPU (batch 1)") return "GPU";
  if (b === "declared per_request") return "per-req";
  return b;
}
function passColor(p) {
  if (p >= 0.96) return "var(--good)";
  if (p >= 0.85) return "var(--accent)";
  if (p >= 0.75) return "var(--warn)";
  return "var(--bad)";
}
function Tags({ r }) {
  return (
    <React.Fragment>
      {r.successRank === 0 && <span className="cb-tag best">cheapest / success</span>}
      {r.runRank + 2 <= r.successRank && <span className="cb-tag flip">looks cheap</span>}
    </React.Fragment>
  );
}

/* confusion summary over per-case classifications (positive = ESCALATE) */
function confusion(perCase) {
  let tp = 0, tn = 0, fp = 0, fn = 0;
  perCase.forEach((c) => {
    if (c.correct) { c.expect === "ESCALATE" ? tp++ : tn++; }
    else { c.predicted === "ESCALATE" ? fp++ : fn++; }
  });
  return { tp, tn, fp, fn };
}

/* expandable per-target classification detail */
function Classifications({ r }) {
  const c = confusion(r.perCase);
  const tokOpaque = r.tokensIn === null;
  // The escalation breakdown only makes sense for the triage-style task whose
  // positive class is ESCALATE; other tasks just show correct/wrong + tokens.
  const isTriage = r.perCase.some((cc) => String(cc.expect).toUpperCase() === "ESCALATE");
  return (
    <div className="cb-clsf">
      <div className="cb-clsf-summary">
        <span className="cb-clsf-stat"><b style={{ color: "var(--good)" }}>{r.passes}</b> correct</span>
        <span className="cb-clsf-stat"><b style={{ color: "var(--bad)" }}>{r.n - r.passes}</b> wrong</span>
        {isTriage && <span className="cb-clsf-sep" />}
        {isTriage && <span className="cb-clsf-stat">{c.fn} missed escalation{c.fn === 1 ? "" : "s"}</span>}
        {isTriage && <span className="cb-clsf-stat">{c.fp} over-escalation{c.fp === 1 ? "" : "s"}</span>}
        <span className="cb-clsf-sep" />
        <span className="cb-clsf-stat">tokens <b className="mono">{tokOpaque ? "—" : fmtInt(r.tokensIn)}</b> in · <b className="mono">{tokOpaque ? "—" : fmtInt(r.tokensOut)}</b> out</span>
      </div>
      <div className="cb-clsf-grid">
        {r.perCase.map((cc) => (
          <div className={"cb-clsf-item " + (cc.correct ? "ok" : "bad")} key={cc.i} title={cc.input}>
            <span className="mk">{cc.correct ? "✓" : "✗"}</span>
            <span className="ci">{cc.input}</span>
            <span className={"cb-clsf-pred " + (cc.predicted === "ESCALATE" ? "esc" : "res")}>{cc.predicted}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- table ---------- */
function ResultsTable({ ranked }) {
  const [open, setOpen] = useResState(() => new Set());
  const toggle = (id) => setOpen((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  return (
    <div className="cb-card" style={{ overflowX: "auto" }}>
      <table className="cb-table">
        <thead>
          <tr>
            <th className="l"></th>
            <th className="l">#</th>
            <th className="l">Target</th>
            <th>Pass</th>
            <th className="l">Basis</th>
            <th>Tokens (in/out)</th>
            <th>Cost / run</th>
            <th>Cost / success</th>
            <th>Latency</th>
          </tr>
        </thead>
        <tbody>
          {ranked.map((r) => {
            const isOpen = open.has(r.id);
            return (
              <React.Fragment key={r.id}>
                <tr className={(r.successRank === 0 ? "best " : "") + "clickable"} onClick={() => toggle(r.id)}>
                  <td className="l"><span className={"cb-rowchev " + (isOpen ? "open" : "")}><Icon name="chev" size={12} /></span></td>
                  <td className="l"><span className="cb-rank">{r.successRank + 1}</span></td>
                  <td className="l">
                    <span className="cb-tid">
                      <VendorMark vendor={r.vendor} />
                      <span className="mid">{r.id}</span>
                      <Tags r={r} />
                    </span>
                  </td>
                  <td>
                    <span className="cb-passbar">
                      <span className="track"><span className="fill" style={{ width: (r.passRate * 100) + "%", background: passColor(r.passRate) }} /></span>
                      <span style={{ color: "var(--text-2)", width: 34, display: "inline-block" }}>{fmtPct(r.passRate)}</span>
                    </span>
                  </td>
                  <td className="l"><span className="cb-tag basis" title={r.basis}>{basisShort(r.basis)}</span></td>
                  <td><span className="cb-mut">{fmtTokens(r.tokensIn)}<span style={{ opacity: 0.5 }}> / </span>{fmtTokens(r.tokensOut)}</span></td>
                  <td><span className="cb-mut">{fmtCost(r.costRun)}</span></td>
                  <td><span className={"cb-cps " + (r.successRank === 0 ? "win" : "")}>{fmtCost(r.costSuccess)}</span></td>
                  <td><span className="cb-mut">{fmtLat(r.latency)}</span></td>
                </tr>
                {isOpen && (
                  <tr className="cb-detailrow">
                    <td colSpan={9}><Classifications r={r} /></td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- chart (log scale; inner = cost/run, tail = failure penalty) ---------- */
function ResultsChart({ ranked }) {
  const lo = Math.min(...ranked.map((r) => r.costRun));
  const hi = Math.max(...ranked.map((r) => r.costSuccess));
  const lLo = Math.log(lo), lHi = Math.log(hi);
  const scale = (v) => {
    if (v === Infinity) return 100;
    const w = ((Math.log(v) - lLo) / (lHi - lLo)) * 100;
    return Math.max(4, Math.min(100, w));
  };
  return (
    <div className="cb-card">
      <div className="cb-chart-legend">
        <span><span className="sw" style={{ background: "var(--accent)" }} />cost / run</span>
        <span><span className="sw" style={{ background: "var(--accent-soft)" }} />penalty from failed runs</span>
        <span style={{ color: "var(--text-3)" }}>· log scale</span>
      </div>
      <div className="cb-chart">
        {ranked.map((r) => (
          <div className="cb-chart-row" key={r.id}>
            <span className="name" title={r.id}>{r.id}</span>
            <div className="barwrap">
              <div className="bar success" style={{ width: scale(r.costSuccess) + "%" }} />
              <div className="bar run" style={{ width: scale(r.costRun) + "%", background: r.successRank === 0 ? "var(--good)" : "var(--accent)" }} />
            </div>
            <span className="val">
              <span style={{ color: r.successRank === 0 ? "var(--good)" : "var(--text)" }}>{fmtCost(r.costSuccess)}</span>
              <span className="tok">{fmtTokens(r.tokensIn)}/{fmtTokens(r.tokensOut)} tok</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- cards ---------- */
function ResultsCards({ ranked }) {
  return (
    <div className="cb-cardgrid">
      {ranked.map((r) => (
        <div className={"cb-rcard " + (r.successRank === 0 ? "best" : "")} key={r.id}>
          <div className="corner"><VendorMark vendor={r.vendor} size={22} /></div>
          <div className="rid">{r.id}</div>
          <div className="rvendor">{r.vendor} · {r.basis}</div>
          <div className={"big " + (r.successRank === 0 ? "win" : "")}>{fmtCost(r.costSuccess)}</div>
          <div className="biglab">per correct answer · #{r.successRank + 1}</div>
          <div className="cb-rcard-foot">
            <div><div className="k">Pass</div><div className="v" style={{ color: passColor(r.passRate) }}>{fmtPct(r.passRate)}</div></div>
            <div><div className="k">Cost / run</div><div className="v">{fmtCost(r.costRun)}</div></div>
            <div><div className="k">Tokens</div><div className="v">{fmtTokens(r.tokensIn)}/{fmtTokens(r.tokensOut)}</div></div>
            <div><div className="k">Latency</div><div className="v">{fmtLat(r.latency)}</div></div>
          </div>
        </div>
      ))}
    </div>
  );
}

function Results({ rows, view, meta }) {
  const ranked = rankResults(rows);
  const totalIn = ranked.reduce((a, r) => a + (r.tokensIn || 0), 0);
  const totalOut = ranked.reduce((a, r) => a + (r.tokensOut || 0), 0);
  return (
    <div className="cb-rise">
      <div className="cb-results-head">
        <div>
          <h2>Results</h2>
          <div className="sub">Ranked by cost per success · total cost ÷ correct answers · {fmtInt(totalIn)} input / {fmtInt(totalOut)} output tokens measured</div>
        </div>
      </div>
      <Insight ranked={ranked} />
      {view === "table" && <ResultsTable ranked={ranked} />}
      {view === "chart" && <ResultsChart ranked={ranked} />}
      {view === "cards" && <ResultsCards ranked={ranked} />}
      <p style={{ fontSize: 12, color: "var(--text-3)", marginTop: 16, lineHeight: 1.5 }}>
        {view === "table" ? "Click any target to see its per-case classifications. " : ""}
        Tokens are provider-reported. Config <span style={{ fontFamily: "var(--mono)" }}>{meta.configFingerprint}</span> · pricing <span style={{ fontFamily: "var(--mono)" }}>{meta.pricingFingerprint}</span> · endpoint cost is declared, tokens unobservable.
      </p>
    </div>
  );
}

Object.assign(window, { Results });
