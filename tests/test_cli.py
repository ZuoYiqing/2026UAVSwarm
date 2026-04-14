"""CLI skeleton tests aligned with currently supported commands."""
from __future__ import annotations

from uav_runtime.console.cli import build_parser, main
from uav_runtime.runtime.adapter_selection import DEFAULT_ADAPTER_NAME


def test_parser_accepts_supported_command_submit_action() -> None:
    args = build_parser().parse_args(["submit-action", "hover"])
    assert args.cmd == "submit-action"
    assert args.action == "hover"
    assert args.adapter == DEFAULT_ADAPTER_NAME


def test_main_accepts_show_status_command() -> None:
    rc = main(["show-status"])
    assert rc == 0


def test_main_accepts_submit_action_command() -> None:
    rc = main(["submit-action", "takeoff"])
    assert rc == 0


def test_parser_accepts_demo_flags_and_pretty() -> None:
    args = build_parser().parse_args([
        "submit-action",
        "goto",
        "--demo-link-state",
        "lost",
        "--risk-hint",
        "5",
        "--pretty",
    ])
    assert args.cmd == "submit-action"
    assert args.demo_link_state == "lost"
    assert args.risk_hint == 5
    assert args.pretty is True


def test_main_accepts_submit_mission_command() -> None:
    rc = main(["submit-mission", "--mission-id", "demo-mission"])
    assert rc == 0


def test_parser_accepts_adapter_override_for_submit_action() -> None:
    args = build_parser().parse_args(["submit-action", "hover", "--adapter", "mavlink"])
    assert args.adapter == "mavlink"


def test_main_accepts_submit_action_with_mavlink_adapter() -> None:
    rc = main(["submit-action", "takeoff", "--adapter", "mavlink"])
    assert rc == 0
