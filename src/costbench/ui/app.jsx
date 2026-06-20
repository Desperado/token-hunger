/* costbench — main App: layout, theme, tweaks, and the live run flow.
 *
 * All data is fetched from the backend (see api.js / server.py):
 *   - bootstrap on mount: task, cases, the live pricing models, fingerprints;
 *   - estimate re-runs (debounced) whenever the task or selected targets change;
 *   - run executes the real benchmark and renders the leaderboard.
 */

const { useState, useMemo, useEffect, useRef } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "dark": true,
  "resultsView": "table",
  "accent": "#ff6a1a",
  "outputTokens": 3,
  "concurrency": 12
}/*EDITMODE-END*/;

const ACCENTS = {
  "#ff6a1a": { accent: "#ff6a1a", soft: "rgba(255,106,26,0.14)", text: "#ff6a1a", darkAccent: "#ff6a1a", darkText: "#ff6a1a", darkSoft: "rgba(255,106,26,0.16)" },
  "#34d6a0": { accent: "#16b582", soft: "rgba(22,181,130,0.14)", text: "#16b582", darkAccent: "#34d6a0", darkText: "#34d6a0", darkSoft: "rgba(52,214,160,0.16)" },
  "#f4f1ec": { accent: "#9a8f86", soft: "rgba(154,143,134,0.14)", text: "#9a8f86", darkAccent: "#f4f1ec", darkText: "#f4f1ec", darkSoft: "rgba(244,241,236,0.12)" },
};

const FLAME_MARK = (
  <svg className="th-flame" width="22" height="22" viewBox="0 0 48 48" fill="none" aria-hidden="true">
    <circle cx="24" cy="24" r="20.5" stroke="#ff6a1a" strokeOpacity="0.42" strokeWidth="2.4" />
    <g transform="translate(11.6 10.4) scale(1.06)">
      <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z" fill="#ff6a1a" />
      <path d="M12 13.1c-1.3 1.6-1.9 2.8-1.9 4.1a1.9 1.9 0 0 0 3.8 0c0-1.7-1.1-2.7-1.9-4.1z" fill="#34d6a0" />
    </g>
  </svg>
);

