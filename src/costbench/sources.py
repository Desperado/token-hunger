"""Case sources — where a benchmark's cases come from.

The run path stays **pure and offline**: cases are either written inline in the
config, or read from a local file that a prior `costbench pull` materialized.
Networked sources (sql/http/mcp) deliberately live in the *pull* path
(:mod:`costbench.connectors`), never here — so a `run` is reproducible and its
fingerprint actually pins the cases it scored.

A source resolves to ``(list[Case], content_key)``. ``content_key`` is folded
into the config fingerprint so two different dumps never collide on one
fingerprint, even though the config YAML referencing them is byte-identical.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from .config import Case


def _render(template: str, row: dict) -> str:
    """Fill ``{column}`` placeholders from a row, leaving unknown ones intact."""
    out = template
    for key, value in row.items():
        out = out.replace("{" + key + "}", "" if value is None else str(value))
    return out


def _rows_from_file(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".jsonl":
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows
    if suffix == ".json":
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("cases"), list):
            data = data["cases"]
        if not isinstance(data, list):
            raise ValueError(f"{path}: JSON case file must be a list (or {{cases: [...]}})")
        return data
    if suffix == ".csv":
        return list(csv.DictReader(text.splitlines()))
    raise ValueError(f"{path}: unsupported case file type {suffix!r}; use .jsonl/.json/.csv")


def _cases_from_rows(
    rows: list[dict],
    *,
    input_field: str,
    input_template: Optional[str],
    expect_field: str,
    check: Any,
    drop_unlabeled: bool,
    where: str,
) -> list[Case]:
    cases: list[Case] = []
    dropped = 0
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{where}: row {i} must be a mapping, got {row!r}")
        if input_template is not None:
            case_input = _render(input_template, row)
        else:
            if input_field not in row:
                raise ValueError(
                    f"{where}: row {i} has no {input_field!r} field "
                    f"(available: {sorted(row)})"
                )
            case_input = row[input_field]
        expect = row.get(expect_field)
        if drop_unlabeled and (expect is None or str(expect).strip() == ""):
            dropped += 1
            continue
        cases.append(Case(input=str(case_input), expect=expect, check=check))
    if dropped:
        # Surfaced, never silent — a dropped row is a case that won't be scored.
        print(f"note: {where}: dropped {dropped} unlabeled row(s) (drop_unlabeled)")
    return cases


def load_cases(spec: Any, base_dir: Path) -> tuple[list[Case], str]:
    """Resolve a config ``cases:`` value into cases plus a content key.

    ``spec`` is either a list (inline cases — the original form) or a mapping
    ``{source: inline|file, ...}``. ``base_dir`` is the config file's directory,
    so a ``file`` source path is resolved relative to the config.
    """
    if isinstance(spec, list):
        return _inline(spec), ""

    if not isinstance(spec, dict):
        raise ValueError(f"'cases' must be a list or a mapping, got {spec!r}")

    source = spec.get("source", "inline")
    if source == "inline":
        items = spec.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("inline case source needs a non-empty 'items' list")
        return _inline(items), ""

    if source == "file":
        raw_path = spec.get("path")
        if not raw_path:
            raise ValueError("file case source needs a 'path'")
        path = Path(raw_path)
        if not path.is_absolute():
            path = base_dir / path
        rows = _rows_from_file(path)
        cases = _cases_from_rows(
            rows,
            input_field=spec.get("input_field", "input"),
            input_template=spec.get("input_template"),
            expect_field=spec.get("expect_field", "expect"),
            check=spec.get("check"),
            drop_unlabeled=bool(spec.get("drop_unlabeled", False)),
            where=str(path),
        )
        if not cases:
            raise ValueError(f"{path}: no cases loaded")
        # Pin the actual bytes scored, not just the path, into the fingerprint.
        content_key = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        return cases, content_key

    raise ValueError(
        f"unknown case source {source!r}; use 'inline' or 'file' "
        "(networked sources like 'sql' run via `costbench pull`)"
    )


def _inline(items: list) -> list[Case]:
    cases = []
    for i, c in enumerate(items):
        if not isinstance(c, dict):
            raise ValueError(f"case {i} must be a mapping: {c!r}")
        if "input" not in c or "expect" not in c:
            raise ValueError(f"case {i} needs 'input' and 'expect': {c!r}")
        cases.append(Case(input=str(c["input"]), expect=c["expect"], check=c.get("check")))
    return cases
