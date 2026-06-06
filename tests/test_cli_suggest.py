from pathlib import Path
from types import SimpleNamespace

from costbench.cli import main

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO = str(REPO_ROOT / "examples" / "offline" / "demo.yaml")


def test_suggest_runs_and_exits_zero(capsys):
    rc = main(["suggest", "coding"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "costbench suggest" in out
    assert "ground truth" in out


def test_suggest_aa_source_warns_and_exits_nonzero(capsys):
    rc = main(["suggest", "coding", "--priors-source", "artificialanalysis"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "ARTIFICIAL_ANALYSIS_API_KEY" in out


def test_suggest_can_analyze_config(monkeypatch, capsys):
    analysis = SimpleNamespace(
        task_type="general",
        category="classification",
        complexity="low",
        confidence=0.9,
        reason="Constrained output.",
        signals=("short inputs",),
        analyzer_model="qwen/test",
        input_tokens=100,
        output_tokens=20,
        cost=None,
        cost_basis="unknown",
    )
    monkeypatch.setattr(
        "costbench.analyze.analyze_config",
        lambda config, analyzer_model, pricing: analysis,
    )

    rc = main(
        [
            "suggest",
            "--config",
            DEMO,
            "--analyzer-model",
            "qwen/test",
        ]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "analysis disclosure" in out
    assert "complexity low" in out
    assert "costbench suggest — general" in out


def test_suggest_analyzer_requires_config(capsys):
    rc = main(["suggest", "--analyzer-model", "qwen/test"])

    assert rc == 1
    assert "requires --config" in capsys.readouterr().out


def test_estimate_offline_demo_no_network(capsys):
    rc = main(["estimate", DEMO])
    assert rc == 0
    out = capsys.readouterr().out
    assert "costbench estimate" in out
    assert "Estimates only" in out
