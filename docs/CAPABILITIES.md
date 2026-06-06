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

### `costbench suggest [task-type]`

Ranks models with available priors and prices using quality-per-dollar. Priors
are candidate-selection hints, not benchmark results. The bundled values are
explicitly marked illustrative; see [PRIORS.md](PRIORS.md).

The task type can be supplied manually or inferred with an opt-in analyzer:

```bash
costbench suggest \
  --config benchmark.yaml \
  --analyzer-model qwen/qwen3.5-flash
```

The analyzer calls the user-selected model through LiteLLM and returns:

- broad prior family: coding, math, or general;
- functional category;
- low, medium, or high complexity;
- confidence, explanation, and detected signals;
- provider token usage and computed call cost when pricing is available.

The payload is bounded to the task instructions, prompt template, check
definition, and up to five case inputs. It excludes expected answers, target
definitions, credentials, and prices. No analyzer call occurs unless
`--analyzer-model` is explicitly provided.

In the MVP, task type selects the static prior family. Complexity is displayed
but does not modify the ranking score.

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
authentication and extract output through a dotted response path. The `url` must
use an `http`/`https` scheme; loopback, private, link-local, and cloud-metadata
hosts (e.g. `169.254.169.254`) are rejected by default to avoid pointing the
benchmark at internal services (SSRF). Set `allow_private_endpoint: true` on the
target to benchmark a genuinely local service such as a localhost model server.

### Command

Command targets pass the rendered task through standard input and read standard
output. When a system prompt exists, the command receives a JSON object with
`system` and `input` fields.

Command targets and custom code checks execute trusted local code. Benchmark
configurations from untrusted sources must not be run.

A command target may instead run inside an e2b cloud sandbox by setting
`sandbox: e2b` (requires the `e2b` extra and `E2B_API_KEY`). The stdin/stdout
contract is unchanged, but the command runs off the local machine. Note the
isolation covers the *command only*: a `code` check still runs on the host via
`exec_module`, so combining a `code` check with a `sandbox: e2b` target is
rejected unless the config sets `allow_local_code_checks: true`. The config
file, stdout/stderr captured into reports, and the sandbox's network egress
remain trusted/uncontrolled.

**Cost basis.** A combined CPU + RAM rate must be declared with
`cost.basis: per_second` and `cost.per_second: <rate>`; there is no fallback
because E2B resource prices and template sizes vary. Only the *seconds* are
observed — the rate is your declared number and must already fold in the
template's vCPU + RAM tier, so reports label this `e2b-seconds × declared-rate`,
not "measured." The full sandbox lifetime (spin-up, idle, teardown) is billed
and **allocated** across the cases a worker processed, weighted by each case's
active time; per-case cost is therefore an allocation, not an isolated meter
reading, and shifts with pool size and load. The per-call `timeout` is bounded
(1–3600s) so a hung command cannot run up an unbounded bill.

**Pooling / speed.** During a `run`, sandboxes are reused across cases instead
of recreated for every call. The pool defaults to 10 and is bounded by
`sandbox_pool_size` (maximum 10), runner concurrency, and case count. Sandbox
creation is paced at one per second for Hobby accounts; higher tiers may lower
`sandbox_create_interval`. Pool workers reuse their VM filesystem, so commands
should be stateless between cases or clean any paths they mutate. This
parallelizes **`command` + `sandbox: e2b` targets only** — it does not speed up
`model`/`endpoint` targets, nor the `suggest`/analyze (LiteLLM) paths, which
remain direct provider calls. The end-to-end speedup is unmeasured here; expect
it to scale with concurrency up to the pool size minus per-case overhead. An
optional `sandbox_template` selects an e2b template. See
`examples/sandbox/e2b.yaml`.

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
- production latency percentiles or distributed load testing;
- complexity-conditioned ranking from historical benchmark outcomes.

These boundaries keep local results inspectable while leaving operational
platform features to future work.
