# Hosting costbench (Railway) — Architecture B

This deploys the costbench web UI as a hosted **demo** that serves a *pre-pulled*
QualityMax dataset. The hosted box has **no database access** — the networked
`pull` runs elsewhere (locally / in CI) and only the resulting offline `.jsonl`
dump is placed on the box's volume.

Why B: the production Supabase has RLS on every table, so a hosted reader would
need a `BYPASSRLS` role whose DSN lives on the box. B avoids that entirely — no
DB credentials ever touch Railway.

## Security invariants (do not violate)
- **No provider API keys** in the Railway environment. Keyless, the `/api/run`
  endpoint cannot spend credits; the offline demo + estimate still work.
- `COSTBENCH_PUBLIC_HOST=<domain>` is the *only* thing that relaxes the
  loopback-only guards (`serve` bind + API `Origin` check). Set it to exactly
  the public domain.
- Put Railway access protection in front if it should not be world-readable
  (the dump contains customer data).

## Deploy (CLI)
```bash
# from this branch's worktree
railway init                       # create the project/service
railway volume add --mount-path /app/.context   # persist dumps across deploys
railway variables --set COSTBENCH_PUBLIC_HOST=<domain-after-first-deploy>
railway up                         # build the Dockerfile + deploy
railway domain                     # get / confirm the public URL
```

The bundled **offline demo** works immediately (no data, no keys) and shows the
cost-inversion table. The QualityMax dataset is layered on next.

## Refreshing the QualityMax dataset (runs OFF the box)
Run the networked pull where governed DB credentials already exist (local dev or
QualityMax CI), then upload the dump to the volume:
```bash
export QUALITYMAX_DB_URL='postgresql://<read-only-role>:...@db.<ref>.supabase.co:5432/postgres'
pip install 'costbench[sql]'
costbench pull examples/qualitymax/crawl.pull.yaml   # writes .context/qualitymax_crawls.jsonl
costbench pull examples/qualitymax/cost.pull.yaml
costbench calibrate examples/qualitymax/cost.calibrate.yaml
# then copy the .context/*.jsonl dumps onto the Railway volume (one-off railway run / volume sync)
```
Refresh = re-pull + re-upload (manual, or scheduled in CI). The box itself never
holds DB credentials.
