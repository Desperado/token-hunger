# Model quality priors — licensing & policy

`costbench suggest <task-type>` ranks candidate models by public quality priors
**before** you run your real scenario. Priors are a starting point, **not ground
truth** — the only ground truth is your own `costbench run` on your real cases.

## Source policy (binding)

- **Artificial Analysis (artificialanalysis.ai) is NOT bundled, cached, or
  committed** anywhere in this repo. Their Terms of Service prohibit
  republishing their data; attribution is insufficient. No scraper, no snapshot.
  AA is available only as an **opt-in runtime source** (`--priors-source=
  artificialanalysis`) that requires the user's own API key
  (`ARTIFICIAL_ANALYSIS_API_KEY`) and caches nothing to disk. The runtime fetch
  is a roadmap item and currently raises a clear opt-in error.

- The bundled seed dataset (`src/costbench/priors.yaml`) currently ships
  **ILLUSTRATIVE PLACEHOLDER numbers only** — they are synthetic, not measured,
  and exist solely to wire the feature end-to-end. They are **not** attributed
  to any source, on purpose: a real-looking score linked to a URL that does not
  actually state that number is exactly the "looks sourced but isn't" trap this
  tool exists to expose, so we refuse to ship one.

- **Standard for real data** (what a contributor must meet to replace the
  placeholders): a value belongs here only if it comes from a source that
  *actually states it* — a provider system card, the benchmark's own
  leaderboard, or a peer-reviewed paper — bundled with a source URL containing
  the figure, the benchmark's license, and the date you verified it. Linking a
  model's score to a benchmark's *definition* repo does not meet this bar.

## Acceptable real sources (for contributors replacing the seed)

| Source | Used for | License |
| --- | --- | --- |
| A benchmark's own leaderboard (e.g. an MMLU-Pro/HumanEval leaderboard that publishes per-model scores) | the score it actually lists | per that benchmark |
| Provider system cards | per-model published numbers | cited per row |

Note: the *benchmark definition* repos (e.g. `openai/human-eval`,
`TIGER-AI-Lab/MMLU-Pro`) define the task but do **not** publish model scores —
do not cite them as the source of a number. See `LICENSE.priors` at the repo root.

## Seed data caveat

`priors.yaml` is **illustrative seed data**. Each row is marked
`"ILLUSTRATIVE seed — replace with real, sourced numbers before use"`, and
`suggest` prints a visible warning whenever it ranks on these placeholders. Every
value MUST be replaced with a real, sourced number before any published
comparison. Self-hosted / quantized models (e.g. `local/gemma-27b`,
`local/qwen-coder`) ship with no priors on purpose — there is no reliable public
number for an arbitrary quant/serving config. Run costbench to establish ground
truth for those.

## Ranking method

`suggest` ranks by **quality-per-dollar**:

- `quality` = mean of task-relevant public-benchmark scores, normalized 0–1.
- `blended $/1M` = `(3 × input_per_m + 1 × output_per_m) / 4` (a documented,
  deterministic 3:1 input:output assumption).
- rank = `quality / blended` descending.

Prices older than 30 days are flagged `(price may be stale)`.
