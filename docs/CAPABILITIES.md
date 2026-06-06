# costbench Technical Capabilities

This document describes the behavior implemented in the current repository.
Future work is tracked separately in [ROADMAP.md](ROADMAP.md).

## Runtime

costbench is a Python 3.10+ package with a `costbench` command-line entry point.
Core installation requires PyYAML and Rich. Model, endpoint, and tokenizer
integrations are optional dependencies loaded only when required.

The package builds as a Python wheel and can run locally or in self-managed CI.

## Commands

### `costbench run <config.yaml>`

Executes every configured case against each target and aggregates:

- passed cases and pass rate;
- execution errors;
- arithmetic mean latency;
- known and unknown case costs;
- average cost per priced run;
- total known cost divided by successful outcomes.

Cases for one target can execute concurrently. The command exits with status
`2` when any target produces execution errors, making it suitable for basic CI
automation.

`--max-cases` supports smoke testing. A truncated run receives a deterministic
subset fingerprint, keeping its history separate from the complete benchmark.

### `costbench estimate <config.yaml>`

Estimates cost without invoking a target or requiring provider credentials.

For model targets it:

- renders the configured system and user messages;
- counts message content, conservative chat framing, and configured tool,
  function, or response schemas;
- uses a locally available provider tokenizer when possible;
- falls back to a padded heuristic when a tokenizer is unavailable or uncached;
- uses a positive output ceiling from the CLI, model parameters, the bundled
  limits table, or the conservative default;
- rounds reported costs upward.

Tokenizer resolution does not download assets. Hugging Face uses
`local_files_only`, and an uncached tiktoken vocabulary falls back to the local
heuristic.

With at least five matching observations, output estimates use local p50-p90
history. Otherwise they use the worst-case output ceiling.

For endpoint and command targets, estimation uses only the declared
per-request or subscription-amortized cost. It does not invent token usage for
an opaque service.

### `costbench suggest <task-type>`

Ranks models with available priors and prices using quality-per-dollar. Priors
are candidate-selection hints, not benchmark results. The bundled values are
explicitly marked illustrative; see [PRIORS.md](PRIORS.md).

### `costbench init [path]`

Writes a ready-to-edit example model benchmark.

### `costbench models`

Lists entries in the bundled pricing table with their verification dates.

## Target Types

### Model

Model targets call LiteLLM and use provider-reported prompt and completion
tokens for actual run costs.

`id` is the stable costbench identity used for pricing and reports. An optional
`model` field can provide a different executable LiteLLM provider/model ID:

```yaml
- type: model
  id: local/gemma-27b
  model: ollama/gemma3:27b
```

This separation allows a local pricing identity to use a valid runtime
provider ID.

### Endpoint

Endpoint targets send a configurable JSON request with optional bearer-token
authentication and extract output through a dotted response path.

### Command

Command targets pass the rendered task through standard input and read standard
output. When a system prompt exists, the command receives a JSON object with
`system` and `input` fields.

Command targets and custom code checks execute trusted local code. Benchmark
configurations from untrusted sources must not be run.

## Correctness Checks

Implemented checks are:

- normalized exact equality;
- normalized substring containment;
- regular-expression matching;
- numeric comparison with absolute or relative tolerance;
- a custom Python callable.

A case can override the benchmark's default check.

## Cost Models

Vendor model prices are stored as input and output USD per million tokens.
Self-hosted models use:

```text
cost = (input tokens + output tokens)
       * GPU hourly rate
       / throughput tokens per second
       / 3600
```

Per-target `infra_cost` overrides apply to both estimates and actual run
reports. Reports preserve the distinct `amortized GPU (batch 1)` basis instead
of labeling it as vendor token pricing.

Opaque targets support:

- fixed cost per request;
- monthly subscription cost amortized over expected request volume;
- unknown cost.

Known costs from attempted failures remain in total cost. Preflight failures
without a request, such as a missing endpoint credential, remain unpriced.

## Reproducibility

Reports include:

- a fingerprint of the benchmark configuration;
- a fingerprint of the effective pricing table;
- explicit target cost bases and assumptions;
- a methodology link.

Local token observations are append-only JSON Lines in
`~/.costbench/history.jsonl`. Set `COSTBENCH_HISTORY` to change the location or
use `--no-history` to disable writes.

## Reports

Run reports can be exported as Markdown, HTML, or JSON. Estimate reports can be
exported as Markdown or JSON. Terminal output uses the same aggregate values.

## Current Boundaries

The current implementation does not provide:

- hosted or shared benchmark history;
- recurring managed execution, dashboards, permissions, or alerts;
- native Ollama/vLLM lifecycle management;
- cache-hit, batch-discount, retry, regional, priority-tier, or tool-call fee
  modeling;
- automatic case generation;
- LLM-as-judge as a built-in correctness default;
- production latency percentiles or distributed load testing.

These boundaries keep local results inspectable while leaving operational
platform features to future work.
