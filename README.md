# TokenHunger

**Don't waste tokens on expensive models.** TokenHunger shows which model
delivers each correct result at the lowest cost, not which one has the lowest
token price or the biggest name. Not every task needs a frontier model, and
paying frontier prices for work a smaller model handles well is money burned.

This is especially useful for **agents**: benchmark the kinds of steps an agent
performs, then use the measured pass rates and costs to decide where a cheaper
model is sufficient and where a more capable model earns its price.

TokenHunger makes that tradeoff measurable. It benchmarks any LLM-powered
target by **cost per successful outcome**, not cost per token, so failures count
against apparently cheap models instead of being hidden by a low per-call price.

> The command-line engine is `costbench` (see Quick Start). TokenHunger is the
> product around it.

A target can be:

- a raw model called through LiteLLM;
- any HTTP API, including a SaaS orchestrator or custom agent;
- a local command or pipeline.

Every target receives the same cases and is judged by the same correctness
check. The result shows whether a cheaper call is actually cheaper after failed
outputs are counted. Reports carry separate fingerprints for the benchmark
configuration and effective pricing table.

## What Exists Today

costbench is an installable Python 3.10+ CLI with these implemented workflows:

- run the same cases against LiteLLM models, HTTP endpoints, and local commands;
- grade outputs with exact, contains, regex, numeric, or custom Python checks;
- report pass rate, errors, latency, cost per run, and cost per success;
- estimate model and black-box target costs before execution;
- calibrate output-token estimates from local run history;
- price vendor models from a versioned table and self-hosted models from
  amortized GPU cost;
- suggest candidate models from clearly labeled benchmark priors;
- optionally classify task category and complexity with a user-selected cheap
  LiteLLM model;
- export Markdown, HTML, and JSON reports;
- identify benchmark and pricing inputs with deterministic fingerprints;
- run cases concurrently and return non-zero exit codes for execution errors;
- pull cases from an external source (e.g. a SQL database) into a local,
  fingerprinted dump, then benchmark offline against it (see
  [docs/CONNECTORS.md](docs/CONNECTORS.md));
- explore all of the above in a local web UI with `costbench serve` — a
  keyless cost estimate updates live as you pick targets, and **Run** executes
  the real benchmark and ranks targets by cost per success.

`costbench serve` is deliberately loopback-only because Run can spend provider
credits using keys in the server process. Keep secrets in a gitignored,
owner-readable `.env` (`chmod 600 .env`), never in benchmark YAML. Endpoint
`auth_env` tokens should be short-lived and least-privilege where possible.

The estimator requires no API key or target execution. Tokenizer cache misses
fall back to a local heuristic rather than downloading assets. Partial
`--max-cases` runs receive a different fingerprint, so smoke-test observations
cannot calibrate the full benchmark accidentally.

For the complete technical inventory and boundaries, see
[docs/CAPABILITIES.md](docs/CAPABILITIES.md).

## Why

Defaulting every call to the biggest model is expensive, while choosing only by
token price ignores failures. TokenHunger measures both sides of that tradeoff:
how often each target succeeds and how much each successful result costs.

The question it answers is not "what's the best model?" but:

> Which model has the lowest cost per successful result — for *this* task?

Token price alone can't answer it, because a cheap model that fails often may
not be cheap per usable result. The metric is **cost per correct answer**, and
it can cut either way: a smaller model can win when its savings outweigh its
failures, while a pricier, more reliable model can win when the extra successes
justify its price.

Here is a real, keyless run from the working demo
(`costbench run examples/offline/demo.yaml`) — a case where the cheaper target
actually loses, because its extra failures cost more than the price it saved:

```text
Target          Pass   Cost/run   Cost/SUCCESS
premium-smart   100%   $0.001050  $0.001050   ← cheaper per CORRECT answer
cheap-naive      90%   $0.001000  $0.001111
```

Flip the task to something the cheap model handles more reliably and the result
can flip with it. The point is that you no longer have to guess: the report
shows pass rate and cost per success together, so you can apply your own quality
requirements before choosing a target.

## Quick Start

Requires Python 3.10 or newer.

