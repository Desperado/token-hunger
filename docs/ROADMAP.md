# costbench roadmap

## Current foundation

The local runner, offline demo, pre-run estimator, local calibration history,
model suggestions, optional LLM task analysis, self-hosted GPU costing, report
exporters, and configuration/pricing fingerprints are implemented. See
[CAPABILITIES.md](CAPABILITIES.md) for the current contract.

## SDK / proxy wrapper (DESIGN ONLY — not implemented)

A thin wrapper that estimates a call **before it fires**, reusing the existing
estimate machinery — no new core logic.

Shape:

1. Before a real LLM call, take the rendered messages, model-visible schemas,
   and the call's output-token limit.
2. Run the request-aware token estimator and treat the explicit output limit
   (or the `model_limits.yaml` ceiling) as the worst-case output ceiling, using
   the same request-estimate + ceiling-output range `estimate` produces.
3. Optionally **block or warn** when the per-call ceiling exceeds a budget the
   caller sets. Over-estimate-safe: the wrapper quotes the ceiling, never a
   fake-precise point number.
4. After the call returns, append the **actual** observed usage to the
   calibration history file (`history.append_observations`) so future estimates
   for the same workload tighten from worst-case ceiling toward a real p50–p90
   range.

Reuses `tokens.py`, `estimate.py`, and `history.py` verbatim. A future managed
host can read the same JSONL history file.

### Explicitly out of scope (founder item 6)

Caching, batch, tool-call, and retry cost modeling are **not** modeled. These
change cost in both directions; assuming caching/batch discounts would
under-estimate and violate over-estimate-safe. Tracked as v2 work; see the
`TODO(v2)` notes in `pricing.yaml` and `targets.py`.

## Other v2 candidates

- Complexity-conditioned recommendations learned from benchmark history:
  estimate success probability, cost, and latency for each task fingerprint,
  then choose the cheapest model whose confidence bound clears the quality bar.
- Native `local_model` target type wrapping an ollama/vLLM server (today: use a
  `model` target with a LiteLLM execution `model`, or an `endpoint`/`command`
  target).
- Cache-hit / batch / retry overhead pricing.
- Calibrated p50/p90 surfaced in the `run` report, not only in `estimate`.
