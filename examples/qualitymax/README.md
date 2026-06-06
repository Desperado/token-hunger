# QualityMax connector example

Pull QualityMax test cases (and their real execution outcomes) into a local,
fingerprinted case dump, then benchmark targets against them by cost per
successful outcome.

The design separates the **networked pull** from the **offline run** so the
benchmark stays reproducible: `pull` materializes a local file with its own
content fingerprint; `run` reads only that file and folds its fingerprint into
the run fingerprint. QualityMax is not special-cased — it is reached as a generic
`sql` source (see [`../../docs/CONNECTORS.md`](../../docs/CONNECTORS.md)).

## 1. Pull (once, networked)

Use a **read-only** database role.

```bash
export QUALITYMAX_DB_URL='postgresql://READONLY:...@db.<ref>.supabase.co:5432/postgres'
pip install 'costbench[sql]'
costbench pull examples/qualitymax/pull.yaml
# → .context/qualitymax_cases.jsonl  (+ .meta.json with row counts + fingerprint)
```

Edit `pull.yaml` to set `params.project_id` and the query. The dump carries both
grounds of truth per case: the deterministic `result_status` label and the
free-text `expected_results`.

## 2. Run (offline, reproducible)

Headline metric — cost per correct verdict, deterministic ground truth:

```bash
costbench run examples/qualitymax/label.yaml --report md
```

Secondary, diagnostic — semantic reproduction via an opt-in LLM-as-judge
(arguable by design; see [`judge.py`](judge.py)):

```bash
costbench run examples/qualitymax/semantic.yaml --report md
```

## Notes

- The dump lives under `.context/` (gitignored). It contains customer data —
  keep it out of version control and scope pulls to a single `project_id`.
- The connectors used to *discover* this schema are wired to the agent, not to
  the CLI; the CLI uses its own `QUALITYMAX_DB_URL` credential.
