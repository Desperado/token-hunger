import os

from costbench.cli import _load_dotenv


def test_load_dotenv_parses_and_does_not_override(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "\n".join([
            "# a comment",
            "",
            "ANTHROPIC_API_KEY=sk-from-file",
            "export OPENAI_API_KEY=sk-exported",
            'QUOTED="quoted value"',
            "ALREADY_SET=from-file",
        ]),
        encoding="utf-8",
    )
    env.chmod(0o600)
    # a real env value must win over the file
    monkeypatch.setenv("ALREADY_SET", "from-shell")
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "QUOTED"):
        monkeypatch.delenv(k, raising=False)

    loaded = _load_dotenv(env)

    assert loaded == 3  # ALREADY_SET skipped (shell wins)
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-from-file"
    assert os.environ["OPENAI_API_KEY"] == "sk-exported"  # `export ` stripped
    assert os.environ["QUOTED"] == "quoted value"  # quotes stripped
    assert os.environ["ALREADY_SET"] == "from-shell"  # not overridden


def test_load_dotenv_missing_file_is_noop(tmp_path):
    assert _load_dotenv(tmp_path / "nope.env") == 0


def test_load_dotenv_warns_on_permissive_permissions(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("PRIVATE_TOKEN=secret\n", encoding="utf-8")
    env.chmod(0o644)
    monkeypatch.delenv("PRIVATE_TOKEN", raising=False)
    messages = []
    monkeypatch.setattr("costbench.cli.console.print", messages.append)

    assert _load_dotenv(env) == 1
    assert any("chmod 600" in message for message in messages)
