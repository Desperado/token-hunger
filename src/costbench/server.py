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
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

UI_DIR = Path(__file__).resolve().parent / "ui"

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


def _build_cfg(task: dict, target_ids: list[str], cases: list[dict]):
    """Build a real Config from the posted task/targets/cases (no file written)."""
    from .config import build_config

    raw = {
        "name": task.get("name", "costbench"),
        "task": {
            "system": task.get("system"),
            "prompt_template": task.get("promptTemplate", "{input}"),
        },
        "check": task.get("check", "exact"),
        "targets": [{"type": "model", "id": tid} for tid in target_ids],
        "cases": [{"input": c["input"], "expect": c["expect"]} for c in cases],
    }
    return build_config(raw, base_dir=Path.cwd())


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
    examples = presets()
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
        "connectors": _CONNECTORS,
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

    cfg = _build_cfg(task, target_ids, cases)
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
    for label in labels:
        if label != str(expect) and _norm(label) and _norm(label) in no:
            return label
    if len(labels) == 2:
        return next(label for label in labels if label != str(expect))
    first = (str(output).strip().split() or ["?"])[0]
    return first[:24]


def run_payload(body: dict, case_progress=None) -> dict:
    from .pricing import load_pricing
    from .runner import run_benchmark

    task = body["task"]
    target_ids = body.get("targets") or []
    cases = body.get("cases") or []
    concurrency = int(body.get("concurrency", 4))

    cfg = _build_cfg(task, target_ids, cases)
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
    total = len(target_ids) * len(cases)
    concurrency = int(body.get("concurrency", 4))
    started = time.monotonic()
    completed = passes = errors = 0

    emit({
        "type": "start",
        "completed": 0,
        "total": total,
        "targets": len(target_ids),
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

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/bootstrap":
            try:
                self._send_json(bootstrap_payload())
            except Exception as exc:  # noqa: BLE001
                self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/run-stream":
            self._handle_run_stream()
            return
        handler = _ROUTES.get(path)
        if handler is None:
            self._send_json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            self._send_json({"error": f"invalid JSON: {exc}"}, 400)
            return
        try:
            self._send_json(handler(body))
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the server
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def _handle_run_stream(self) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            self._send_json({"error": f"invalid JSON: {exc}"}, 400)
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
            try:
                emit({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
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
    """Start the UI server (blocking)."""
    if not UI_DIR.is_dir():
        raise RuntimeError(f"UI assets not found at {UI_DIR}")
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
