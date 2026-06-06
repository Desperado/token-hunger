"""Render results. The report is a first-class feature, not polish — the
markdown/JSON artifact is the thing people share, and the shareable moment is
the gap between 'cheapest per call' and 'cheapest per correct answer'.
"""

from __future__ import annotations

import json
from html import escape
from typing import Optional

from rich.console import Console
from rich.table import Table

from .runner import BenchmarkReport, TargetResult

METHODOLOGY_URL = (
    "https://github.com/Desperado/token-hunger/blob/master/METHODOLOGY.md"
)


def _fmt_cost(value: Optional[float]) -> str:
    if value is None:
        return "—"
    if value == float("inf"):
        return "∞ (0 passed)"
    if value == 0:
        return "$0"
    if value < 0.01:
        return f"${value:.6f}"
    return f"${value:,.4f}"


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def render_terminal(report: BenchmarkReport, console: Optional[Console] = None) -> None:
    console = console or Console()
    table = Table(title=f"costbench — {report.name}", title_style="bold")
    table.add_column("Target", style="bold")
    table.add_column("Type")
    table.add_column("Pass", justify="right")
    table.add_column("Cost basis")
    table.add_column("Cost/run", justify="right")
    table.add_column("Cost/SUCCESS", justify="right", style="bold cyan")
    table.add_column("Latency", justify="right")

    ranked = report.ranked_by_cost_per_success()
    best_id = ranked[0].target_id if ranked else None
    for r in ranked:
        row_style = "green" if r.target_id == best_id else None
        errors = f" ({r.errors} err)" if r.errors else ""
        table.add_row(
            r.target_id,
            r.target_type,
            f"{_fmt_pct(r.pass_rate)}{errors}",
            r.cost_basis,
            _fmt_cost(r.cost_per_run),
            _fmt_cost(r.cost_per_success),
            f"{r.mean_latency:.2f}s",
            style=row_style,
        )

    console.print(table)
    console.print(
        f"[dim]Headline = Cost/SUCCESS (total cost ÷ correct answers). "
        f"Config {report.fingerprint}; pricing {report.pricing_fingerprint or 'n/a'}. "
        f"Methodology: {METHODOLOGY_URL}[/dim]"
    )
    for r in ranked:
        if r.n_unpriced > 0:
            console.print(
                f"[yellow]{r.target_id}: {r.n_unpriced} of {r.n} cases unpriced — "
                f"cost columns reflect only the {r.n_priced} priced cases.[/yellow]"
            )
    for r in ranked:
        if r.cost_note:
            console.print(f"[dim]{r.target_id} cost assumption: {r.cost_note}[/dim]")


def _row_dict(r: TargetResult) -> dict:
    cps = r.cost_per_success
    return {
        "target": r.target_id,
        "type": r.target_type,
        "cases": r.n,
        "passes": r.passes,
        "errors": r.errors,
        "pass_rate": round(r.pass_rate, 4),
        "cost_basis": r.cost_basis,
        "cost_note": r.cost_note,
        "n_priced": r.n_priced,
        "n_unpriced": r.n_unpriced,
        "cost_per_run": r.cost_per_run,
        "cost_per_success": None if cps == float("inf") else cps,
        "cost_per_success_infinite": cps == float("inf"),
        "mean_latency_s": round(r.mean_latency, 3),
    }


def to_json(report: BenchmarkReport) -> str:
    payload = {
        "name": report.name,
        "config_fingerprint": report.fingerprint,
        "pricing_fingerprint": report.pricing_fingerprint,
        "headline_metric": "cost_per_success",
        "methodology": METHODOLOGY_URL,
        "results": [_row_dict(r) for r in report.ranked_by_cost_per_success()],
    }
    return json.dumps(payload, indent=2)


