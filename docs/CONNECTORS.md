# Connectors & case sources

costbench separates **where cases come from** from **running the benchmark**, so
a run stays offline and reproducible.

```
  costbench pull <pull.yaml>     (networked: sql, …)  ──▶  cases.jsonl  (+ .meta.json)
  costbench run  <bench.yaml>    (offline: reads the dump)
```

## Case sources in a run config

A run config's `cases:` is either an inline list (the original form) or a
mapping selecting a source. Only **offline** sources are allowed at run time:

```yaml
# inline (unchanged)
cases:
  - input: hello
    expect: world

# from a local dump
cases:
  source: file
  path: ../../.context/cases.jsonl   # resolved relative to the config file
  input_field: input                 # or: input_template: "{title}: {steps}"
  expect_field: expect               # which column becomes the ground truth
  drop_unlabeled: true               # skip rows with empty/None expect
```

`.jsonl`, `.json` (a list, or `{cases: [...]}`), and `.csv` are supported. The
file's bytes are folded into the run fingerprint, so two different dumps never
share a fingerprint even when the config text is identical.

## Pulling cases from an external service

`costbench pull` fetches rows from a source and materializes a fingerprinted
dump. Networked sources live here, never in the run path. Secrets are read from
an environment variable named in the config — never inlined.

```yaml
source:
  type: sql                 # implemented; http and mcp are planned
  dsn_env: SOME_DB_URL      # connection string read from this env var (use a read-only role)
  params: { project_id: 1 } # bound into the query (%(name)s placeholders)
  query: "select ... from ... where project_id = %(project_id)s order by id"
out: ../../.context/cases.jsonl
map:
  input_template: "{title}: {steps}"   # or input_field: <column>
  expect: "{status}"                    # template, or expect_field: <column>
  passthrough: [expected_results, id]   # extra columns kept in the dump
  drop_unlabeled: true
```

`passthrough` lets one dump carry several grounds of truth (e.g. a deterministic
label *and* a free-text expected result); each run config then picks which
column is `expect` via `expect_field`. Install the SQL driver with
`pip install 'costbench[sql]'`.

Give the query a deterministic `ORDER BY`: the dump fingerprint is computed over
the rows in the order returned, and a database does not guarantee row order
without one — so an unordered query can produce a different fingerprint on each
pull even when the underlying data is unchanged.

See [`examples/qualitymax/`](../examples/qualitymax/) for a complete pull → run
example (deterministic label headline + opt-in semantic judge).

## Importing production token usage

`costbench calibrate <config.yaml>` imports token/cost rows from a local dump
into the same history used by `costbench estimate`. The calibration config
names the benchmark whose fingerprint the observations belong to, filters the
source workload, and explicitly maps source model names to benchmark targets:

```yaml
benchmark: crawl.label.yaml
source: ../../.context/ai_cost_log.jsonl
source_label: qualitymax-ai-cost-log
filters: { service: crawl }
target_map:
  claude-haiku-4-5: anthropic/claude-haiku-4-5
fields:
  model: model
  input_tokens: input_tokens
  output_tokens: output_tokens
  cost: cost_usd
  timestamp: created_at
  id: id
```

Only mapped targets present in the benchmark are imported. Stable source row
IDs plus the benchmark fingerprint make repeated imports idempotent. This
binding is intentionally explicit: token distributions from unrelated services
must not calibrate a benchmark merely because they used the same model.
Calibration input paths are resolved through symlinks and must remain inside
the current working directory. Run the command from the repository root; paths
that traverse outside it are rejected.

## Roadmap

- `http` source (export APIs) and `mcp` source (read rows from an MCP server) in
  the pull path — same materialize-then-run model, no run-path change.
- costbench exposed **as** an MCP server (`estimate` / `suggest` / `run` as
  tools) so agents can call the benchmark.
