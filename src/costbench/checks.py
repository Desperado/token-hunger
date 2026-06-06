"""Correctness checks — the crux of the tool's credibility.

A cost-per-success number is only as trustworthy as the "success" test behind
it. So the defaults here are deterministic, reproducible, and not up for debate:
exact / contains / regex / numeric, plus an escape hatch to your own Python
code. LLM-as-judge is intentionally NOT built in as a default — the moment a
benchmark's correctness depends on a model's opinion, the numbers become
arguable, and arguable is the one thing a benchmark cannot be.

A check is a callable ``(output: str, expect) -> CheckResult``. Build one from a
config spec with :func:`make_check`.
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class CheckResult:
    passed: bool
    detail: str = ""


Check = Callable[[str, Any], CheckResult]


def _normalize(text: str) -> str:
    """Trim, lowercase, and collapse internal whitespace."""
    return re.sub(r"\s+", " ", str(text).strip().lower())


def _exact(case_sensitive: bool = False) -> Check:
    def check(output: str, expect: Any) -> CheckResult:
        if case_sensitive:
            ok = str(output).strip() == str(expect).strip()
        else:
            ok = _normalize(output) == _normalize(expect)
        return CheckResult(ok, "" if ok else f"expected {expect!r}, got {output!r}")

    return check


def _contains(case_sensitive: bool = False) -> Check:
    def check(output: str, expect: Any) -> CheckResult:
        hay = str(output) if case_sensitive else _normalize(output)
        needle = str(expect) if case_sensitive else _normalize(expect)
        ok = needle in hay
        return CheckResult(ok, "" if ok else f"{expect!r} not found in output")

    return check


def _regex(flags: int = re.IGNORECASE) -> Check:
    def check(output: str, expect: Any) -> CheckResult:
        ok = re.search(str(expect), str(output), flags) is not None
        return CheckResult(ok, "" if ok else f"pattern {expect!r} did not match")

    return check


_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _numeric(tolerance: float = 0.0, relative: bool = False) -> Check:
    def check(output: str, expect: Any) -> CheckResult:
        m = _NUMBER_RE.search(str(output))
        if not m:
            return CheckResult(False, f"no number found in output {output!r}")
        got = float(m.group(0).replace(",", ""))
        want = float(expect)
        bound = abs(want) * tolerance if relative else tolerance
        ok = abs(got - want) <= bound
        return CheckResult(ok, "" if ok else f"expected {want} (±{bound}), got {got}")

    return check


def _load_callable(spec: str, base_dir: Path | None = None) -> Callable:
    """Load ``module/file.py:function`` from a path or importable module.

    A relative file path is resolved against ``base_dir`` (the config file's
    directory) when given, so a `code` check works regardless of the cwd — the
    same rule a `file` case source uses. A cwd-relative path still resolves as a
    fallback for back-compat.
    """
    if ":" not in spec:
        raise ValueError(f"code check must be 'path.py:function', got {spec!r}")
    location, func_name = spec.rsplit(":", 1)
    path = Path(location)
    if base_dir is not None and not path.is_absolute() and (base_dir / path).exists():
        path = base_dir / path
    if path.exists():
        mod_spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(mod_spec)
        mod_spec.loader.exec_module(module)  # type: ignore[union-attr]
    else:
        # `import importlib.util` at module scope already binds `importlib`; a
        # local re-import here would shadow it and break the path branch above.
        module = importlib.import_module(location)
    return getattr(module, func_name)


def _code(spec: str, base_dir: Path | None = None) -> Check:
    fn = _load_callable(spec, base_dir)

    def check(output: str, expect: Any) -> CheckResult:
        result = fn(output, expect)
        if isinstance(result, CheckResult):
            return result
        if isinstance(result, tuple):
            passed, detail = result
            return CheckResult(bool(passed), str(detail))
        return CheckResult(bool(result), "" if result else "code check returned falsey")

    return check


def make_check(spec: Any, base_dir: Path | None = None) -> Check:
    """Build a check callable from a config value.

    ``spec`` may be a bare string (``"exact"``, ``"contains"``, ``"regex"``,
    ``"numeric"``) or a mapping with a ``type`` key and options, e.g.::

        check:
          type: numeric
          tolerance: 0.5

        check:
          type: code
          function: checks.py:grade

    ``base_dir`` (the config file's directory) is used to resolve a relative
    ``code`` check path; it is ignored by the built-in deterministic checks.
    """
    if isinstance(spec, str):
        spec = {"type": spec}
    if not isinstance(spec, dict):
        raise ValueError(f"invalid check spec: {spec!r}")

    kind = spec.get("type")
    if kind == "exact":
        return _exact(spec.get("case_sensitive", False))
    if kind == "contains":
        return _contains(spec.get("case_sensitive", False))
    if kind == "regex":
        return _regex(re.IGNORECASE if not spec.get("case_sensitive") else 0)
    if kind == "numeric":
        return _numeric(spec.get("tolerance", 0.0), spec.get("relative", False))
    if kind == "code":
        target = spec.get("function") or spec.get("path")
        if not target:
            raise ValueError("code check needs a 'function' (path.py:name)")
        return _code(target, base_dir)
    raise ValueError(
        f"unknown check type {kind!r}; "
        "use exact, contains, regex, numeric, or code"
    )