```bash
git clone https://github.com/Desperado/token-hunger.git
cd token-hunger
python -m venv .venv
source .venv/bin/activate
pip install -e .
costbench run examples/offline/demo.yaml
```

The offline demo uses two local classifiers, needs no API keys, and completes
the full benchmark flow.

Launch the local web UI:

```bash
costbench serve
```

This opens `http://127.0.0.1:8765/`. Loading the UI and generating estimates
need no provider keys. To execute benchmarks against hosted models, install
model support with `pip install -e ".[models]"` and put the provider keys those
models require in a gitignored `.env`.

Generate a shareable report:

```bash
costbench run examples/offline/demo.yaml \
  --report markdown \
  --out costbench-report.md
```

Available report formats are Markdown, HTML, and JSON.

## Predict Cost Before You Spend

`costbench estimate <config>` predicts cost from your config **without running a
single target** — no API key, no network. It counts the chat request with a
locally available tokenizer (`pip install -e ".[tokenizers]"`) and an
over-estimate-safe heuristic otherwise, then prices a range:

- **input cost** is tokenized from messages, framing, and configured schemas;
- **output cost** is a worst-case ceiling from `max_tokens`/`model_limits.yaml`,
  or a calibrated p50–p90 range once you have run history.

```bash
costbench estimate examples/classification.yaml
costbench estimate examples/classification.yaml --max-output-tokens 256 --report md
```

