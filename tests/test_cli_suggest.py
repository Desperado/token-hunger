from pathlib import Path

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


def test_estimate_offline_demo_no_network(capsys):
    rc = main(["estimate", DEMO])
    assert rc == 0
    out = capsys.readouterr().out
    assert "costbench estimate" in out
    assert "Estimates only" in out
