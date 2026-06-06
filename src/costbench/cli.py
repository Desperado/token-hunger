"""costbench command-line interface.

    costbench run <config.yaml>       run a benchmark, print the table
    costbench estimate <config.yaml>  predict cost WITHOUT running targets
    costbench suggest [task-type]     suggest models manually or via analysis
    costbench pull <pull.yaml>        pull cases from an external source to a dump
    costbench init [path]             write a ready-to-run example config
    costbench models                  list models in the pricing table
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from importlib import resources
from pathlib import Path

from rich.console import Console
from rich.markup import escape

from . import __version__

console = Console()


def _apply_case_limit(config, max_cases: int) -> None:
    if max_cases < 0:
        raise ValueError("--max-cases cannot be negative")
    if not max_cases or max_cases >= len(config.cases):
        return
    config.cases = config.cases[:max_cases]
    subset = f"{config.fingerprint}:first-cases:{max_cases}"
    config.fingerprint = hashlib.sha256(subset.encode("utf-8")).hexdigest()[:12]


def _cmd_run(args: argparse.Namespace) -> int:
    from .config import load_config
    from .pricing import load_pricing
    from .report import render_terminal, write_report
    from .runner import run_benchmark

    config = load_config(args.config)
    _apply_case_limit(config, args.max_cases)

    # Warn loudly when a model target has no committed price — the cost number
    # is the credibility, so silence here would be dishonest.
    pricing = load_pricing(config.pricing_path).with_overrides(config.pricing_overrides)
    for t in config.targets:
        if t.type == "model" and t.id not in pricing:
            console.print(
                f"[yellow]warning:[/yellow] no price for {t.id!r} in the pricing "
                f"table — its cost will show as unknown. Add it to pricing.yaml "
                f"or a 'pricing:' block in your config."
            )

    n_runs = len(config.targets) * len(config.cases)
    console.print(
        f"[bold]{config.name}[/bold]: {len(config.targets)} targets × "
        f"{len(config.cases)} cases = {n_runs} runs"
    )

    with console.status("running…"):
        report = run_benchmark(config, concurrency=args.concurrency)

    # Best-effort calibration history. NEVER fail a run because history couldn't
    # be written — a later `estimate` simply falls back to the worst-case ceiling.
    if not getattr(args, "no_history", False):
        _record_history(config, report)

    console.print()
    render_terminal(report, console)

    if args.report:
        out = args.out or f"costbench-report.{ 'md' if args.report in ('md','markdown') else args.report }"
        write_report(report, args.report, out)
        console.print(f"[green]report written:[/green] {out}")

    # Non-zero exit if any target produced errors, so CI-ish callers notice.
    if any(r.errors for r in report.results):
        return 2
    return 0


def _record_history(config, report) -> None:
    """Append observed token usage from a run to the calibration history file.

    Best-effort: only records cases that produced a real cost (real usage), and
    warns rather than raising on any failure."""
    try:
        from datetime import datetime, timezone

        from .history import Observation, append_observations

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        obs = []
        for r in report.results:
            for c in r.cases:
                if c.cost is None or c.input_tokens is None or c.output_tokens is None:
                    continue
                obs.append(
                    Observation(
                        config_fingerprint=config.fingerprint,
                        target_id=r.target_id,
                        model_id=r.target_id,
                        input_tokens=int(c.input_tokens),
                        output_tokens=int(c.output_tokens),
                        cost=c.cost,
                        passed=c.passed,
                        ts=ts,
                        pricing_fingerprint=report.pricing_fingerprint,
                    )
                )
        append_observations(obs)
    except Exception as exc:  # noqa: BLE001 — history is best-effort
        console.print(
            f"[dim]history not written ({type(exc).__name__}); estimates will "
            f"fall back to the worst-case ceiling.[/dim]"
        )


def _cmd_estimate(args: argparse.Namespace) -> int:
    from .config import load_config
    from .estimate import estimate_config
    from .history import load_observations
    from .limits import load_model_limits
    from .limits_gate import check_estimate_quota
    from .pricing import load_pricing
    from .report import render_estimate_terminal, write_estimate_report

    config = load_config(args.config)

    # Free-tier seam (no billing): a future host can deny here. Default: allow.
    decision = check_estimate_quota(config)
    if not decision.allowed:
        console.print(f"[red]{decision.reason}[/red]")
        return 3

    pricing = load_pricing(config.pricing_path).with_overrides(config.pricing_overrides)
    limits = load_model_limits()
    try:
        history = load_observations()
    except Exception:  # noqa: BLE001 — history is best-effort on read too
        history = []

    estimates = estimate_config(
        config,
        pricing,
        limits,
        history=history,
        max_output_override=args.max_output_tokens,
    )

    for t in config.targets:
        if t.type == "model" and t.id not in pricing:
            console.print(
                f"[yellow]warning:[/yellow] no price for {t.id!r} in the pricing "
                f"table — its cost will show as unknown. Add it to pricing.yaml "
                f"or a 'pricing:' block in your config."
            )

    console.print()
    render_estimate_terminal(
        estimates, console, config_fp=config.fingerprint,
        pricing_fp=pricing.fingerprint,
    )

    if args.report:
        out = args.out or f"costbench-estimate.{'md' if args.report in ('md','markdown') else args.report}"
        write_estimate_report(
            estimates, args.report, out, name=config.name,
            config_fp=config.fingerprint, pricing_fp=pricing.fingerprint,
        )
        console.print(f"[green]estimate report written:[/green] {out}")

    return 0


def _cmd_suggest(args: argparse.Namespace) -> int:
    from .analyze import analyze_config, render_analysis_terminal
    from .config import load_config
    from .pricing import load_pricing
    from .priors import load_priors, rank_models, render_suggest_terminal

    pricing = load_pricing()
    task_type = args.task_type
    if args.analyzer_model:
        if not args.config:
            raise ValueError("--analyzer-model requires --config")
        config = load_config(args.config)
        console.print(
            f"[yellow]analysis disclosure:[/yellow] sending task instructions "
            f"and up to 5 case inputs to {args.analyzer_model!r}; expected "
            f"answers, target definitions, and pricing are excluded."
        )
        analysis = analyze_config(config, args.analyzer_model, pricing=pricing)
        task_type = analysis.task_type
        render_analysis_terminal(analysis, console)
    elif args.config:
        raise ValueError("--config requires --analyzer-model")
    if not task_type:
        raise ValueError(
            "provide a task type or use --config with --analyzer-model"
        )

    try:
        priors = load_priors(args.priors_source)
    except NotImplementedError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        return 1

    ranked, unranked = rank_models(task_type, priors, pricing, top=args.top)
    render_suggest_terminal(task_type, ranked, unranked, console)
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    dest = Path(args.path or "costbench.yaml")
    if dest.exists() and not args.force:
        console.print(f"[red]{dest} already exists[/red] (use --force to overwrite)")
        return 1
    example = resources.files("costbench").joinpath("examples/classification.yaml")
    dest.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    console.print(f"[green]wrote {dest}[/green] — set your API keys and run "
                  f"`costbench run {dest}`")
    return 0


def _cmd_pull(args: argparse.Namespace) -> int:
    from pathlib import Path as _Path

    from .connectors import load_pull_config, pull

    pull_config = load_pull_config(args.config)
    result = pull(pull_config, base_dir=_Path(args.config).resolve().parent)

    console.print(
        f"[green]pulled[/green] {result.written} case(s) from "
        f"[bold]{result.source}[/bold] → {result.out_path}"
    )
    if result.dropped_unlabeled:
        console.print(
            f"[yellow]dropped {result.dropped_unlabeled} unlabeled row(s)[/yellow] "
            f"(of {result.rows} fetched) — they would not be scored"
        )
    console.print(
        f"[dim]content fingerprint {result.fingerprint} "
        f"(folded into the run fingerprint when this file is a 'cases.source: file')[/dim]"
    )
    console.print(
        f"point a run config's cases at it:\n"
        f"  cases:\n    source: file\n    path: {result.out_path}"
    )
    return 0


def _cmd_models(args: argparse.Namespace) -> int:
    from .pricing import load_pricing

    pricing = load_pricing()
    console.print("[bold]Models in the pricing table[/bold] (USD per 1M tokens):")
    for mid in pricing.ids():
        p = pricing.get(mid)
        console.print(f"  {mid:<34} in ${p.input_per_m:<7} out ${p.output_per_m:<7} "
                      f"[dim]verified {p.verified or '?'}[/dim]")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="costbench",
        description="Benchmark LLM targets by cost per successful outcome.",
    )
    parser.add_argument("--version", action="version",
                        version=f"costbench {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run a benchmark from a config file")
    p_run.add_argument("config", help="path to the YAML config")
    p_run.add_argument("--report", choices=["md", "markdown", "html", "json"],
                       help="also write a shareable report in this format")
    p_run.add_argument("--out", help="report output path")
    p_run.add_argument("--concurrency", type=int, default=4,
                       help="parallel calls per target (default 4)")
    p_run.add_argument("--max-cases", type=int, default=0,
                       help="limit number of cases (smoke test)")
    p_run.add_argument("--no-history", action="store_true",
                       help="do not record observed tokens to the calibration history")
    p_run.set_defaults(func=_cmd_run)

    p_est = sub.add_parser("estimate",
                           help="estimate cost from a config WITHOUT running targets")
    p_est.add_argument("config", help="path to the YAML config")
    p_est.add_argument("--max-output-tokens", type=int, default=None,
                       help="override the worst-case output ceiling for all targets")
    p_est.add_argument("--report", choices=["md", "markdown", "json"],
                       help="also write an estimate report")
    p_est.add_argument("--out", help="report output path")
    p_est.set_defaults(func=_cmd_estimate)

    p_sug = sub.add_parser("suggest",
                           help="suggest models to try for a task type (priors, NOT ground truth)")
    p_sug.add_argument("task_type", nargs="?",
                       help="manual type: coding, math, or general")
    p_sug.add_argument("--config",
                       help="benchmark config to classify with an analyzer model")
    p_sug.add_argument("--analyzer-model",
                       help="opt-in LiteLLM model for task analysis, e.g. qwen/qwen3.5-flash")
    p_sug.add_argument("--priors-source", default="seed",
                       choices=["seed", "artificialanalysis"])
    p_sug.add_argument("--top", type=int, default=5)
    p_sug.set_defaults(func=_cmd_suggest)

    p_init = sub.add_parser("init", help="write an example config to start from")
    p_init.add_argument("path", nargs="?", help="destination (default costbench.yaml)")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=_cmd_init)

    p_pull = sub.add_parser(
        "pull",
        help="pull cases from an external source (e.g. SQL) into a local dump",
    )
    p_pull.add_argument("config", help="path to the pull config YAML")
    p_pull.set_defaults(func=_cmd_pull)

    p_models = sub.add_parser("models", help="list models in the pricing table")
    p_models.set_defaults(func=_cmd_models)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        console.print(f"[red]file not found:[/red] {escape(str(exc))}")
        return 1
    except ValueError as exc:
        console.print(f"[red]config error:[/red] {escape(str(exc))}")
        return 1
    except RuntimeError as exc:
        console.print(f"[red]error:[/red] {escape(str(exc))}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
