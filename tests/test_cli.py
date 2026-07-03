"""CLI skeleton tests aligned with currently supported commands."""
from __future__ import annotations

import json

from uav_runtime.console.cli import build_parser, main
from uav_runtime.runtime.adapter_selection import DEFAULT_ADAPTER_NAME


def test_parser_accepts_supported_command_submit_action() -> None:
    args = build_parser().parse_args(["submit-action", "hover"])
    assert args.cmd == "submit-action"
    assert args.action == "hover"
    assert args.adapter == DEFAULT_ADAPTER_NAME
    assert args.backend_mode == "stub"
    assert args.backend_enabled is False


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


def test_parser_accepts_sitl_wiring_flags() -> None:
    args = build_parser().parse_args(
        [
            "submit-action",
            "takeoff",
            "--adapter",
            "mavlink",
            "--backend-mode",
            "sitl",
            "--backend-enabled",
            "--transport-endpoint",
            "udpin:127.0.0.1:14540",
            "--connect-timeout-ms",
            "3500",
            "--timeout-ms",
            "5000",
            "--retry-count",
            "1",
        ]
    )
    assert args.adapter == "mavlink"
    assert args.backend_mode == "sitl"
    assert args.backend_enabled is True
    assert args.transport_endpoint == "udpin:127.0.0.1:14540"
    assert args.connect_timeout_ms == 3500
    assert args.timeout_ms == 5000
    assert args.retry_count == 1


def test_main_accepts_submit_action_with_mavlink_adapter() -> None:
    rc = main(["submit-action", "takeoff", "--adapter", "mavlink"])
    assert rc == 0


def test_main_accepts_submit_action_with_mavlink_sitl_wiring_flags() -> None:
    rc = main([
        "submit-action",
        "takeoff",
        "--adapter",
        "mavlink",
        "--backend-mode",
        "sitl",
    ])
    assert rc == 0


def test_parser_accepts_check_backend_command() -> None:
    args = build_parser().parse_args([
        "check-backend",
        "--backend",
        "px4_sitl",
        "--backend-mode",
        "sitl",
        "--backend-enabled",
        "--transport-endpoint",
        "udpin:127.0.0.1:14540",
    ])
    assert args.cmd == "check-backend"
    assert args.backend == "px4_sitl"
    assert args.backend_mode == "sitl"
    assert args.backend_enabled is True
    assert args.transport_endpoint == "udpin:127.0.0.1:14540"


def test_parser_accepts_smoke_takeoff_command() -> None:
    args = build_parser().parse_args([
        "smoke-takeoff",
        "--backend",
        "px4_sitl",
        "--backend-mode",
        "sitl",
        "--backend-enabled",
        "--transport-endpoint",
        "udpin:127.0.0.1:14540",
        "--altitude-m",
        "3",
        "--connect-timeout-ms",
        "5000",
        "--command-timeout-ms",
        "10000",
        "--observe-timeout-ms",
        "25000",
        "--auto-land",
    ])

    assert args.cmd == "smoke-takeoff"
    assert args.backend == "px4_sitl"
    assert args.backend_mode == "sitl"
    assert args.backend_enabled is True
    assert args.transport_endpoint == "udpin:127.0.0.1:14540"
    assert args.altitude_m == 3
    assert args.command_timeout_ms == 10000
    assert args.observe_timeout_ms == 25000
    assert args.auto_land is True


