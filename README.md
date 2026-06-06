# costbench

Benchmark any LLM-powered target by **cost per successful outcome**, not cost
per token.

A target can be:

- a raw model called through LiteLLM;
- any HTTP API, including a SaaS orchestrator or custom agent;
- a local command or pipeline.

Every target receives the same cases and is judged by the same correctness
check. The result shows whether a cheaper call is actually cheaper after failed
outputs are counted. Reports carry separate fingerprints for the benchmark
configuration and effective pricing table.

## Why

Token prices do not answer the question engineering teams care about:

> Which implementation reaches our quality bar at the lowest real cost?

If target A costs `$0.001` per call and succeeds 70% of the time while target B
costs `$0.0012` and succeeds 95%, target B can be cheaper per correct result.

costbench makes that tradeoff visible:

```text
Target          Pass   Cost/run   Cost/SUCCESS
premium-smart   100%   $0.00105   $0.00105
cheap-naive      90%   $0.00100   $0.00111
```

## Quick Start

Requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
costbench run examples/offline/demo.yaml
```

The offline demo uses two local classifiers, needs no API keys, and completes
the full benchmark flow.

Generate a shareable report:

```bash
costbench run examples/offline/demo.yaml \
  --report markdown \
  --out costbench-report.md
```

Available report formats are Markdown, HTML, and JSON.

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

The initial scope intentionally excludes historical storage, hosted execution,
team dashboards, auto-generated cases, and LLM-as-judge defaults.
