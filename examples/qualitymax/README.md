# QualityMax production dataset examples

Pull real QualityMax test cases, AI crawls, security findings, generated-test
quality scores, and AI cost observations into local fingerprinted dumps.

The design separates the **networked pull** from the **offline run** so the
benchmark stays reproducible: `pull` materializes a local file with its own
content fingerprint; `run` reads only that file and folds its fingerprint into
the run fingerprint. QualityMax is not special-cased — it is reached as a generic
`sql` source (see [`../../docs/CONNECTORS.md`](../../docs/CONNECTORS.md)).

## Available datasets

| Dataset | Pull config | Run config | Recorded ground truth |
|---|---|---|---|
| Test cases | `pull.yaml` | `label.yaml` | latest automation result |
| AI crawls | `crawl.pull.yaml` | `crawl.label.yaml` | terminal crawl status |
| Security reviews | `review.pull.yaml` | `review.grade.yaml` | audit grade |
| Generated-test quality | `quality.pull.yaml` | `quality.run.yaml` | A-F quality grade |
| Actual AI spend | `cost.pull.yaml` | `cost.calibrate.yaml` | tokens and USD cost |

## 1. Pull (networked)

Use a **read-only** database role.

```bash
export QUALITYMAX_DB_URL='postgresql://READONLY:...@db.<ref>.supabase.co:5432/postgres'
pip install 'costbench[sql]'
costbench pull examples/qualitymax/crawl.pull.yaml
costbench pull examples/qualitymax/review.pull.yaml
costbench pull examples/qualitymax/quality.pull.yaml
costbench pull examples/qualitymax/cost.pull.yaml
```

Set `params.project_id` in each pull config. Every query has a deterministic
`ORDER BY`, and every dump gets a content fingerprint plus metadata.

For the crawl MVP, use the one-command setup instead of editing YAML:

```bash
examples/qualitymax/mvp.sh 42
costbench serve
```

The script pulls crawl outcomes and matching production cost rows, imports
calibration, and writes an estimate report. The local UI then exposes
**QualityMax AI crawl outcomes** in the task picker and marks the QualityMax
connector installed. You can also set `QUALITYMAX_PROJECT_ID` in `.env` and run
the script without an argument.

## 2. Run (offline, reproducible)

Headline metric — cost per correct verdict, deterministic ground truth:

```bash
costbench run examples/qualitymax/label.yaml --report md
costbench run examples/qualitymax/crawl.label.yaml --report md
costbench run examples/qualitymax/review.grade.yaml --report md
costbench run examples/qualitymax/quality.run.yaml --report md
```

Secondary, diagnostic — semantic reproduction via an opt-in LLM-as-judge
(arguable by design; see [`judge.py`](judge.py)):

```bash
costbench run examples/qualitymax/semantic.yaml --report md
```

These are **historical prediction benchmarks**. They test model judgment against
recorded outcomes; they do not replay a browser crawl, security scan, or test
execution. To measure the live system, add QualityMax as an `endpoint` or
`command` target and keep the same deterministic checks.

## 3. Calibrate estimates from actual spend

After pulling both crawl cases and the cost log:

```bash
costbench calibrate examples/qualitymax/cost.calibrate.yaml
costbench estimate examples/qualitymax/crawl.label.yaml
```

The calibration config explicitly maps QualityMax's served model names to
benchmark target IDs and filters to the `crawl` service. Rows for unknown models
are skipped. Imports are idempotent by QualityMax row ID and benchmark
fingerprint, so rerunning the command does not duplicate observations.

## Notes

- The dump lives under `.context/` (gitignored). It contains customer data —
  keep it out of version control and scope pulls to a single `project_id`.
- Use the served `model` for cost calibration. `model_requested` and
  `fell_back` remain in the dump for fallback analysis but are not used to
  attribute token usage to a model that did not actually serve the request.
- The connectors used to *discover* this schema are wired to the agent, not to
  the CLI; the CLI uses its own `QUALITYMAX_DB_URL` credential.