def to_markdown(report: BenchmarkReport) -> str:
    lines = [
        f"# costbench results — {report.name}",
        "",
        "Headline metric: **cost per success** (total cost ÷ number of correct "
        "answers). The cheapest model per call is not always the cheapest per "
        "correct answer.",
        "",
        "| Target | Type | Pass | Cost basis | Cost/run | Cost/SUCCESS | Latency |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: |",
    ]
    for r in report.ranked_by_cost_per_success():
        errors = f" ({r.errors} err)" if r.errors else ""
        lines.append(
            f"| {r.target_id} | {r.target_type} | {_fmt_pct(r.pass_rate)}{errors} "
            f"| {r.cost_basis} | {_fmt_cost(r.cost_per_run)} "
            f"| **{_fmt_cost(r.cost_per_success)}** | {r.mean_latency:.2f}s |"
        )
    lines += [
        "",
        f"_Ranked by cost per success. Config fingerprint `{report.fingerprint}`; "
        f"pricing fingerprint `{report.pricing_fingerprint or 'n/a'}`._",
        "",
        "Costs for `model` targets are computed from the committed pricing table "
        "(USD/token). Costs for `endpoint`/`command` targets use the basis "
        "declared in the config and are **not** blended with per-token costs.",
        "",
        f"Reproduce: clone the repo, use the same config, run `costbench run`. "
        f"Methodology: {METHODOLOGY_URL}",
    ]
    notes = [
        f"- `{r.target_id}` cost assumption: {r.cost_note}"
        for r in report.ranked_by_cost_per_success()
        if r.cost_note
    ]
    notes += [
        f"- `{r.target_id}`: {r.n_unpriced} of {r.n} cases unpriced — cost "
        f"columns reflect only the {r.n_priced} priced cases."
        for r in report.ranked_by_cost_per_success()
        if r.n_unpriced > 0
    ]
    if notes:
        lines += ["", "## Cost assumptions", "", *notes]
    return "\n".join(lines)


def to_html(report: BenchmarkReport) -> str:
    rows = ""
    for r in report.ranked_by_cost_per_success():
        rows += (
            "<tr>"
            f"<td>{escape(r.target_id)}</td><td>{escape(r.target_type)}</td>"
            f"<td>{_fmt_pct(r.pass_rate)}</td><td>{escape(r.cost_basis)}</td>"
            f"<td>{_fmt_cost(r.cost_per_run)}</td>"
            f"<td><b>{_fmt_cost(r.cost_per_success)}</b></td>"
            f"<td>{r.mean_latency:.2f}s</td>"
            "</tr>\n"
        )
    report_name = escape(report.name)
    notes = "".join(
        f"<li><code>{escape(r.target_id)}</code>: {escape(r.cost_note)}</li>"
        for r in report.ranked_by_cost_per_success()
        if r.cost_note
    )
    notes_html = f"<h2>Cost assumptions</h2><ul>{notes}</ul>" if notes else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>costbench — {report_name}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:840px;margin:2rem auto;padding:0 1rem}}
