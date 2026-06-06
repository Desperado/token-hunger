#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

project_id="${1:-${QUALITYMAX_PROJECT_ID:-}}"
max_cases="${QUALITYMAX_MAX_CASES:-25}"

if [[ -z "$project_id" ]]; then
  echo "usage: examples/qualitymax/mvp.sh <project_id>" >&2
  echo "or set QUALITYMAX_PROJECT_ID in .env" >&2
  exit 2
fi

if ! command -v costbench >/dev/null 2>&1; then
  echo "costbench is not installed; run: pip install -e '.[sql,models]'" >&2
  exit 2
fi

costbench pull examples/qualitymax/crawl.pull.yaml \
  --param "project_id=$project_id"
costbench pull examples/qualitymax/cost.pull.yaml \
  --param "project_id=$project_id"
costbench calibrate examples/qualitymax/cost.calibrate.yaml
costbench estimate examples/qualitymax/crawl.label.yaml \
  --report md \
  --out .context/qualitymax-crawl-estimate.md

echo
echo "QualityMax MVP is ready with up to $max_cases cases per smoke run."
echo "Open the UI: costbench serve"
echo "Run models:  costbench run examples/qualitymax/crawl.label.yaml --max-cases $max_cases"
