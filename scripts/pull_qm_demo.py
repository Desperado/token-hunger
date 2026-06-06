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

    OUT.parent.mkdir(parents=True, exist_ok=True)
    n, by_status = 0, {}
    with OUT.open("w") as f:
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
            line = {
                "input": inp,
                "expect": status,
                "crawl_job_id": row.get("id"),
                "project_id": row.get("project_id"),
                "status": status,
                "created_at": row.get("created_at"),
            }
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
            n += 1
            by_status[status] = by_status.get(status, 0) + 1

    print(f"wrote {n} cases -> {OUT}")
    print("by status:", by_status)
    if n:
        first = json.loads(OUT.read_text().splitlines()[0])
        print("--- sample input (truncated) ---")
        print(first["input"][:300])
        print("--- expect:", first["expect"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
