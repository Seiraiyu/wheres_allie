from typer.testing import CliRunner

from wheres_allie.cli import app


def test_help_lists_serve():
    res = CliRunner().invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "serve" in res.output