table{{border-collapse:collapse;width:100%}}
th,td{{padding:.5rem .75rem;border-bottom:1px solid #ddd;text-align:right}}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2),
th:nth-child(4),td:nth-child(4){{text-align:left}}
caption{{font-weight:700;font-size:1.2rem;margin-bottom:.5rem}}
.note{{color:#666;font-size:.85rem}}
</style></head><body>
<table><caption>costbench — {report_name}</caption>
<thead><tr><th>Target</th><th>Type</th><th>Pass</th><th>Cost basis</th>
<th>Cost/run</th><th>Cost/SUCCESS</th><th>Latency</th></tr></thead>
<tbody>
{rows}</tbody></table>
<p class="note">Headline = cost per success (total cost ÷ correct answers).
Config fingerprint {report.fingerprint}.
Pricing fingerprint {report.pricing_fingerprint or "n/a"}.
<a href="{METHODOLOGY_URL}">Methodology</a>.</p>
{notes_html}
</body></html>"""


def write_report(report: BenchmarkReport, fmt: str, path: str) -> None:
    renderers = {"markdown": to_markdown, "md": to_markdown, "json": to_json,
                 "html": to_html}
    if fmt not in renderers:
        raise ValueError(f"unknown report format {fmt!r}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(renderers[fmt](report))


# --- estimate rendering ------------------------------------------------------

ESTIMATE_FOOTER = (
    "Estimates only — NOT verified costs. Input cost is computed from a "
    "request-aware token estimate; output cost is a worst-case ceiling from "
    "max_output_tokens "
    "(or a calibrated p50–p90 range when run history exists). Estimates round "
    "UP. Run `costbench run <config>` for actual billed cost."
)


def _fmt_output_range(e) -> str:
    if e.output_cost_low is None or e.output_cost_high is None:
        return "—"
    if e.output_cost_low == e.output_cost_high:
        return f"≤ {_fmt_cost(e.output_cost_high)}"
    return f"{_fmt_cost(e.output_cost_low)} – {_fmt_cost(e.output_cost_high)}"


def _fmt_percase_range(e) -> str:
    if e.per_case_low is None or e.per_case_high is None:
        return "—"
    if e.per_case_low == e.per_case_high:
        return f"≤ {_fmt_cost(e.per_case_high)}"
    return f"{_fmt_cost(e.per_case_low)} – {_fmt_cost(e.per_case_high)}"


def render_estimate_terminal(estimates, console=None, config_fp="", pricing_fp=""):
    console = console or Console()
    table = Table(title="costbench estimate", title_style="bold")
    table.add_column("Target", style="bold")
    table.add_column("Type")
    table.add_column("Cost basis")
    table.add_column("Input cost (tokenized)", justify="right")
    table.add_column("Output cost (range)", justify="right")
    table.add_column("Est. cost/case (range)", justify="right", style="bold cyan")

    for e in estimates:
        table.add_row(
            e.target_id,
            e.target_type,
            e.cost_basis,
            _fmt_cost(e.input_cost_total) if e.input_cost_total is not None else "—",
            _fmt_output_range(e),
            _fmt_percase_range(e),
        )
    console.print(table)
    console.print(
        f"[dim]{ESTIMATE_FOOTER} Config {config_fp or 'n/a'}; "
        f"pricing {pricing_fp or 'n/a'}.[/dim]"
    )
    for e in estimates:
        bits = []
        if e.tokenizer_method:
            bits.append(
                f"tokenizer {e.tokenizer_method} "
                f"({'exact' if e.input_exact else 'approx'})"
            )
        if not e.calibrated and e.output_ceiling and e.priced and e.target_type == "model":
            bits.append(
                f"output ceiling {e.output_ceiling} tok via {e.ceiling_source}"
            )
        if e.note:
            bits.append(e.note)
        if bits:
            console.print(f"[dim]{e.target_id}: {'; '.join(bits)}[/dim]")


def _estimate_row_dict(e) -> dict:
    return {
        "target": e.target_id,
        "type": e.target_type,
        "n_cases": e.n_cases,
        "priced": e.priced,
        "cost_basis": e.cost_basis,
        "calibrated": e.calibrated,
        "input_cost_total": e.input_cost_total,
        "output_cost_low": e.output_cost_low,
        "output_cost_high": e.output_cost_high,
        "per_case_low": e.per_case_low,
        "per_case_high": e.per_case_high,
        "output_ceiling": e.output_ceiling,
        "ceiling_source": e.ceiling_source,
        "tokenizer_method": e.tokenizer_method,
        "input_exact": e.input_exact,
        "note": e.note,
    }


def estimate_to_json(estimates, name, config_fp, pricing_fp) -> str:
    payload = {
        "kind": "estimate",
        "schema_version": 1,
        "name": name,
        "config_fingerprint": config_fp,
        "pricing_fingerprint": pricing_fp,
        "disclaimer": ESTIMATE_FOOTER,
        "estimates": [_estimate_row_dict(e) for e in estimates],
    }
    return json.dumps(payload, indent=2)


def estimate_to_markdown(estimates, name, config_fp, pricing_fp) -> str:
    lines = [
        f"# costbench estimate — {name}",
        "",
        "**Estimates, not verified costs.** Input cost is computed from a "
        "request-aware token estimate; output cost is a worst-case ceiling "
        "(or a calibrated p50–p90 range when run history exists). Estimates "
        "round UP.",
        "",
        "| Target | Type | Cost basis | Input cost (tokenized) | Output cost (range) | Est. cost/case (range) |",
        "| --- | --- | --- | ---: | ---: | ---: |",
    ]
    for e in estimates:
        inp = _fmt_cost(e.input_cost_total) if e.input_cost_total is not None else "—"
        lines.append(
            f"| {e.target_id} | {e.target_type} | {e.cost_basis} | {inp} "
            f"| {_fmt_output_range(e)} | **{_fmt_percase_range(e)}** |"
        )
    lines += [
        "",
        f"_Config fingerprint `{config_fp or 'n/a'}`; pricing fingerprint "
        f"`{pricing_fp or 'n/a'}`._",
        "",
        ESTIMATE_FOOTER,
    ]
    notes = [f"- `{e.target_id}`: {e.note}" for e in estimates if e.note]
    if notes:
        lines += ["", "## Notes", "", *notes]
    return "\n".join(lines)


def write_estimate_report(estimates, fmt, path, name="", config_fp="", pricing_fp=""):
    if fmt in ("md", "markdown"):
        text = estimate_to_markdown(estimates, name, config_fp, pricing_fp)
    elif fmt == "json":
        text = estimate_to_json(estimates, name, config_fp, pricing_fp)
    else:
        raise ValueError(f"unknown estimate report format {fmt!r}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
