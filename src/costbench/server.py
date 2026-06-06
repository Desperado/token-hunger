"""`costbench serve` — a local web UI wired to the real engine.

A tiny stdlib HTTP server (no new dependencies) that serves the static UI in
``ui/`` and exposes a small JSON API backed by the *same* functions the CLI
uses, so the dashboard shows real numbers:

  GET  /api/bootstrap   default task + cases, the live pricing table grouped by
                        vendor, connectors, and config/pricing fingerprints.
  POST /api/estimate    keyless, offline cost estimate for the selected targets
                        (real tokenizer counts via :mod:`costbench.estimate`).
  POST /api/run         execute the benchmark and return the cost-per-success
                        leaderboard with per-case classifications.
  POST /api/run-stream  the same run as newline-delimited progress events,
                        followed by the complete leaderboard.

Nothing here invents numbers: estimates come from ``estimate_config`` and run
results from ``run_benchmark`` over a ``Config`` built from the posted task,
targets, and cases. ``run`` needs provider API keys in the environment just like
``costbench run``; without them each case reports its error honestly.
"""

from __future__ import annotations

import json
import ipaddress
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

UI_DIR = Path(__file__).resolve().parent / "ui"
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_TARGETS = 100
MAX_CASES = 1000
MAX_RUNS = 10_000
MAX_TEXT_LENGTH = 100_000
WEB_CHECKS = {"exact", "contains", "regex", "numeric"}

# Map a litellm-style provider prefix to the vendor label the UI styles by.
_VENDOR_BY_PREFIX = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "gemini": "Google",
    "google": "Google",
    "mistral": "Mistral",
    "qwen": "Qwen",
    "deepseek": "DeepSeek",
    "local": "Self-hosted",
}

# Informational connector catalog — mirrors docs/CONNECTORS.md. The only pull
# path implemented today is `sql` (via `costbench pull`); http/mcp are planned.
_CONNECTORS = [
    {"id": "sql", "name": "SQL database", "kind": "Data", "status": "available",
     "detail": "Pull labeled rows into a case dump via `costbench pull` (Postgres)."},
    {"id": "http", "name": "HTTP export API", "kind": "Data", "status": "planned",
     "detail": "Pull cases from an export endpoint (planned)."},
    {"id": "mcp", "name": "MCP server", "kind": "Agent", "status": "planned",
     "detail": "Read rows from an MCP server (planned)."},
]
_MCP = []  # MCP usage/trace connectors are not wired yet — show none rather than fake.


def vendor_of(model_id: str) -> str:
    prefix = str(model_id).split("/", 1)[0].lower()
    return _VENDOR_BY_PREFIX.get(prefix, "Endpoint")


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text).strip().lower())