function useThemeEffect(t, theme) {
  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", theme);
    const a = ACCENTS[t.accent] || ACCENTS["#ff6a1a"];
    if (t.dark) {
      root.style.setProperty("--accent", a.darkAccent);
      root.style.setProperty("--accent-text", a.darkText);
      root.style.setProperty("--accent-soft", a.darkSoft);
    } else {
      root.style.setProperty("--accent", a.accent);
      root.style.setProperty("--accent-text", a.text);
      root.style.setProperty("--accent-soft", a.soft);
    }
  }, [theme, t.accent, t.dark]);
}

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const theme = t.dark ? "dark" : "light";
  useThemeEffect(t, theme);

  // ---- bootstrap (task, cases, models, connectors, meta) ----
  const [boot, setBoot] = useState(null);
  const [bootErr, setBootErr] = useState(null);

  const [task, setTask] = useState(null);
  const [cases, setCases] = useState([]);
  const [models, setModels] = useState([]);
  const [connectors, setConnectors] = useState([]);
  const [examples, setExamples] = useState([]);
  const [exampleId, setExampleId] = useState(null);
  const [configFingerprint, setConfigFingerprint] = useState(null);
  const [removed, setRemoved] = useState(() => new Set());
  const [drawer, setDrawer] = useState(false);

  useEffect(() => {
    CostbenchAPI.bootstrap()
      .then((d) => {
        setBoot(d);
        setTask(d.task);
        setCases(d.cases);
        setModels(d.models);
        setConnectors(d.connectors || []);
        setExamples(d.examples || []);
        setExampleId(d.examples && d.examples[0] ? d.examples[0].id : null);
        setConfigFingerprint(
          d.examples && d.examples[0] ? d.examples[0].configFingerprint || null : null
        );
      })
      .catch((e) => setBootErr(e.message || String(e)));
  }, []);

  // Pick a built-in example task: swap the prompt, cases, and check together;
  // any prior leaderboard is stale, so clear it.
  const pickExample = (id) => {
    const ex = examples.find((e) => e.id === id);
    if (!ex) return;
    setTask(ex.task);
    setCases(ex.cases);
    setExampleId(id);
    setConfigFingerprint(ex.configFingerprint || null);
    setResults(null);
  };
  // A manual prompt edit means it's no longer one of the presets.
  const editTask = (nt) => {
    setTask(nt);
    setExampleId(null);
    setConfigFingerprint(null);
  };

  // ---- target selection ----
  const activeRows = useMemo(() => models.filter((r) => !removed.has(r.id)), [models, removed]);
  const activeIds = useMemo(() => activeRows.map((r) => r.id), [activeRows]);

  const toggleTarget = (id) => setRemoved((prev) => {
    const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n;
  });
  const toggleProvider = (items) => setRemoved((prev) => {
    const n = new Set(prev);
    const allOn = items.every((r) => !n.has(r.id));
    if (allOn) items.forEach((r) => n.add(r.id)); else items.forEach((r) => n.delete(r.id));
    return n;
  });
  const selectAll = () => setRemoved(new Set());
  const clearAll = () => setRemoved(new Set(models.map((r) => r.id)));
  // Narrow the active targets to exactly `ids` (used by the Cheapest-to-try panel).
  const selectModels = (ids) => {
    const keep = new Set(ids);
    setRemoved(new Set(models.filter((r) => !keep.has(r.id)).map((r) => r.id)));
  };

  // ---- estimate (debounced; keyless, offline on the server) ----
  const [est, setEst] = useState(null);
  const [estErr, setEstErr] = useState(null);
  const estSeq = useRef(0);

  useEffect(() => {
    if (!task || activeIds.length === 0) { setEst(null); return; }
    const seq = ++estSeq.current;
    const handle = setTimeout(() => {
      CostbenchAPI.estimate({
        task,
        targets: activeIds,
        cases,
        outputTokens: t.outputTokens,
        configFingerprint,
      })
        .then((d) => {
          if (seq !== estSeq.current) return; // a newer request superseded this
          let low = 0, high = 0, inTok = 0, outLow = 0, outHigh = 0, opaque = 0;
          d.rows.forEach((e) => {
            low += e.costLow || 0; high += e.costHigh || 0;
            if (e.opaque) { opaque += 1; return; }
            inTok += e.inTok || 0; outLow += e.outLowTok || 0; outHigh += e.outHighTok || 0;
          });
          setEst({ low, high, inTok, outLow, outHigh, opaque, rows: d.rows });
          setEstErr(null);
        })
        .catch((e) => { if (seq === estSeq.current) setEstErr(e.message || String(e)); });
    }, 300);
    return () => clearTimeout(handle);
  }, [task, activeIds, cases, t.outputTokens, configFingerprint]);

  // ---- run ----
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState(null);
  const [runMeta, setRunMeta] = useState(null);
  const [runErr, setRunErr] = useState(null);
  const [runProgress, setRunProgress] = useState(null);

  const run = () => {
    if (running || activeIds.length === 0) return;
    if (boot && boot.demo) return; // read-only demo: running is disabled server-side too
    const payload = { task, targets: activeIds, cases, concurrency: t.concurrency };
    setRunning(true); setRunErr(null); setResults(null); setRunProgress(null);
    CostbenchAPI.run(payload, (event) => {
      if (event.type === "start" || event.type === "progress") {
        setRunProgress(event);
      } else if (event.type === "result") {
        setResults(event.data.rows);
        setRunMeta(event.data.meta);
        setRunProgress((prev) => ({ ...prev, ...event, percent: 100 }));
      }
    })
      .catch((e) => setRunErr(e.message || String(e)))
      .finally(() => setRunning(false));
  };

  const installConnector = () => {}; // connectors are pulled via `costbench pull`; drawer is informational

  // ---- case suggestion (two-click: suggest → use / regenerate / discard) ----
  const [suggesting, setSuggesting] = useState(false);
  const [suggestion, setSuggestion] = useState(null); // { cases, model }
  const [suggestErr, setSuggestErr] = useState(null);

  const doSuggest = () => {
    if (suggesting) return;
    if (boot && boot.demo) return; // case suggestion calls a model; disabled in demo
    setSuggesting(true); setSuggestErr(null);
    CostbenchAPI.suggestCases({ task, n: Math.max(8, Math.min(cases.length || 10, 16)) })
      .then((d) => setSuggestion(d))
      .catch((e) => setSuggestErr(e.message || String(e)))
      .finally(() => setSuggesting(false));
  };
  const confirmSuggest = () => {
    if (!suggestion) return;
    setCases(suggestion.cases);
    setSuggestion(null);
    setExampleId(null);   // these are now custom cases
    setConfigFingerprint(null);
    setResults(null);     // prior leaderboard is stale
  };
  const discardSuggest = () => { setSuggestion(null); setSuggestErr(null); };

  // ---- gates ----
  if (bootErr) {
    return <div className="cb-boot err">Could not reach the TokenHunger server: {bootErr}</div>;
  }
  if (!boot || !task) {
    return <div className="cb-boot">Loading TokenHunger…</div>;
  }

  const classes = classSplit(cases); // generic expected-label split (or null)
  const meta = (runMeta || boot.meta);
  const hasRun = !!results;
  const demo = !!boot.demo;

  return (
    <React.Fragment>
      <header className="cb-header">
        <div className="cb-header-inner">
          <span className="cb-wordmark">
            {FLAME_MARK}
            <span className="wm"><span className="tk">Token</span><span className="hg">Hunger</span></span>
            <span className="sub">cost per success, not cost per token</span>
          </span>
          <span className="cb-header-spacer" />
          <button className="cb-iconbtn" onClick={() => setDrawer(true)}>
            <span className="badge" /><Icon name="plug" size={14} /> Connectors
          </button>
          <button className="cb-iconbtn" onClick={() => setTweak("dark", !t.dark)} title="Toggle appearance" style={{ width: 36, padding: 0, justifyContent: "center" }}>
            <Icon name={t.dark ? "sun" : "moon"} size={15} />
          </button>
        </div>
      </header>

      <main className="cb-main">
        {demo && (
          <div className="cb-demobanner" role="note">
            <Icon name="spark" size={14} /> <b>Read-only demo.</b> Explore models, cases, and live cost
            <em> estimates</em> — including Claude Fable 5. Running benchmarks is disabled here because it spends real
            provider credits; <span className="mono">pip install costbench &amp;&amp; costbench serve</span> to run locally.
          </div>
        )}
        <Hero task={task} setTask={editTask} examples={examples} exampleId={exampleId} onPickExample={pickExample} />
        <RunBar
          nTargets={activeRows.length}
          nCases={cases.length}
          est={est || { low: 0, high: 0, inTok: 0, outLow: 0, outHigh: 0, opaque: 0, rows: [] }}
          classes={classes}
          check={task.check}
          outCeilPerCase={t.outputTokens}
          outLowPerCase={2}
          concurrency={t.concurrency}
          onConcurrency={(v) => setTweak("concurrency", v)}
          onRun={run}
          running={running}
          hasRun={hasRun}
          progress={runProgress}
          demo={demo}
        />
        {runErr && <div className="cb-runerr">Run failed: {runErr}</div>}

        <div className="cb-gap" />
        <CheapestToTry est={est} onSelect={selectModels} />

        <div className="cb-gap" />
        <TargetsTree
          rows={models}
          removed={removed}
          onToggle={toggleTarget}
          onToggleProvider={toggleProvider}
          onSelectAll={selectAll}
          onClearAll={clearAll}
          onAdd={() => setDrawer(true)}
        />

        <div className="cb-gap" />
        <Cases
          cases={cases}
          sourceLabel={exampleId ? (examples.find((e) => e.id === exampleId) || {}).name || "example" : "custom"}
          onConnect={() => setDrawer(true)}
          suggesting={suggesting}
          suggestion={suggestion}
          suggestErr={suggestErr}
          onSuggest={doSuggest}
          onConfirm={confirmSuggest}
          onRegenerate={doSuggest}
          onDiscard={discardSuggest}
          demo={demo}
        />

        <div className="cb-gap" />
        {hasRun
          ? <Results rows={results} view={t.resultsView} meta={meta} />
          : (
            <div className="cb-card" style={{ padding: 40, textAlign: "center", color: "var(--text-3)" }}>
              {running ? "Running the benchmark…" : "Run the benchmark to see the cost-per-success leaderboard."}
            </div>
          )}
      </main>

      <ConnectorsDrawer
        open={drawer}
        onClose={() => setDrawer(false)}
        mcp={boot.mcpServers || []}
        connectors={connectors}
        onInstall={installConnector}
      />

      <TweaksPanel>
        <TweakSection label="Results view" />
        <TweakRadio label="Layout" value={t.resultsView} options={["table", "chart", "cards"]} onChange={(v) => setTweak("resultsView", v)} />
        <TweakSection label="Appearance" />
        <TweakToggle label="Dark mode" value={t.dark} onChange={(v) => setTweak("dark", v)} />
        <TweakColor label="Accent" value={t.accent} options={["#ff6a1a", "#34d6a0", "#f4f1ec"]} onChange={(v) => setTweak("accent", v)} />
        <TweakSection label="Estimate" />
        <TweakSlider label="Output ceiling" value={t.outputTokens} min={2} max={64} step={1} unit=" tok/case" onChange={(v) => setTweak("outputTokens", v)} />
      </TweaksPanel>
    </React.Fragment>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
