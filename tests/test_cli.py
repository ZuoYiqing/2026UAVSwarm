"""CLI skeleton tests aligned with currently supported commands."""
from __future__ import annotations

from uav_runtime.console.cli import build_parser, main


def test_parser_accepts_supported_command_submit_action() -> None:
    args = build_parser().parse_args(["submit-action", "hover"])
    assert args.cmd == "submit-action"
    assert args.action == "hover"


def test_main_accepts_show_status_command() -> None:
    rc = main(["show-status"])
    assert rc == 0


def test_main_accepts_submit_action_command() -> None:
    rc = main(["submit-action", "takeoff"])
    assert rc == 0