def _validate_text(value: Any, field: str, *, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if len(value) > MAX_TEXT_LENGTH:
        raise ValueError(f"{field} is too long")


def _validate_web_check(check: Any) -> None:
    if isinstance(check, str):
        kind = check
        options = {}
    elif isinstance(check, dict):
        kind = check.get("type")
        options = check
    else:
        raise ValueError("task.check must be a string or object")
    if kind not in WEB_CHECKS:
        raise ValueError(
            "web checks must be exact, contains, regex, or numeric"
        )
    allowed = {
        "exact": {"type", "case_sensitive"},
        "contains": {"type", "case_sensitive"},
        "regex": {"type", "case_sensitive"},
        "numeric": {"type", "tolerance", "relative"},
    }[kind]
    unknown = set(options) - allowed
    if unknown:
        raise ValueError(f"unsupported {kind} check option: {sorted(unknown)[0]}")
    for key in ("case_sensitive", "relative"):
        if key in options and not isinstance(options[key], bool):
            raise ValueError(f"task.check.{key} must be boolean")
    if "tolerance" in options:
        tolerance = options["tolerance"]
        if (
            not isinstance(tolerance, (int, float))
            or isinstance(tolerance, bool)
            or tolerance < 0
        ):
            raise ValueError("task.check.tolerance must be a non-negative number")


def _validate_sandbox(sandbox: Any) -> None:
    """Validate the optional e2b-sandbox target block (UI 'Run in E2B' toggle).

    The server normally only runs `model` targets; this opt-in block lets the UI
    run a single `command` target inside an e2b sandbox. It stays loopback-only
    (enforced per request) and the command is the operator's own — the same trust
    boundary as a local CLI config.
    """
    if not isinstance(sandbox, dict):
        raise ValueError("sandbox must be an object")
    command = sandbox.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("sandbox.command must be a non-empty string")
    if len(command) > 4000:
        raise ValueError("sandbox.command is too long")
    rate = sandbox.get("perSecond")
    if (
        not isinstance(rate, (int, float))
        or isinstance(rate, bool)
        or not 0 < rate <= 1
    ):
        raise ValueError(
            "sandbox.perSecond must be a positive USD/second rate (<= 1)"
        )
    template = sandbox.get("template")
    if template not in (None, ""):
        _validate_text(template, "sandbox.template")
    pool = sandbox.get("poolSize", 10)
    if not isinstance(pool, int) or isinstance(pool, bool) or not 1 <= pool <= 10:
        raise ValueError("sandbox.poolSize must be an integer between 1 and 10")


def _validate_run_body(body: Any, *, allow_empty: bool = False) -> dict:
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    task = body.get("task")
    if not isinstance(task, dict):
        raise ValueError("task must be an object")
    _validate_text(task.get("system"), "task.system", allow_none=True)
    _validate_text(task.get("promptTemplate", "{input}"), "task.promptTemplate")
    _validate_web_check(task.get("check", "exact"))

    # Sandbox mode: the lone target is a command run in an e2b sandbox, so the
    # model-ids requirement is relaxed (targets is ignored). Otherwise require
    # 1..MAX_TARGETS model ids exactly as before.
    sandbox = body.get("sandbox")
    cases = body.get("cases")
    if sandbox is not None:
        _validate_sandbox(sandbox)
        n_targets = 1
    else:
        targets = body.get("targets")
        if not isinstance(targets, list) or (not targets and not allow_empty):
            raise ValueError("targets must be a non-empty array")
        if len(targets) > MAX_TARGETS or not all(
            isinstance(t, str) and t for t in targets
        ):
            raise ValueError(f"targets must contain 1-{MAX_TARGETS} model ids")
        n_targets = len(targets)
    if not isinstance(cases, list) or (not cases and not allow_empty):
        raise ValueError("cases must be a non-empty array")
    if len(cases) > MAX_CASES:
        raise ValueError(f"cases cannot exceed {MAX_CASES}")
    for i, case in enumerate(cases):
        if not isinstance(case, dict) or "input" not in case or "expect" not in case:
            raise ValueError(f"cases[{i}] must contain input and expect")
        _validate_text(case["input"], f"cases[{i}].input")
        if isinstance(case["expect"], (dict, list)):
            raise ValueError(f"cases[{i}].expect must be a scalar")
    if n_targets * len(cases) > MAX_RUNS:
        raise ValueError(f"a request cannot exceed {MAX_RUNS} target/case calls")
    fingerprint = body.get("configFingerprint")
    if fingerprint is not None and not re.fullmatch(r"[0-9a-f]{12}", fingerprint):
        raise ValueError("configFingerprint must be a 12-character hex fingerprint")

    if "concurrency" in body:
        concurrency = body["concurrency"]
        if not isinstance(concurrency, int) or isinstance(concurrency, bool):
            raise ValueError("concurrency must be an integer")
        if not 1 <= concurrency <= 32:
            raise ValueError("concurrency must be between 1 and 32")
    if "outputTokens" in body:
        output_tokens = body["outputTokens"]
        if not isinstance(output_tokens, int) or isinstance(output_tokens, bool):
            raise ValueError("outputTokens must be an integer")
        if not 1 <= output_tokens <= 1_000_000:
            raise ValueError("outputTokens must be between 1 and 1000000")
    return body


def _validate_suggest_body(body: Any) -> dict:
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    task = body.get("task")
    if not isinstance(task, dict):
        raise ValueError("task must be an object")
    _validate_text(task.get("system"), "task.system", allow_none=True)
    _validate_text(task.get("promptTemplate", "{input}"), "task.promptTemplate")
    _validate_web_check(task.get("check", "exact"))
    n = body.get("n", 10)
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 24:
        raise ValueError("n must be an integer between 1 and 24")
    if body.get("model") is not None:
        _validate_text(body["model"], "model")
    return body


def validate_request(path: str, body: Any) -> dict:
    if path in ("/api/estimate", "/api/run", "/api/run-stream"):
        return _validate_run_body(body)
    if path == "/api/suggest-cases":
        return _validate_suggest_body(body)
    raise ValueError("unsupported endpoint")


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _public_host() -> str | None:
    """Public hostname this instance may be reached at when hosted behind a
    front door (e.g. Railway). Set ``COSTBENCH_PUBLIC_HOST`` to the deployed
    domain to relax the otherwise loopback-only guards in ``serve`` and
    ``_is_allowed_origin``.

    SAFETY: the run API can spend provider credits using keys in this process,
    so a hosted instance MUST run WITHOUT provider API keys (offline/estimate
    demo) or behind authentication. See examples/deploy/README.md.
    """
    h = os.environ.get("COSTBENCH_PUBLIC_HOST", "").strip().lower()
    return h or None


def _is_local_http_authority(value: str) -> bool:
    try:
        hostname = urlsplit("//" + value).hostname
    except ValueError:
        return False
    return bool(hostname and _is_loopback_host(hostname))


def _is_allowed_origin(value: str | None) -> bool:
    if value is None:
        return True
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return _is_loopback_host(host) or host == _public_host()


def _sandbox_target(sandbox: dict) -> dict:
    """Translate the UI sandbox block into an e2b command TargetSpec dict."""
    target = {
        "type": "command",
        "id": sandbox.get("id") or "sandboxed-agent",
        "sandbox": "e2b",
        "command": sandbox["command"],
        "sandbox_pool_size": int(sandbox.get("poolSize", 10)),
        "cost": {"basis": "per_second", "per_second": float(sandbox["perSecond"])},
    }
    if sandbox.get("template"):
        target["sandbox_template"] = sandbox["template"]
    return target


def _build_cfg(
    task: dict,
    target_ids: list[str],
    cases: list[dict],
    *,
    sandbox: dict | None = None,
    config_fingerprint: str | None = None,
):
    """Build a real Config from the posted task/targets/cases (no file written)."""
    from .config import build_config

    targets = (
        [_sandbox_target(sandbox)]
        if sandbox is not None
        else [{"type": "model", "id": tid} for tid in target_ids]
    )
    raw = {
        "name": task.get("name", "costbench"),
        "task": {
            "system": task.get("system"),
            "prompt_template": task.get("promptTemplate", "{input}"),
        },
        "check": task.get("check", "exact"),
        "targets": targets,
        "cases": [{"input": c["input"], "expect": c["expect"]} for c in cases],
    }
    config = build_config(raw, base_dir=Path.cwd())
    if config_fingerprint:
        config.fingerprint = config_fingerprint
    return config


def _connectors_payload(examples: list[dict]) -> list[dict]:
    connectors = [dict(connector) for connector in _CONNECTORS]
    qualitymax = next(
        (example for example in examples if example["id"] == "qualitymax-crawls"),
        None,
    )
    connectors.append({
        "id": "qualitymax",
        "name": "QualityMax",
        "kind": "Data",
        "status": "installed" if qualitymax else "available",
        "cases": len(qualitymax["cases"]) if qualitymax else 0,
        "detail": (
            "Production AI crawl outcomes and token usage. Run "
            "`examples/qualitymax/mvp.sh <project_id>` to refresh."
        ),
    })
    return connectors


def _models_payload(pricing) -> list[dict]:
    from .pricing import AmortizedGpuPrice

    out = []
    for mid in pricing.ids():
        price = pricing.get(mid)
        row = {
            "id": mid,
            "vendor": vendor_of(mid),
            "type": "model",
            "priced": True,
            "verified": str(price.verified or ""),
        }
        if isinstance(price, AmortizedGpuPrice):
            row.update(
                basis="amortized GPU (batch 1)",
                gpu=price.gpu_hourly_rate,
                tput=price.throughput_tokens_per_sec,
            )
        else:
            row.update(
                basis="vendor $/token",
                inPrice=price.input_per_m,
                outPrice=price.output_per_m,
            )
        out.append(row)
    return out


# ---------------------------------------------------------------- endpoints


def bootstrap_payload() -> dict:
    from .pricing import load_pricing
    from .ui_examples import presets

    pricing = load_pricing()
    examples = presets(base_dir=Path.cwd())
    default = examples[0]  # support triage — matches the bundled example
    task = default["task"]
    cases = default["cases"]
    models = _models_payload(pricing)

    cfg = _build_cfg(task, [m["id"] for m in models], cases)
    return {
        "task": task,
        "cases": cases,
        "examples": examples,
        "models": models,
        "connectors": _connectors_payload(examples),
        "mcpServers": _MCP,
        "meta": {
            "nCases": len(cases),
            "configFingerprint": "cfg:" + cfg.fingerprint,
            "pricingFingerprint": "px:" + pricing.fingerprint,
        },
    }


def estimate_payload(body: dict) -> dict:
    from .estimate import estimate_config
    from .history import load_observations
    from .limits import load_model_limits
    from .pricing import load_pricing

    task = body["task"]
    target_ids = body.get("targets") or []
    cases = body.get("cases") or []
    out_override = body.get("outputTokens")

    # Sandbox cost is measured from runtime, not estimable up front.
    if body.get("sandbox") is not None:
        return {
            "rows": [],
            "meta": {"nCases": len(cases), "sandbox": True,
                     "note": "e2b cost is measured at run time, not estimated"},
        }

    cfg = _build_cfg(
        task,
        target_ids,
        cases,
        config_fingerprint=body.get("configFingerprint"),
    )
    pricing = load_pricing()
    limits = load_model_limits()
    try:
        history = load_observations()
    except Exception:  # noqa: BLE001 — history is best-effort
        history = []

    estimates = estimate_config(
        cfg, pricing, limits, history=history, max_output_override=out_override
    )

    rows = []
    for e in estimates:
        opaque = e.input_tokens_total is None
        in_cost = e.input_cost_total or 0.0
        cost_low = None if (not e.priced) else in_cost + (e.output_cost_low or 0.0)
        cost_high = None if (not e.priced) else in_cost + (e.output_cost_high or 0.0)
        rows.append({
            "id": e.target_id,
            "vendor": vendor_of(e.target_id),
            "type": e.target_type,
            "basis": _result_basis(pricing, e.target_id, e.target_type),
            "priced": e.priced,
            "opaque": opaque,
            "inTok": e.input_tokens_total,
            "outLowTok": e.output_tokens_low,
            "outHighTok": e.output_tokens_high,
            "costLow": cost_low,
            "costHigh": cost_high,
            "calibrated": e.calibrated,
            "note": e.note,
        })
    return {
        "rows": rows,
        "meta": {
            "configFingerprint": "cfg:" + cfg.fingerprint,
            "pricingFingerprint": "px:" + pricing.fingerprint,
            "nCases": len(cases),
        },
    }


def suggest_cases_payload(body: dict) -> dict:
    from .suggest_cases import suggest_cases

    task = body.get("task") or {}
    n = body.get("n", 10)
    model = body.get("model")
    return suggest_cases(task, n=n, model=model)


def _result_basis(pricing, target_id: str, target_type: str) -> str:
    from .pricing import AmortizedGpuPrice

    if target_type != "model":
        return "declared per_request"
    price = pricing.get(target_id)
    if isinstance(price, AmortizedGpuPrice):
        return "amortized GPU (batch 1)"
    return "vendor $/token"


def _predicted(output: str, expect: Any, passed: bool, labels: list[str]) -> str:
    """Best-effort predicted label for the per-case classification view.

    The pass/fail verdict comes from the configured check (authoritative); this
    only labels *what* the target answered so a confusion view can be drawn.
    """
    if passed:
        return str(expect)
    no = _norm(output)
    first = (str(output).strip().split() or ["?"])[0]
    normalized_first = _norm(first.rstrip(":"))
    for label in labels:
        if normalized_first == _norm(label):
            return label
    for label in labels:
        if label != str(expect) and _norm(label) and _norm(label) in no:
            return label
    if len(labels) == 2:
        return next(label for label in labels if label != str(expect))
    return first[:24]


def run_payload(body: dict, case_progress=None) -> dict:
    from .pricing import load_pricing
    from .runner import run_benchmark

    task = body["task"]
    target_ids = body.get("targets") or []
    cases = body.get("cases") or []
    concurrency = int(body.get("concurrency", 8))

    cfg = _build_cfg(task, target_ids, cases, sandbox=body.get("sandbox"))
    pricing = load_pricing()
    report = run_benchmark(
        cfg,
        concurrency=concurrency,
        case_progress=case_progress,
    )

    labels = sorted({str(c.expect) for c in cfg.cases})
    rows = []
    for r in report.results:
        ins = [c.input_tokens for c in r.cases]
        outs = [c.output_tokens for c in r.cases]
        tokens_in = sum(ins) if ins and all(x is not None for x in ins) else None
        tokens_out = sum(outs) if outs and all(x is not None for x in outs) else None

        cps = r.cost_per_success  # number | inf | None
        cps_inf = cps == float("inf")
        per_case = [{
            "i": i,
            "input": c.case_input,
            "expect": c.expect,
            "predicted": _predicted(c.output, c.expect, c.passed, labels),
            "correct": c.passed,
            "output": c.output,
            "inTok": c.input_tokens,
            "outTok": c.output_tokens,
            "error": c.error,
        } for i, c in enumerate(r.cases)]

        first_error = next((c.error for c in r.cases if c.error), None)
        rows.append({
            "id": r.target_id,
            "vendor": vendor_of(r.target_id),
            "type": r.target_type,
            "basis": _result_basis(pricing, r.target_id, r.target_type),
            "passes": r.passes,
            "n": r.n,
            "passRate": r.pass_rate,
            "tokensIn": tokens_in,
            "tokensOut": tokens_out,
            "perCase": per_case,
            "costRun": r.cost_per_run,
            "costSuccess": None if (cps is None or cps_inf) else cps,
            "costSuccessInf": cps_inf,
            "latency": r.mean_latency,
            "priced": r.cost_known,
            "errors": r.errors,
            "note": (r.cost_note or first_error),
        })

    return {
        "rows": rows,
        "meta": {
            "nCases": len(cfg.cases),
            "configFingerprint": "cfg:" + report.fingerprint,
            "pricingFingerprint": "px:" + report.pricing_fingerprint,
        },
    }


def stream_run_payload(body: dict, emit) -> dict:
    """Run a benchmark and emit JSON-serializable lifecycle events."""
    target_ids = body.get("targets") or []
    cases = body.get("cases") or []
    # In sandbox mode the single command target replaces the model list.
    n_targets = 1 if body.get("sandbox") is not None else len(target_ids)
    total = n_targets * len(cases)
    concurrency = int(body.get("concurrency", 8))
    started = time.monotonic()
    completed = passes = errors = 0

    emit({
        "type": "start",
        "completed": 0,
        "total": total,
        "targets": n_targets,
        "cases": len(cases),
        "concurrency": concurrency,
    })

    def on_case(event) -> None:
        nonlocal completed, passes, errors
        completed += 1
        passes += int(event.passed)
        errors += int(event.error)
        elapsed = time.monotonic() - started
        rate = completed / elapsed if elapsed > 0 else 0.0
        eta = (total - completed) / rate if rate > 0 else None
        emit({
            "type": "progress",
            "completed": completed,
            "total": total,
            "percent": round((completed / total * 100) if total else 100.0, 1),
            "target": event.target_id,
            "targetIndex": event.target_index,
            "targetCount": event.target_count,
            "targetCompleted": event.target_completed,
            "targetTotal": event.target_total,
            "caseIndex": event.case_index,
            "passes": passes,
            "errors": errors,
            "elapsedSec": round(elapsed, 1),
            "etaSec": round(eta, 1) if eta is not None else None,
        })

    result = run_payload(body, case_progress=on_case)
    emit({
        "type": "result",
        "completed": total,
        "total": total,
        "elapsedSec": round(time.monotonic() - started, 1),
        "data": result,
    })
    return result


# ---------------------------------------------------------------- HTTP glue

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".jsx": "text/babel; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}

_ROUTES = {
    "/api/estimate": estimate_payload,
    "/api/run": run_payload,
    "/api/suggest-cases": suggest_cases_payload,
}


class _Handler(BaseHTTPRequestHandler):
    server_version = "costbench"

    def log_message(self, *args):  # quiet by default
        pass

    def _send_json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _request_is_local(self) -> bool:
        host = self.headers.get("Host", "")
        if not _is_local_http_authority(host):
            self._send_json({"error": "forbidden host"}, 403)
            return False
        if not _is_allowed_origin(self.headers.get("Origin")):
            self._send_json({"error": "forbidden origin"}, 403)
            return False
        return True

    def _read_json_body(self, path: str) -> dict | None:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._send_json({"error": "Content-Type must be application/json"}, 415)
            return None
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            self._send_json({"error": "invalid Content-Length"}, 400)
            return None
        if length < 0 or length > MAX_BODY_BYTES:
            self._send_json({"error": "request body too large"}, 413)
            return None
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
            return validate_request(path, body)
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON"}, 400)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
        return None

    def do_GET(self) -> None:
        if not self._request_is_local():
            return
        path = self.path.split("?", 1)[0]
        if path == "/api/bootstrap":
            try:
                self._send_json(bootstrap_payload())
            except Exception as exc:  # noqa: BLE001
                print(f"costbench server error: {type(exc).__name__}: {exc}", file=sys.stderr)
                self._send_json({"error": "internal server error"}, 500)
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        if not self._request_is_local():
            return
        path = self.path.split("?", 1)[0]
        if path == "/api/run-stream":
            self._handle_run_stream()
            return
        handler = _ROUTES.get(path)
        if handler is None:
            self._send_json({"error": "not found"}, 404)
            return
        body = self._read_json_body(path)
        if body is None:
            return
        try:
            self._send_json(handler(body))
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001 — log details server-side only
            print(f"costbench server error: {type(exc).__name__}: {exc}", file=sys.stderr)
            self._send_json({"error": "internal server error"}, 500)

    def _handle_run_stream(self) -> None:
        body = self._read_json_body("/api/run-stream")
        if body is None:
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def emit(event: dict) -> None:
            line = json.dumps(event, separators=(",", ":")).encode("utf-8") + b"\n"
            self.wfile.write(line)
            self.wfile.flush()

        try:
            stream_run_payload(body, emit)
        except Exception as exc:  # noqa: BLE001 — errors belong in the stream
            print(f"costbench server error: {type(exc).__name__}: {exc}", file=sys.stderr)
            try:
                emit({"type": "error", "error": "internal server error"})
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _serve_static(self, path: str) -> None:
        rel = "costbench.html" if path in ("/", "") else path.lstrip("/")
        target = (UI_DIR / rel).resolve()
        # Path-traversal guard: stay inside UI_DIR.
        if UI_DIR.resolve() not in target.parents and target != UI_DIR.resolve():
            self._send_json({"error": "forbidden"}, 403)
            return
        if not target.is_file():
            self._send_json({"error": "not found"}, 404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    """Start the loopback-only UI server (blocking).

    The API can spend provider credits using keys loaded into this process, so
    it is deliberately not an unauthenticated network service.
    """
    if not UI_DIR.is_dir():
        raise RuntimeError(f"UI assets not found at {UI_DIR}")
    if not _is_loopback_host(host) and not _public_host():
        raise ValueError(
            "costbench serve is local-only; bind to 127.0.0.1, ::1, or localhost "
            "(set COSTBENCH_PUBLIC_HOST=<domain> to allow a hosted, keyless deploy)"
        )
    httpd = ThreadingHTTPServer((host, port), _Handler)
    url = f"http://{host}:{port}/"
    print(f"costbench UI → {url}  (Ctrl-C to stop)")
    if open_browser:
        try:
            import webbrowser

            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        except Exception:  # noqa: BLE001 — opening a browser is best-effort
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        httpd.server_close()