Estimates always **round up** and carry the basis `estimated (...)` — they are
never blended with verified `$/token` run costs. `run` records observed tokens
to a local calibration history file (`~/.costbench/history.jsonl`, override with
`COSTBENCH_HISTORY`, opt out with `--no-history`) so estimates tighten over time.
Production token logs can be imported into that history with an explicit
workload/target mapping via `costbench calibrate <config.yaml>`; see
[`docs/CONNECTORS.md`](docs/CONNECTORS.md#importing-production-token-usage).

The free-tier limit is a deliberate, **billing-free hook**: `estimate` is
unlimited by default; a future host can cap it by setting
`COSTBENCH_FREE_TIER_MAX_CASES` or replacing `limits_gate.check_estimate_quota`.
No billing is implemented.

## Suggest Models to Try

`costbench suggest <task-type>` ranks candidate models by **quality-per-dollar**
using public benchmark priors, so you know what to try before writing a config:

```bash
costbench suggest coding
costbench suggest math --top 3
```

You can also opt in to task analysis by a cheap LiteLLM model:

```bash
pip install -e ".[models]"
costbench suggest \
  --config benchmark.yaml \
  --analyzer-model qwen/qwen3.5-flash
```

The analyzer returns:

- a broad ranking type: `coding`, `math`, or `general`;
- a functional category such as classification, extraction, or reasoning;
- `low`, `medium`, or `high` complexity;
- confidence, rationale, signals, token usage, and analyzer cost when priced.

This sends the task instructions and at most five bounded case inputs to the
selected model. Expected answers, targets, credentials, and pricing are not
sent. Analysis is never automatic; passing `--analyzer-model` is explicit
consent to the provider call.

For the MVP, detected task type selects the static prior family. Complexity is
informational and does not alter ranking until costbench has sufficient
observed benchmark history to justify complexity-conditioned recommendations.

Priors are a **starting point, not ground truth** — your own `costbench run` is
ground truth. The bundled seed dataset currently contains clearly marked
illustrative placeholders and must not be used as published evidence.
Artificial Analysis data is **not bundled**; its opt-in runtime integration is
a roadmap item and currently returns a clear not-implemented error. See
[docs/PRIORS.md](docs/PRIORS.md).

## Compare Models

Install model support:

```bash
pip install -e ".[models]"
costbench init benchmark.yaml
```

Edit `benchmark.yaml`, set the provider keys required by your selected models,
then run:

```bash
costbench run benchmark.yaml --report html --out report.html
```

Model calls use LiteLLM. Cost is computed independently from the transparent
[`pricing.yaml`](src/costbench/pricing.yaml) table committed in this repository.

## Compare Any API

An endpoint target can represent a SaaS product, an orchestrator, an agent, a
RAG pipeline, or an internal service:

```yaml
targets:
  - type: endpoint
    id: my-orchestrator
    url: https://api.example.com/v1/run
    auth_env: MY_SERVICE_KEY
    request_template:
      task: "{input}"
    response_path: result.answer
    cost:
      basis: per_request
      per_request: 0.002
```

Install endpoint support with `pip install -e ".[endpoint]"`.

Endpoint internals are usually opaque, so their cost must be declared as one
of:

```yaml
cost:
  basis: per_request
  per_request: 0.002
```

```yaml
cost:
  basis: subscription
  monthly: 500
  expected_monthly_volume: 100000
```

Or omit `cost` to report it as unknown. The report always displays the basis;
costbench does not invent token costs for services it cannot observe.

## Configuration

```yaml
name: Support triage

targets:
  - type: model
    id: anthropic/claude-haiku-4-5
  - type: command
    id: local-pipeline
    command: ["python", "pipeline.py"]
    cost:
      basis: per_request
      per_request: 0.001

task:
  system: Reply with ESCALATE or RESOLVE.
  prompt_template: "Ticket: {input}"

check: exact

cases:
  - input: "Someone accessed another customer's account."
    expect: ESCALATE
  - input: "Where can I download an invoice?"
    expect: RESOLVE
```

Built-in deterministic checks:

- `exact`: normalized equality;
- `contains`: expected value appears in output;
- `regex`: expected value is a regular expression;
- `numeric`: numeric equality with optional absolute or relative tolerance;
- `code`: your Python function returns pass/fail.

Per-case checks can override the benchmark default.

```yaml
check:
  type: numeric
  tolerance: 0.05
  relative: true
```

```yaml
check:
  type: code
  function: checks.py:grade
```

Code checks and command targets execute local code. Only run trusted benchmark
configurations.

### Local / self-hosted models

Self-hosted models (e.g. `local/gemma-27b`, `local/qwen-coder`) have no vendor
`$/token` price. costbench prices them by **amortized GPU time** — a distinct
cost basis (`amortized GPU (batch 1)`) that is never blended with vendor rates.
The defaults in `pricing.yaml` are conservative (batch-size-1, over-estimate-
safe); override them for your own hardware per target:

```yaml
targets:
  - type: model
    id: local/gemma-27b
    model: ollama/gemma3:27b       # executable LiteLLM provider/model ID
    infra_cost:
      gpu_hourly_rate: 1.03         # your GPU $/hour
      throughput_tokens_per_sec: 3100
```

`id` selects the costbench pricing entry and report label. When that ID is not
itself executable by LiteLLM, set `model` to the provider/model ID used for the
actual request.

## Metric

For each target:

```text
cost per success = total cost across all attempts / number of passed cases
```

Failed attempts remain in total cost when their cost is known. A target with
zero passes has infinite cost per success. A target with unknown cost is not
assigned a synthetic value.

See [METHODOLOGY.md](METHODOLOGY.md) for assumptions and limitations.

## Project Boundary

costbench is vendor-neutral and standalone. It has no QualityMax dependency,
special adapter, preferred target, or scoring path. Any service competes as the
same generic endpoint target under the same cases and checks.

The open-source tool is complete for local, one-off comparisons. A future
hosted product can add the operational layer that does not belong in the core:
shared history, continuous drift monitoring, managed execution, alerts, and
team governance. The CLI remains usable locally and in self-managed automation.

## Development

```bash
pip install -e ".[dev]"
pytest
python -m build
```

The initial scope intentionally excludes shared/hosted historical storage,
hosted execution, team dashboards, auto-generated cases, and LLM-as-judge
defaults. Local calibration history is implemented in
`~/.costbench/history.jsonl`.

## License

Source-available under the [Functional Source License,
Version 1.1, Apache 2.0 Future License (FSL-1.1-ALv2)](LICENSE) — created by
Sentry. Free for any non-competing use: internal use, modifications,
contributions, education, research, and professional services. The only thing
it withholds is offering costbench itself as a competing commercial product or
service. Two years after each release, that version automatically converts to
plain Apache 2.0.

> The "Other" tag GitHub shows in the sidebar is a quirk of its license
> detector — FSL is not on the SPDX list, so GitHub can't name it.
