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
