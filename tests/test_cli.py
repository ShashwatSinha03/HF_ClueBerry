from clueberry.main import app
from typer.testing import CliRunner

runner = CliRunner()


def test_help_runs() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Clueberry" in result.stdout


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "clueberry" in result.stdout.lower()


def test_info_command() -> None:
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
    assert "Clueberry" in result.stdout
