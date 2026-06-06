# costbench roadmap

## SDK / proxy wrapper (DESIGN ONLY — not implemented)

A thin wrapper that estimates a call **before it fires**, reusing the existing
estimate machinery — no new core logic.

Shape:

1. Before a real LLM call, take the rendered prompt + the call's `max_tokens`.
2. Run `tokens.count_input_tokens(prompt, model_id)` for the exact-ish input
   count, and treat `max_tokens` (or the `model_limits.yaml` ceiling) as the
   worst-case output ceiling — the same exact-input + ceiling-output range
   `estimate` produces.
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

- Native `local_model` target type wrapping an ollama/vLLM server (today: use a
  `model` target via litellm, or an `endpoint`/`command` target).
- Cache-hit / batch / retry overhead pricing.
- Calibrated p50/p90 surfaced in the `run` report, not only in `estimate`.
