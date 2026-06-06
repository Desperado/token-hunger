#!/usr/bin/env python3
"""Local-only pull of QualityMax crawl outcomes into a costbench dump.

Reads Supabase REST creds from the qa-rag-app .env (service role, used LOCALLY
only — never shipped to Railway), fetches crawl jobs for the demo-scoped public
projects, and writes a costbench `cases` dump (input = crawl spec, expect =
terminal status) that the UI's "QualityMax AI crawl outcomes" preset reads.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ENV = Path("/Users/ruslan/conductor/workspaces/qa-rag-app-v1/las-vegas-v1/.env")
OUT = Path(__file__).resolve().parent.parent / "examples" / "qualitymax" / "data" / "qualitymax_crawls.jsonl"
PROJECTS = [82, 149, 6, 71, 5, 7, 41, 53, 28, 3, 88, 116, 128]
# Keep the demo cheap to RUN: a full 26-target run on the whole set is ~$4.8;
# an evenly-sampled subset keeps the ranking meaningful for a fraction of that.
N_COMPLETED = 50
N_FAILED = 10


def env(key: str) -> str:
    for line in ENV.read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"{key} not found in {ENV}")


def trunc(v, n):
    s = "" if v is None else (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
    return s if len(s) <= n else s[:n] + "…"


def main() -> int:
    base = env("NEXT_PUBLIC_SUPABASE_URL").rstrip("/")
    key = env("NEXT_PUBLIC_SERVICE_ROLE_KEY")
    cols = ("id,project_id,test_case_id,url,depth,test_type,pages_limit,framework,"
            "exploration_strategy,custom_instructions,job_parameters,virtual_test_plan,"
            "status,error_message,created_at,updated_at")
    q = {
        "select": cols,
        "project_id": f"in.({','.join(map(str, PROJECTS))})",
        "status": "in.(completed,failed)",
        "order": "id",
    }
    url = f"{base}/rest/v1/ai_crawl_jobs?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.load(r)

    buckets: dict[str, list] = {"completed": [], "failed": []}
    for row in rows:
        status = (row.get("status") or "").strip()
        if status not in ("completed", "failed"):
            continue
        inp = (
            f"URL: {row.get('url')}\n"
            f"Test type: {row.get('test_type')}\n"
            f"Framework: {row.get('framework')}\n"
            f"Depth: {row.get('depth')}\n"
            f"Page limit: {row.get('pages_limit')}\n"
            f"Exploration strategy: {row.get('exploration_strategy')}\n\n"
            f"Custom instructions:\n{trunc(row.get('custom_instructions'), 400)}\n\n"
            f"Job parameters:\n{trunc(row.get('job_parameters'), 400)}\n\n"
            f"Virtual test plan:\n{trunc(row.get('virtual_test_plan'), 300)}"
        )
        buckets[status].append({
            "input": inp,
            "expect": status,
            "crawl_job_id": row.get("id"),
            "project_id": row.get("project_id"),
            "status": status,
            "created_at": row.get("created_at"),
        })

    def even(lst: list, k: int) -> list:
        """Evenly-spaced deterministic sample of k items (keeps site diversity)."""
        if k >= len(lst):
            return lst
        step = len(lst) / k
        return [lst[int(i * step)] for i in range(k)]

    sample = even(buckets["completed"], N_COMPLETED) + even(buckets["failed"], N_FAILED)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        for line in sample:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    n = len(sample)
    by_status = {
        "completed": min(N_COMPLETED, len(buckets["completed"])),
        "failed": min(N_FAILED, len(buckets["failed"])),
    }
    print(f"wrote {n} cases -> {OUT}  (sampled from {len(buckets['completed'])}+{len(buckets['failed'])})")
    print("by status:", by_status)
    if n:
        first = json.loads(OUT.read_text().splitlines()[0])
        print("--- sample input (truncated) ---")
        print(first["input"][:300])
        print("--- expect:", first["expect"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
