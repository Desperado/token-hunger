"""costbench command-line interface.

    costbench run <config.yaml>     run a benchmark, print the table
    costbench init [path]           write a ready-to-run example config
    costbench models                list models in the pricing table
"""

from __future__ import annotations

import argparse
import sys
from importlib import resources
from pathlib import Path

from rich.console import Console

from . import __version__

console = Console()


def _cmd_run(args: argparse.Namespace) -> int:
    from .config import load_config
    from .pricing import load_pricing
    from .report import render_terminal, write_report
    from .runner import run_benchmark

    config = load_config(args.config)
    if args.max_cases < 0:
        raise ValueError("--max-cases cannot be negative")
    if args.max_cases:
        config.cases = config.cases[: args.max_cases]

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
    p_run.set_defaults(func=_cmd_run)

    p_init = sub.add_parser("init", help="write an example config to start from")
    p_init.add_argument("path", nargs="?", help="destination (default costbench.yaml)")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=_cmd_init)

    p_models = sub.add_parser("models", help="list models in the pricing table")
    p_models.set_defaults(func=_cmd_models)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        console.print(f"[red]file not found:[/red] {exc}")
        return 1
    except ValueError as exc:
        console.print(f"[red]config error:[/red] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
