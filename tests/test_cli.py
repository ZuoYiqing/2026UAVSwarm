from uav_runtime.console.cli import main


def test_cli_health(capsys) -> None:
    code = main(["health"])
    captured = capsys.readouterr().out
    assert code == 0
    assert "status" in captured


def test_cli_plan(capsys) -> None:
    code = main(["plan"])
    captured = capsys.readouterr().out
    assert code == 0
    assert "tasks" in captured