def test_main_check_backend_outputs_readiness_json(capsys) -> None:
    rc = main(["check-backend", "--backend-enabled"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["backend"] == "px4_sitl"
    assert payload["dependency"]["name"] == "pymavlink"
    assert payload["readiness"] == "not_ready"


def test_parser_accepts_payload_adapter_override_for_submit_action() -> None:
    args = build_parser().parse_args(["submit-action", "health_query", "--adapter", "payload"])

    assert args.cmd == "submit-action"
    assert args.action == "health_query"
    assert args.adapter == "payload"


def test_main_submit_action_with_payload_adapter_outputs_result_and_policy(capsys) -> None:
    rc = main(["submit-action", "health_query", "--adapter", "payload"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["accepted"] is True
    assert payload["result"]["adapter"] == "payload"
    assert payload["result"]["code"] == "payload_placeholder_ok"
    assert payload["result"]["execution_trace"]["device_type"] == "health_monitor"
    assert payload["policy_decision_event"]["decision_code"] == "allow"


def test_main_submit_action_with_payload_adapter_keeps_unsupported_stable(capsys) -> None:
    rc = main(["submit-action", "payload_release", "--adapter", "payload"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["accepted"] is False
    assert payload["result"]["status"] == "blocked"
    assert payload["result"]["adapter"] == ""
    assert payload["result"]["code"] == "REASON_CODE_UNSAFE_PAYLOAD_ACTION_DENIED"
    assert payload["policy_decision_event"]["decision_code"] == "deny"
    assert payload["policy_decision_event"]["primary_reason_code"] == "REASON_CODE_UNSAFE_PAYLOAD_ACTION_DENIED"


def test_parser_accepts_list_capabilities_filters() -> None:
    args = build_parser().parse_args([
        "list-capabilities",
        "--domain",
        "payload",
        "--adapter",
        "payload",
        "--fallback-only",
        "--include-dangerous",
        "--pretty",
    ])
    assert args.cmd == "list-capabilities"
    assert args.domain == "payload"
    assert args.adapter == "payload"
    assert args.fallback_only is True
    assert args.include_dangerous is True
    assert args.pretty is True


def test_main_list_capabilities_outputs_complete_default_manifest(capsys) -> None:
    rc = main(["list-capabilities"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    capabilities = payload["capabilities"]
    assert capabilities
    action_types = {row["action_type"] for row in capabilities}
    assert "payload_release" not in action_types

    required_fields = {
        "action_type",
        "domain",
        "skill_group",
        "risk_level",
        "supported_adapters",
        "fallback_allowed",
        "allowed_link_states",
        "requires_confirmation_by_default",
        "dangerous",
        "policy_default",
        "notes",
    }
    assert required_fields <= set(capabilities[0])


def test_main_list_capabilities_include_dangerous_and_filters(capsys) -> None:
    rc = main(["list-capabilities", "--include-dangerous", "--domain", "payload"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    capabilities = payload["capabilities"]
    assert capabilities
    assert all(row["domain"] == "payload" for row in capabilities)
    action_types = {row["action_type"] for row in capabilities}
    assert {"payload_release", "drop", "strike", "attack"} <= action_types


def test_main_list_capabilities_fallback_and_adapter_filters(capsys) -> None:
    rc = main(["list-capabilities", "--fallback-only", "--adapter", "payload"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    capabilities = payload["capabilities"]
    assert capabilities
    assert all(row["fallback_allowed"] is True for row in capabilities)
    assert all("payload" in row["supported_adapters"] for row in capabilities)
    assert all(row["dangerous"] is False for row in capabilities)


def test_main_smoke_takeoff_non_sitl_outputs_policy_and_audit(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    rc = main([
        "smoke-takeoff",
        "--backend",
        "px4_sitl",
        "--backend-mode",
        "stub",
        "--backend-enabled",
        "--transport-endpoint",
        "udpin:127.0.0.1:14540",
        "--auto-land",
    ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["endpoint"] == "udpin:127.0.0.1:14540"
    assert payload["policy_decision"]["decision_code"] == "allow"
    assert payload["result"] == "fail"
    assert payload["failure_reason"] == "sitl_only_required"

    audit_text = (tmp_path / "audit" / "runtime.audit.jsonl").read_text(encoding="utf-8")
    assert "policy_decision_event" in audit_text
    assert "px4_sitl_smoke_takeoff" in audit_text
    assert "udpin:127.0.0.1:14540" in audit_text
    assert "MAV_CMD_NAV_TAKEOFF" in audit_text
