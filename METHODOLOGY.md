# costbench Methodology

## Claim

costbench compares implementations of the same task by quality, cost, and
latency. Its headline metric is cost per successful outcome:

```text
cost per success = total known cost of all attempts / passed cases
```

This is more informative than token price or average call cost when targets
have different failure rates.

## Experimental Unit

A benchmark contains:

1. A fixed set of cases.
2. One or more targets.
3. A task prompt or input template.
4. A correctness check.
5. Cost assumptions.

Every target receives the same cases. Results should only be compared when
inputs, correctness criteria, and relevant runtime conditions are equivalent.
The configuration fingerprint identifies the exact YAML used for a run.

## Correctness

The benchmark author defines success. costbench supplies deterministic checks
for exact, substring, regular-expression, and numeric matching, plus a Python
code assertion escape hatch.

Deterministic checks are preferred because they are reproducible and
inspectable. An exact check can still encode a bad requirement; the tool cannot
prove that a case set represents production quality. Benchmark credibility
depends on representative cases and a defensible check.

LLM-as-judge is deliberately not a built-in default. Model grading can be
useful, but it adds cost, variance, and possible provider bias that must be
measured separately.

## Cost

### Model targets

For a raw model:

```text
request cost =
  input tokens  * input USD per token
  + output tokens * output USD per token
```

Prices come from the versioned `pricing.yaml` table or explicit configuration
overrides. Each built-in entry includes a verification date and source.

Current limitations:

- cache writes, cache reads, batch discounts, priority tiers, regional
  premiums, long-context tiers, and tool-call fees are not modeled;
- provider-reported token usage is treated as authoritative;
- a provider error without usage data has unknown cost;
- pricing can become stale, so published runs should record the table version.

### Endpoint and command targets

Opaque targets declare one of:

- a per-request cost;
- a monthly subscription amortized over an expected monthly volume;
- unknown cost.

The declared basis is shown in every report. Subscription amortization is an
assumption, not an observed marginal cost. A fair publication should include
the selected volume and explain whether infrastructure, retries, support, and
other bundled value are included. costbench emits the configured note, or the
monthly price and assumed volume, with the report.

Known declared cost is counted for failed attempts once execution was
attempted. Preflight failures such as a missing API key are not assigned a
request cost.

## Latency

Latency is wall-clock time observed by the runner. It includes network and
service time but does not isolate queueing, geographic distance, cold starts,
or client overhead. Multiple runs and percentile reporting are needed before
making production latency claims; the MVP reports the arithmetic mean.

## Ranking

Targets with known finite cost per success rank before targets with infinite
or unknown values. A ranking is only meaningful when the declared cost bases
are economically comparable.

Never use the headline alone. Publish at least:

- pass rate and number of cases;
- errors;
- cost per run;
- cost per success;
- cost basis;
- latency;
- benchmark configuration, config fingerprint, and pricing fingerprint.

## Neutrality Rules

A credible public comparison should:

1. Use identical cases and checks for every target.
2. Publish the configuration needed to reproduce the run.
3. Disclose pricing sources and endpoint cost assumptions.
4. Preserve unfavorable historical results rather than silently replacing
   them.
5. Describe measured results, not make unsupported claims about vendors.
6. Include tasks where a raw model or competitor can win.

costbench has no product-specific scoring path. Raw models, external SaaS
products, and first-party systems are all ordinary targets.

## Interpretation

A result applies to the tested task, cases, configuration, model versions,
prices, and date. It does not establish that one target is universally better.

The practical decision rule is:

> Hold the required quality bar fixed, then choose the lowest-cost target that
> reliably clears it.

Reducing cost by lowering required quality is not an optimization of the same
task.
