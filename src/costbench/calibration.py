"""Import external token observations into costbench's local history."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from .config import load_config
from .history import Observation, append_unique_observations
from .sources import rows_from_file


@dataclass(frozen=True)
class CalibrationImportResult:
    rows: int
    matched: int
    imported: int
    duplicates: int
    skipped: int
    config_fingerprint: str
    source_path: Path


def _field(fields: dict, name: str, default: str) -> str:
    value = fields.get(name, default)
    if not isinstance(value, str) or not value:
        raise ValueError(f"calibration field {name!r} must be a non-empty string")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a non-negative integer") from exc
    if not math.isfinite(numeric) or not numeric.is_integer() or numeric < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return int(numeric)


def _optional_cost(value: Any) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return None
    try:
        cost = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("cost must be a non-negative number") from exc
    if not math.isfinite(cost) or cost < 0:
        raise ValueError("cost must be a non-negative number")
    return cost


def _row_id(row: dict, id_field: str) -> str:
    value = row.get(id_field)
    if value is not None and str(value):
        return str(value)
    canonical = json.dumps(row, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _resolve_input_path(raw: Any, config_dir: Path, allowed_root: Path) -> Path:
    if not isinstance(raw, (str, Path)) or not str(raw):
        raise ValueError("calibration input path must be a non-empty string")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = config_dir / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(allowed_root):
        raise ValueError(
            f"calibration input path {str(raw)!r} escapes allowed root {allowed_root}"
        )
    return resolved


def import_calibration(
    path: str | Path,
    *,
    history_path: Optional[str | Path] = None,
    allowed_root: Optional[str | Path] = None,
) -> CalibrationImportResult:
    """Load a calibration YAML and bind matching rows to one benchmark."""
    config_path = Path(path).resolve()
    root = (
        Path(allowed_root).resolve()
        if allowed_root is not None
        else Path.cwd().resolve()
    )
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("calibration config root must be a mapping")

    benchmark_raw = raw.get("benchmark")
    source_raw = raw.get("source")
    if not benchmark_raw:
        raise ValueError("calibration config needs a 'benchmark' path")
    if not source_raw:
        raise ValueError("calibration config needs a 'source' path")

    benchmark_path = _resolve_input_path(benchmark_raw, config_path.parent, root)
    source_path = _resolve_input_path(source_raw, config_path.parent, root)

    benchmark = load_config(benchmark_path, allowed_root=root)
    target_ids = {target.id for target in benchmark.targets}
    rows = rows_from_file(source_path)

    filters = raw.get("filters") or {}
    if not isinstance(filters, dict):
        raise ValueError("calibration 'filters' must be a mapping")
    target_map = raw.get("target_map") or {}
    if not isinstance(target_map, dict):
        raise ValueError("calibration 'target_map' must be a mapping")
    fields = raw.get("fields") or {}
    if not isinstance(fields, dict):
        raise ValueError("calibration 'fields' must be a mapping")

    model_field = _field(fields, "model", "model")
    input_field = _field(fields, "input_tokens", "input_tokens")
    output_field = _field(fields, "output_tokens", "output_tokens")
    cost_field = _field(fields, "cost", "cost_usd")
    timestamp_field = _field(fields, "timestamp", "created_at")
    id_field = _field(fields, "id", "id")
    passed_field = fields.get("passed")
    source_label = str(raw.get("source_label") or "external")

    observations: list[Observation] = []
    matched = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if any(row.get(key) != value for key, value in filters.items()):
            continue
        matched += 1

        model = row.get(model_field)
        if model is None or str(model).strip() == "":
            continue
        model_id = str(model)
        target_id = str(target_map.get(model_id, model_id))
        if target_id not in target_ids:
            continue

        try:
            input_tokens = _nonnegative_int(row.get(input_field), input_field)
            output_tokens = _nonnegative_int(row.get(output_field), output_field)
            cost = _optional_cost(row.get(cost_field))
        except ValueError:
            continue

        stable_id = (
            f"{source_label}:{benchmark.fingerprint}:{_row_id(row, id_field)}"
        )
        observations.append(
            Observation(
                config_fingerprint=benchmark.fingerprint,
                target_id=target_id,
                model_id=model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
                passed=bool(row.get(passed_field, False)) if passed_field else False,
                ts=str(row.get(timestamp_field) or ""),
                observation_id=stable_id,
                source=source_label,
                schema_version=2,
            )
        )

    imported = append_unique_observations(observations, history_path)
    return CalibrationImportResult(
        rows=len(rows),
        matched=matched,
        imported=imported,
        duplicates=len(observations) - imported,
        skipped=len(rows) - len(observations),
        config_fingerprint=benchmark.fingerprint,
        source_path=source_path.resolve(),
    )
