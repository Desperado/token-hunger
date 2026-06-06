"""Connectors — pull benchmark cases from external services into a local dump.

This is the **impure, networked** half of the case pipeline. It runs only when
the user invokes `costbench pull`; it never runs during `costbench run`. The
output is a fingerprinted local case file that the run path then treats like any
other `file` source — so the benchmark itself stays offline and reproducible.

Connectors are generic on purpose. QualityMax is not special-cased: it is just a
`sql` source pointed at its Postgres database (the `qamax_rag` project), with a
query and a field mapping declared in the pull config. Any other service that
can emit rows over SQL plugs in the same way; `http` and `mcp` sources are
planned to land here next without changing the run path.

Secrets are never read from the pull config. A `sql` source names an environment
variable holding the connection string (`dsn_env`); the credential lives in the
environment, the config stays shareable.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class PullResult:
    out_path: Path
    rows: int
    written: int
    dropped_unlabeled: int
    fingerprint: str
    source: str


def _render(template: str, row: dict) -> str:
    out = template
    for key, value in row.items():
        out = out.replace("{" + key + "}", "" if value is None else str(value))
    return out


# Injection seam so the mapping/writing logic is unit-testable without a DB.
RowFetcher = Callable[[dict], list[dict]]


def _fetch_sql_rows(source: dict) -> list[dict]:
    """Run the source query against a read-only Postgres connection.

    psycopg is imported lazily and only needed for `sql` pulls, matching the
    litellm/httpx pattern elsewhere in costbench.
    """
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional dep
        raise RuntimeError(
            "sql source needs the optional dependency: pip install costbench[sql]"
        ) from exc

    dsn_env = source.get("dsn_env")
    if not dsn_env:
        raise ValueError("sql source needs a 'dsn_env' naming the connection-string env var")
    dsn = os.environ.get(dsn_env)
    if not dsn:
        raise ValueError(f"environment variable {dsn_env!r} is not set")

    query = source.get("query")
    if not query:
        raise ValueError("sql source needs a 'query'")
    params = source.get("params") or {}

    with psycopg.connect(dsn) as conn:  # pragma: no cover - needs a live DB
        conn.read_only = True
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]


def materialize(
    rows: list[dict],
    mapping: dict,
    out_path: Path,
    *,
    source_label: str,
) -> PullResult:
    """Map fetched rows to case dicts and write a fingerprinted JSONL dump.

    Pure given its inputs (no network), so this is what the tests exercise. Each
    output row carries the mapped ``input``/``expect`` plus any passthrough
    columns, so a later run config can choose which column is the ``expect`` —
    e.g. a deterministic label for the headline metric and a free-text field for
    an opt-in semantic check, off the same dump.
    """
    input_template = mapping.get("input_template")
    input_field = mapping.get("input_field", "input")
    expect_template = mapping.get("expect")
    expect_field = mapping.get("expect_field")
    passthrough = mapping.get("passthrough") or []
    drop_unlabeled = bool(mapping.get("drop_unlabeled", False))

    out_rows: list[dict] = []
    dropped = 0
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"row {i} is not a mapping: {row!r}")
        if input_template is not None:
            case_input = _render(input_template, row)
        elif input_field in row:
            case_input = row[input_field]
        else:
            raise ValueError(
                f"row {i}: no 'input_template' and no {input_field!r} column "
                f"(available: {sorted(row)})"
            )

        if expect_template is not None:
            expect: Any = _render(expect_template, row)
        elif expect_field is not None:
            expect = row.get(expect_field)
        else:
            expect = None

        if drop_unlabeled and (expect is None or str(expect).strip() == ""):
            dropped += 1
            continue

        record = {"input": str(case_input), "expect": expect}
        for col in passthrough:
            record[col] = row.get(col)
        out_rows.append(record)

    # Deterministic bytes: stable key order, no run-to-run nondeterminism, so the
    # same query result always produces the same fingerprint.
    payload = "".join(
        json.dumps(r, separators=(",", ":"), sort_keys=True, ensure_ascii=False) + "\n"
        for r in out_rows
    )
    fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(payload, encoding="utf-8")

    meta = {
        "source": source_label,
        "rows_fetched": len(rows),
        "rows_written": len(out_rows),
        "dropped_unlabeled": dropped,
        "fingerprint": fingerprint,
        "mapping": mapping,
    }
    out_path.with_suffix(out_path.suffix + ".meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )

    return PullResult(
        out_path=out_path,
        rows=len(rows),
        written=len(out_rows),
        dropped_unlabeled=dropped,
        fingerprint=fingerprint,
        source=source_label,
    )


def pull(pull_config: dict, base_dir: Path, fetcher: Optional[RowFetcher] = None) -> PullResult:
    """Execute a pull config: fetch rows from the source, materialize the dump.

    ``fetcher`` is an injection point used by tests; in production it defaults to
    the source-type dispatcher below.
    """
    source = pull_config.get("source")
    if not isinstance(source, dict) or not source.get("type"):
        raise ValueError("pull config needs a 'source' mapping with a 'type'")
    stype = source["type"]

    out_raw = pull_config.get("out")
    if not out_raw:
        raise ValueError("pull config needs an 'out' path")
    out_path = Path(out_raw)
    if not out_path.is_absolute():
        out_path = base_dir / out_path

    mapping = pull_config.get("map") or {}
    if not isinstance(mapping, dict):
        raise ValueError("pull config 'map' must be a mapping")

    if fetcher is not None:
        rows = fetcher(source)
    elif stype == "sql":
        rows = _fetch_sql_rows(source)
    else:
        raise ValueError(
            f"unknown pull source type {stype!r}; 'sql' is implemented "
            "('http' and 'mcp' are planned)"
        )

    return materialize(rows, mapping, out_path, source_label=stype)


def load_pull_config(path: str | Path) -> dict:
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("pull config root must be a mapping")
    return raw
