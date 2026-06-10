/* costbench — input sections: Hero prompt, Targets, Cases, RunBar, Connectors drawer. */

const { useState } = React;

/* ---------- Hero prompt: the task the models are graded on ---------- */
function Hero({ task, setTask, examples, exampleId, onPickExample }) {
  // The local web API intentionally excludes `code`: loading a Python callable
  // is appropriate for a trusted YAML config, not an in-memory browser request.
  const checks = ["exact", "contains", "regex", "numeric"];
  const checkKind = typeof task.check === "object" ? task.check.type : task.check;
  const selected = examples.find((ex) => ex.id === exampleId);
  const [level, setLevel] = useState(selected ? selected.level || 1 : 1);
  const visibleExamples = examples.filter((ex) => (ex.level || 1) === level);

  React.useEffect(() => {
    if (selected && (selected.level || 1) !== level) setLevel(selected.level || 1);
  }, [exampleId]);

  return (
    <div>
      <div className="cb-hero">
        <h1>Don't pay frontier prices for tasks a smaller model nails.</h1>
        <p>TokenHunger grades every model on the same cases and ranks them by cost per <em>correct</em> answer, so failures count against apparently cheap calls. Compare pass rate and cost per success, then choose the model that fits your quality requirements.</p>
      </div>

      <div className="cb-promptcard">
        {examples && examples.length > 0 && (
          <div className="cb-example-row">
            <span className="lab">Example task</span>
            <div className="cb-level-tabs" aria-label="Example difficulty">
              {[1, 2, 3].map((n) => (
                <button
                  key={n}
                  className={level === n ? "on" : ""}
                  onClick={() => setLevel(n)}
                >
                  Level {n}
                </button>
              ))}
            </div>
            <div className="cb-seg cb-seg-wrap">
              {visibleExamples.map((ex) => (
                <button key={ex.id} className={exampleId === ex.id ? "on" : ""} onClick={() => onPickExample(ex.id)}>{ex.name}</button>
              ))}
            </div>
            <span className="cb-level-note">
              {selected && selected.authoring
                ? "Opus 4.6 authored · human reviewed"
                : level === 1
                  ? "Single-step fundamentals"
                  : level === 2
                    ? "Multi-rule production scenarios"
                    : "Ambiguous, noisy frontier reasoning"}
            </span>
          </div>
        )}
        <div className="cb-field">
          <div className="cb-field-head"><span className="lab">System</span></div>
          <textarea
            rows={3}
            value={task.system}
            onChange={(e) => setTask({ ...task, system: e.target.value })}
            placeholder="Describe the job. The same instruction is sent to every target…"
          />
        </div>
        <div className="cb-field">
          <div className="cb-field-head">
            <span className="lab">Prompt template</span>
            <span className="cb-token">{"{input}"}</span>
            <span style={{ fontSize: 12, color: "var(--text-3)" }}>← filled from each case</span>
          </div>
          <input
            className="cb-line"
            value={task.promptTemplate}
            onChange={(e) => setTask({ ...task, promptTemplate: e.target.value })}
          />
        </div>
        <div className="cb-prompt-footer">
          <div className="cb-check-group">
            <span className="lab">Check</span>
            <div className="cb-seg">
              {checks.map((c) => (
                <button key={c} className={checkKind === c ? "on" : ""} onClick={() => setTask({ ...task, check: c })}>{c}</button>
              ))}
            </div>
          </div>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 12.5, color: "var(--text-3)" }}>Same cases · same check · every target</span>
        </div>
      </div>
    </div>
  );
}

/* ---------- Targets: compact provider-grouped tree ---------- */
function TCheck({ state, onClick }) {
  // state: "all" | "some" | "none"
  return (
    <span className={"cb-check " + state} onClick={onClick} role="checkbox" aria-checked={state === "all"}>
      {state === "all" && <Icon name="check" size={12} />}
      {state === "some" && <span className="dash" />}
    </span>
  );
}

