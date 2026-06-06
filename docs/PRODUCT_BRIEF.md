# costbench: Shareable Product Brief

## One-Line Idea

An open-source, vendor-neutral benchmark that shows which raw model, SaaS
orchestrator, agent, or custom workflow delivers the lowest **cost per
successful outcome** for a specific task.

## Problem

LLM teams can see token usage, but they still cannot answer:

> Which implementation gives us the required quality at the lowest real cost?

Cost per token is misleading. A cheaper model may fail more often, trigger
retries, or require escalation. Provider dashboards also cannot compare a raw
model against a multi-model SaaS workflow or internal pipeline.

## Product

A developer defines:

- a task;
- representative test cases;
- an objective success check;
- the targets to compare.

costbench runs the same cases against every target and reports:

- pass rate;
- cost per run;
- cost per successful outcome;
- latency;
- errors and cost basis.

Supported targets:

- raw models through LiteLLM;
- generic HTTP endpoints;
- local commands and scripts.

The first experience works offline with no API keys.

## Why It Is Different

Observability products measure spend but usually do not prove correctness.
Evaluation products measure quality but often ignore real cost. costbench sits
between them and makes the economically relevant unit a successful outcome.

Its credibility is structural:

- deterministic checks by default;
- public benchmark configurations;
- transparent, versioned pricing;
- reproducible reports;
- no special treatment for any vendor;
- the tool is designed to show when a raw model or competitor wins.

## Strategic Role

costbench is independent from QualityMax. QualityMax, any competitor, and any
internal system can be added as the same generic endpoint target.

That independence creates three benefits:

1. **Trust and distribution:** useful open-source software earns technical
   credibility and organic reach.
2. **Product learning:** losses reveal where orchestration does not justify its
   cost and where it needs to improve.
3. **Commercial entry:** teams that outgrow one-off local runs need continuous,
   shared operation.

## Honest Open-Core Boundary

Open source remains complete for:

- local benchmarks;
- custom cases and correctness checks;
- raw-model, endpoint, and command comparisons;
- Markdown, HTML, and JSON reports;
- self-managed automation.

A hosted platform can sell:

- managed recurring execution;
- cost-vs-quality history and drift detection;
- pull-request policies and merge gates;
- team dashboards and permissions;
- alerts, governance, and executive reporting;
- maintained evaluation suites at scale.

Payment is driven by real operational work, not artificial setup friction.

## Initial User

An engineering manager, AI platform lead, or founder-CTO shipping multiple LLM
features and providers, who must explain rising AI spend and choose the right
implementation per workflow.

## MVP Success Criteria

- A new user gets a meaningful result in under ten minutes.
- The offline demo clearly shows that cheapest per call can lose on cost per
  success.
- A user can compare at least one raw model with one arbitrary endpoint without
  writing adapter code.
- Every published number can be traced to a case, check, and cost assumption.
- At least five external teams run the tool on a real workflow and share where
  the methodology or setup breaks.

## Key Risks

- Weak or unrepresentative checks make precise-looking results meaningless.
- Pricing changes and complex provider billing can make cost estimates stale.
- OSS maintenance can consume more founder time than the distribution returns.
- Existing observability or eval vendors can copy the headline metric.

The defense is not the formula. It is trusted methodology, target neutrality,
excellent setup, and faster learning from real benchmark results.

## Immediate Roadmap

1. Ship the deterministic local runner and offline demo.
2. Validate setup and methodology with real external workflows.
3. Add benchmark manifests that preserve model, price-table, and environment
   metadata.
4. Improve billing fidelity for caching, tools, retries, and tiered pricing.
5. Test demand for managed continuous runs before building a hosted platform.
