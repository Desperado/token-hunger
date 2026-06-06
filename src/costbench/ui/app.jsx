/* costbench — main App: layout, theme, tweaks, and the live run flow.
 *
 * All data is fetched from the backend (see api.js / server.py):
 *   - bootstrap on mount: task, cases, the live pricing models, fingerprints;
 *   - estimate re-runs (debounced) whenever the task or selected targets change;
 *   - run executes the real benchmark and renders the leaderboard.
 */

const { useState, useMemo, useEffect, useRef } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "dark": false,
  "resultsView": "table",
  "accent": "#007aff",
  "outputTokens": 3
}/*EDITMODE-END*/;

const ACCENTS = {
  "#007aff": { accent: "#007aff", soft: "rgba(0,122,255,0.12)", text: "#007aff", darkAccent: "#0a84ff", darkText: "#409cff", darkSoft: "rgba(10,132,255,0.18)" },
  "#30d158": { accent: "#248a3d", soft: "rgba(48,209,88,0.14)", text: "#248a3d", darkAccent: "#30d158", darkText: "#30d158", darkSoft: "rgba(48,209,88,0.18)" },
  "#5e5ce6": { accent: "#5e5ce6", soft: "rgba(94,92,230,0.14)", text: "#5e5ce6", darkAccent: "#7d7aff", darkText: "#9b99ff", darkSoft: "rgba(94,92,230,0.22)" },
  "#1d1d1f": { accent: "#1d1d1f", soft: "rgba(0,0,0,0.07)", text: "#1d1d1f", darkAccent: "#f5f5f7", darkText: "#f5f5f7", darkSoft: "rgba(255,255,255,0.12)" },
};

function useThemeEffect(t, theme) {
  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", theme);
    const a = ACCENTS[t.accent] || ACCENTS["#007aff"];
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
    setResults(null);
  };
  // A manual prompt edit means it's no longer one of the presets.
  const editTask = (nt) => { setTask(nt); setExampleId(null); };

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

  // ---- estimate (debounced; keyless, offline on the server) ----
  const [est, setEst] = useState(null);
  const [estErr, setEstErr] = useState(null);
  const estSeq = useRef(0);

  useEffect(() => {
    if (!task || activeIds.length === 0) { setEst(null); return; }
    const seq = ++estSeq.current;
    const handle = setTimeout(() => {
      CostbenchAPI.estimate({ task, targets: activeIds, cases, outputTokens: t.outputTokens })
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
  }, [task, activeIds, cases, t.outputTokens]);

  // ---- run ----
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState(null);
  const [runMeta, setRunMeta] = useState(null);
  const [runErr, setRunErr] = useState(null);
  const [runProgress, setRunProgress] = useState(null);

  const run = () => {
    if (running || activeIds.length === 0) return;
    setRunning(true); setRunErr(null); setResults(null); setRunProgress(null);
    CostbenchAPI.run({ task, targets: activeIds, cases }, (event) => {
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
    setResults(null);     // prior leaderboard is stale
  };
  const discardSuggest = () => { setSuggestion(null); setSuggestErr(null); };

  // ---- gates ----
  if (bootErr) {
    return <div className="cb-boot err">Could not reach the costbench server: {bootErr}</div>;
  }
  if (!boot || !task) {
    return <div className="cb-boot">Loading costbench…</div>;
  }

  const classes = classSplit(cases); // generic expected-label split (or null)
  const meta = (runMeta || boot.meta);
  const hasRun = !!results;

  return (
    <React.Fragment>
      <header className="cb-header">
        <div className="cb-header-inner">
          <span className="cb-wordmark">
            <span className="dot" />costbench
            <span className="sub">cost per success</span>
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
        <Hero task={task} setTask={editTask} examples={examples} exampleId={exampleId} onPickExample={pickExample} />
        <RunBar
          nTargets={activeRows.length}
          nCases={cases.length}
          est={est || { low: 0, high: 0, inTok: 0, outLow: 0, outHigh: 0, opaque: 0, rows: [] }}
          classes={classes}
          check={task.check}
          outCeilPerCase={t.outputTokens}
          outLowPerCase={2}
          onRun={run}
          running={running}
          hasRun={hasRun}
          progress={runProgress}
        />
        {runErr && <div className="cb-runerr">Run failed: {runErr}</div>}

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
        <TweakColor label="Accent" value={t.accent} options={["#007aff", "#30d158", "#5e5ce6", "#1d1d1f"]} onChange={(v) => setTweak("accent", v)} />
        <TweakSection label="Estimate" />
        <TweakSlider label="Output ceiling" value={t.outputTokens} min={2} max={64} step={1} unit=" tok/case" onChange={(v) => setTweak("outputTokens", v)} />
      </TweaksPanel>
    </React.Fragment>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