function TargetsTree({ rows, removed, onToggle, onToggleProvider, onSelectAll, onClearAll, onAdd }) {
  const groups = [];
  const map = {};
  rows.forEach((r) => {
    if (!map[r.vendor]) { map[r.vendor] = { vendor: r.vendor, items: [] }; groups.push(map[r.vendor]); }
    map[r.vendor].items.push(r);
  });
  const [open, setOpen] = useState(() => new Set());
  const active = rows.filter((r) => !removed.has(r.id)).length;

  const toggleOpen = (v) => setOpen((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; });

  const groupState = (g) => {
    const on = g.items.filter((r) => !removed.has(r.id)).length;
    return on === 0 ? "none" : on === g.items.length ? "all" : "some";
  };

  return (
    <div>
      <div className="cb-section-label">
        Targets <span className="count">· {active} of {rows.length} selected across {groups.length} providers</span>
        <span style={{ flex: 1 }} />
        <span className="cb-treelink" onClick={onSelectAll}>All</span>
        <span className="cb-treelink" onClick={onClearAll}>None</span>
      </div>
      <div className="cb-card cb-tree">
        {groups.map((g) => {
          const st = groupState(g);
          const isOpen = open.has(g.vendor);
          const on = g.items.filter((r) => !removed.has(r.id)).length;
          return (
            <div className="cb-prov-block" key={g.vendor}>
              <div className="cb-prov" onClick={() => toggleOpen(g.vendor)}>
                <span className={"chev " + (isOpen ? "open" : "")}><Icon name="chev" size={13} /></span>
                <VendorMark vendor={g.vendor} size={20} />
                <span className="pname">{g.vendor}</span>
                <span className="pcount">{g.items.length}</span>
                <span style={{ flex: 1 }} />
                <span className="pactive">{on}/{g.items.length}</span>
                <TCheck state={st} onClick={(e) => { e.stopPropagation(); onToggleProvider(g.items); }} />
              </div>
              {isOpen && (
                <div className="cb-prov-kids">
                  {g.items.map((r) => {
                    const onState = !removed.has(r.id);
                    return (
                      <div className={"cb-model " + (onState ? "" : "off")} key={r.id} onClick={() => onToggle(r.id)}>
                        <span className="mid">{r.id}</span>
                        <span style={{ flex: 1 }} />
                        <span className="price">{priceLabel(r)}</span>
                        <TCheck state={onState ? "all" : "none"} onClick={(e) => { e.stopPropagation(); onToggle(r.id); }} />
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
        <div className="cb-prov add" onClick={onAdd}>
          <span className="chev" style={{ visibility: "hidden" }}><Icon name="chev" size={13} /></span>
          <span className="addmark"><Icon name="plus" size={13} /></span>
          <span className="pname" style={{ color: "var(--text-2)", fontWeight: 500 }}>Add provider or endpoint</span>
        </div>
      </div>
    </div>
  );
}

/* Color an expected-label pill: red-ish for "negative/escalate" labels, green-ish
 * for "positive/resolve" labels, neutral for everything else (numbers, names). */
const NEG_LABELS = new Set(["ESCALATE", "NEGATIVE", "FAIL", "FALSE", "NO"]);
const POS_LABELS = new Set(["RESOLVE", "POSITIVE", "PASS", "TRUE", "YES"]);
function pillClass(expect) {
  const v = String(expect).trim().toUpperCase();
  if (NEG_LABELS.has(v)) return "esc";
  if (POS_LABELS.has(v)) return "res";
  return "gen";
}

/* Distinct expected labels with counts, or null when there are too many to be a
 * meaningful class split (e.g. math answers are all unique). */
function classSplit(cases) {
  const counts = new Map();
  cases.forEach((c) => { const k = String(c.expect); counts.set(k, (counts.get(k) || 0) + 1); });
  if (counts.size === 0 || counts.size > 6) return null;
  return [...counts.entries()].map(([label, count]) => ({ label, count, cls: pillClass(label) }));
}

function CaseList({ cases }) {
  return (
    <div className="cb-caselist">
      {cases.map((c, i) => (
        <div className="cb-caserow" key={i}>
          <span className="num">{String(i + 1).padStart(2, "0")}</span>
          <span className="inp">{c.input}</span>
          <span className={"cb-pill " + pillClass(c.expect)}>{String(c.expect)}</span>
        </div>
      ))}
    </div>
  );
}

/* ---------- Cases (with two-click LLM suggestion: suggest → use/redo/discard) ---------- */
function Cases({ cases, sourceLabel, onConnect, suggesting, suggestion, suggestErr, onSuggest, onConfirm, onRegenerate, onDiscard, demo }) {
  const [open, setOpen] = useState(false);
  const classes = classSplit(cases);
  const summary = classes
    ? classes.map((c) => `${c.count} ${c.label.toLowerCase()}`).join(" / ")
    : `${cases.length} distinct answers`;
  const reviewing = !!suggestion;

  return (
    <div>
      <div className="cb-section-label">Cases</div>
      <div className="cb-card">
        <div className="cb-cases-head" onClick={() => { if (!reviewing) setOpen(!open); }}>
          <span className="ttl">{cases.length} cases</span>
          <span className="meta">· {summary} · from {sourceLabel}</span>
          <div className="cb-cases-actions" onClick={(e) => e.stopPropagation()}>
            {!demo && (
              <button className="cb-connbtn ghost" disabled={suggesting} onClick={onSuggest}>
                {suggesting && !reviewing ? "Suggesting…" : "✨ Suggest cases"}
              </button>
            )}
            <button className="cb-connbtn ghost" onClick={onConnect}>Connect dataset</button>
          </div>
          {!reviewing && <span className={"chev " + (open ? "open" : "")}><Icon name="chev" /></span>}
        </div>

        {suggestErr && <div className="cb-runerr" style={{ margin: "0 16px 14px" }}>{suggestErr}</div>}

        {reviewing ? (
          <React.Fragment>
            <div className="cb-suggest-bar">
              <span>Suggested <b>{suggestion.cases.length}</b> cases
                <span style={{ color: "var(--text-3)" }}> · via {suggestion.model} · review before using</span>
              </span>
              <span style={{ flex: 1 }} />
              <button className="cb-connbtn install" onClick={onConfirm}>Use these {suggestion.cases.length}</button>
              <button className="cb-connbtn ghost" disabled={suggesting} onClick={onRegenerate}>{suggesting ? "Regenerating…" : "Regenerate"}</button>
              <button className="cb-connbtn ghost" onClick={onDiscard}>Discard</button>
            </div>
            <CaseList cases={suggestion.cases} />
          </React.Fragment>
        ) : (open && <CaseList cases={cases} />)}
      </div>
    </div>
  );
}

/* ---------- Run bar + estimate detail (tokens & classifications) ---------- */
function fmtDuration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return "calculating…";
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m ${String(secs).padStart(2, "0")}s`;
}

function RunProgress({ progress }) {
  if (!progress) return null;
  const pct = Math.max(0, Math.min(100, progress.percent || 0));
  const done = progress.completed || 0;
  const total = progress.total || 0;
  const targetNumber = progress.targetIndex == null ? null : progress.targetIndex + 1;
  return (
    <div className="cb-progress" role="status" aria-live="polite">
      <div className="cb-progress-head">
        <span className="state">{pct >= 100 ? "Benchmark complete" : "Benchmark running"}</span>
        <span className="mono">{done} / {total} calls</span>
        <span className="pct mono">{Math.round(pct)}%</span>
      </div>
      <div
        className="cb-progress-track"
        role="progressbar"
        aria-valuemin="0"
        aria-valuemax={total}
        aria-valuenow={done}
      >
        <span style={{ width: `${pct}%` }} />
      </div>
      <div className="cb-progress-detail">
        {progress.target
          ? <span>Target {targetNumber}/{progress.targetCount}: <b className="mono">{progress.target}</b> · {progress.targetCompleted}/{progress.targetTotal} cases</span>
          : <span>Preparing {total} model calls with concurrency {progress.concurrency}…</span>}
        <span className="stats">
          {progress.passes != null && <React.Fragment><b>{progress.passes}</b> correct · <b>{progress.errors || 0}</b> errors · </React.Fragment>}
          elapsed {fmtDuration(progress.elapsedSec || 0)}
          {pct < 100 && <> · ETA {fmtDuration(progress.etaSec)}</>}
        </span>
      </div>
    </div>
  );
}

function RunBar({ nTargets, nCases, est, classes, check, outCeilPerCase, outLowPerCase, concurrency, onConcurrency, onRun, running, hasRun, progress, demo }) {
  const [open, setOpen] = useState(false);
  const inK = est.inTok, outLow = est.outLow, outHigh = est.outHigh;
  const checkKind = typeof check === "object" ? check.type : check;
  const par = concurrency || 12;
  return (
    <div className="cb-estwrap">
      <div className="cb-runbar">
        <button className="cb-run" onClick={onRun} disabled={running || demo}
          title={demo ? "Running is disabled in the read-only demo" : undefined}>
          <Icon name="play" size={15} />
          {demo ? "Run disabled in demo" : running ? "Running…" : hasRun ? "Run again" : "Run benchmark"}
        </button>
        <label className="cb-parallel" title="How many model calls run in parallel. Higher finishes the same run faster, up to each provider's rate limit."
          style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--text-2)" }}>
          <Icon name="spark" size={13} /> Parallelism
          <input type="number" min={1} max={32} value={par} disabled={running}
            onChange={(e) => onConcurrency(Math.max(1, Math.min(32, Number(e.target.value) || 1)))}
            style={{ width: 52, padding: "5px 7px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--bg-2)", color: "var(--text-1)", fontFamily: "monospace" }} />
        </label>
        <div className="cb-estchip">
          <span className="lab">Est. cost</span>
          <span className="amt mono">{fmtCost(est.low)}<span className="dash">–</span>{fmtCost(est.high)}</span>
          <span className="div" />
          <span className="meta">
            <span className="mono">~{fmtTokens(inK)}</span> in · <span className="mono">≤{fmtTokens(outHigh)}</span> out · {nCases} cases × {nTargets} targets
          </span>
        </div>
        <span style={{ flex: 1 }} />
        <button className={"cb-disclosure " + (open ? "open" : "")} onClick={() => setOpen(!open)}>
          {open ? "Hide" : "Estimate detail"} <span className="chev"><Icon name="chev" size={12} /></span>
        </button>
      </div>
      {running && <RunProgress progress={progress} />}

      {open && (
        <div className="cb-estpanel">
          <div className="cb-estnote">
            Input is <b>tokenized</b> from the task + cases (known). Output is a worst-case <b>ceiling</b> of {outCeilPerCase} tok/case
            {"  "}(calibrated p50 ≈ {outLowPerCase}). Estimates round up and are never blended with verified run costs.
          </div>
          <div className="cb-esttable">
            <div className="cb-estrow head">
              <span className="t">Target</span>
              <span className="n">Input tok</span>
              <span className="n">Output ≤</span>
              <span className="n">Est. cost</span>
            </div>
            {est.rows.map((e) => (
              <div className="cb-estrow" key={e.id}>
                <span className="t"><VendorMark vendor={e.vendor} size={16} /> <span className="mid">{e.id}</span></span>
                <span className="n mono">{e.opaque ? "—" : fmtInt(e.inTok)}</span>
                <span className="n mono">{e.opaque ? "—" : fmtInt(e.outHighTok)}</span>
                <span className="n mono">{e.costLow === e.costHigh ? fmtCost(e.costHigh) : fmtCost(e.costLow) + "–" + fmtCost(e.costHigh)}</span>
              </div>
            ))}
          </div>
          <div className="cb-estclass">
            Grading <b>{nCases}</b> cases with <span className="cb-tag basis">{checkKind}</span> check
            {classes
              ? <React.Fragment>{" · expected classes:"}{classes.map((c) => (
                  <span key={c.label} className={"cb-pill " + c.cls} style={{ marginLeft: 6 }}>{c.label} {c.count}</span>
                ))}</React.Fragment>
              : <span style={{ color: "var(--text-3)" }}> · free-form answers (no fixed classes)</span>}
            {est.opaque > 0 && <span style={{ color: "var(--text-3)", marginLeft: 10 }}>· {est.opaque} target with opaque tokens</span>}
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------- Connectors drawer (MCP + dataset connectors) ---------- */
function ConnectorsDrawer({ open, onClose, mcp, connectors, onInstall }) {
  return (
    <React.Fragment>
      <div className={"cb-overlay " + (open ? "open" : "")} onClick={onClose} />
      <aside className={"cb-drawer " + (open ? "open" : "")} aria-hidden={!open}>
        <div className="cb-drawer-head">
          <Icon name="plug" size={19} />
          <h3>Connectors</h3>
          <button className="close" onClick={onClose}><Icon name="close" size={15} /></button>
        </div>
        <div className="cb-drawer-body">
          <div className="cb-drawer-sub">MCP — usage &amp; traces</div>
          {mcp.map((s) => (
            <div className="cb-conn" key={s.id}>
              <div className="glyph">{s.glyph}</div>
              <div className="info">
                <div className="nm">{s.name}</div>
                <div className="dt">{s.detail}</div>
              </div>
              <span className="cb-connbtn on"><span className="cb-statusdot on" />Connected</span>
            </div>
          ))}

          <div className="cb-drawer-sub mt">Data connectors — pull cases &amp; tasks</div>
          {connectors.map((c) => (
            <div className="cb-conn" key={c.id}>
              <div className="glyph">{c.name[0]}</div>
              <div className="info">
                <div className="nm">{c.name}</div>
                <div className="dt">{c.detail}</div>
                {c.status === "installed" && c.cases > 0 && (
                  <div className="extra">{c.cases} cases imported</div>
                )}
              </div>
              {c.status === "installed" ? (
                <span className="cb-connbtn on"><Icon name="check" size={13} /></span>
              ) : (
                <button className="cb-connbtn install" onClick={() => onInstall(c.id)}>Install</button>
              )}
            </div>
          ))}
          <p style={{ fontSize: 12, color: "var(--text-3)", lineHeight: 1.5, marginTop: 20 }}>
            Connectors dump real datasets and labeled tasks into your case set. MCP servers read live token usage from Claude or Codex so estimates calibrate against what you actually spend.
          </p>
        </div>
      </aside>
    </React.Fragment>
  );
}

Object.assign(window, { Hero, TargetsTree, Cases, RunBar, ConnectorsDrawer });
