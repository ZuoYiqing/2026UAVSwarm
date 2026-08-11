"""Runtime HTTP Bridge v0.1 route tests."""
from __future__ import annotations

import json
from pathlib import Path

from uav_runtime.http.contracts import event_to_envelope
from uav_runtime.http import routes
from uav_runtime.http.routes import dispatch
from uav_runtime.http.server import ALLOWED_ORIGINS


def _set_audit_path(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "missing_or_test.audit.jsonl"))


def test_health_returns_ok() -> None:
    status, payload = dispatch("GET", "/api/health")

    assert status == 200
    assert payload["status"] == "ok"
    assert payload["service"] == "uav_runtime_http_bridge"
    assert payload["mode"] == "local_dev"


def test_backend_check_accepts_udpin_endpoint_and_preserves_it(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _set_audit_path(monkeypatch, tmp_path)
    monkeypatch.setattr(routes.Px4SitlBackend, "_is_pymavlink_available", staticmethod(lambda: False))

    status, payload = dispatch(
        "POST",
        "/api/backend/check",
        body={
            "backend": "px4_sitl",
            "backend_mode": "sitl",
            "backend_enabled": True,
            "transport_endpoint": "udpin:127.0.0.1:14540",
            "connect_timeout_ms": 5000,
        },
    )

    assert status == 200
    assert payload["backend"] == "px4_sitl"
    assert payload["transport_endpoint"] == "udpin:127.0.0.1:14540"
    assert payload["backend_mode"] == "sitl"


def test_smoke_takeoff_non_sitl_is_rejected_after_policy_check(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _set_audit_path(monkeypatch, tmp_path)

    status, payload = dispatch(
        "POST",
        "/api/actions/smoke-takeoff",
        body={"backend_mode": "stub", "backend_enabled": True, "transport_endpoint": "udpin:127.0.0.1:14540"},
    )

    assert status == 400
    assert payload["error"] == "unsupported_backend_mode"


def test_land_non_sitl_is_rejected_after_policy_check(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _set_audit_path(monkeypatch, tmp_path)

    status, payload = dispatch(
        "POST",
        "/api/actions/land",
        body={"backend_mode": "stub", "backend_enabled": True, "transport_endpoint": "udpin:127.0.0.1:14540"},
    )

    assert status == 400
    assert payload["error"] == "unsupported_backend_mode"


def test_plan_mission_returns_plan_result_without_execution(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _set_audit_path(monkeypatch, tmp_path)

    status, payload = dispatch(
        "POST",
        "/api/planner/plan-mission",
        body={"mission_type": "inspection_snapshot", "source": "ground_station", "profile": "standard", "dry_run": True},
    )

    assert status == 200
    assert payload["result"] in {"ready", "awaiting_confirmation", "blocked"}
    assert payload["plan"]["mission_type"] == "inspection_snapshot"
    assert [step["action_type"] for step in payload["plan"]["steps"]] == [
        "takeoff",
        "report_status",
        "camera_capture",
        "land",
    ]
    assert "arm_ack" not in payload
    assert "takeoff_ack" not in payload


def test_capabilities_default_hides_dangerous_actions() -> None:
    status, payload = dispatch("GET", "/api/capabilities")

    assert status == 200
    action_types = {row["action_type"] for row in payload["capabilities"]}
    assert "payload_release" not in action_types
    assert "drop" not in action_types
    assert "strike" not in action_types


def test_capabilities_include_dangerous_shows_forbidden_metadata() -> None:
    status, payload = dispatch("GET", "/api/capabilities", query="include_dangerous=true")

    assert status == 200
    action_types = {row["action_type"] for row in payload["capabilities"]}
    assert {"payload_release", "drop", "deploy", "strike", "attack"} <= action_types


def test_replay_returns_empty_list_when_audit_missing(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "does-not-exist.jsonl"))

    status, payload = dispatch("GET", "/api/replay", query="n=20")

    assert status == 200
    assert payload == []


def test_cors_allows_local_frontend_origins_only() -> None:
    assert "http://localhost:5178" in ALLOWED_ORIGINS
    assert "http://127.0.0.1:5178" in ALLOWED_ORIGINS
    assert "http://localhost:5173" in ALLOWED_ORIGINS
    assert "http://127.0.0.1:5173" in ALLOWED_ORIGINS
    assert "https://example.com" not in ALLOWED_ORIGINS



def _write_audit(path: Path, events: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")


def test_event_envelope_from_complete_event() -> None:
    event = {
        "event_id": "evt_complete",
        "trace_id": "trace_001",
        "mission_id": "mission_001",
        "session_id": "sess_001",
        "parent_event_id": None,
        "event_type": "policy_decision_event",
        "severity": "info",
        "source": "policy_gate",
        "node_id": "UAV-01",
        "timestamp": "2026-06-18T14:30:12+00:00",
        "summary": "Policy allowed takeoff request",
        "payload_key": "payload_value",
    }

    envelope = event_to_envelope(event).to_dict()

    assert envelope["event_id"] == "evt_complete"
    assert envelope["trace_id"] == "trace_001"
    assert envelope["event_type"] == "policy_decision_event"
    assert envelope["source"] == "policy_gate"
    assert envelope["payload"]["payload_key"] == "payload_value"


def test_event_envelope_from_legacy_event_tolerates_missing_fields() -> None:
    envelope = event_to_envelope({"type": "legacy_action", "result": "fail"}).to_dict()

    assert envelope["event_id"].startswith("evt_")
    assert envelope["event_type"] == "legacy_action"
    assert envelope["severity"] == "error"
    assert envelope["timestamp"] is None
    assert "unknown timestamp" in envelope["summary"]
    assert envelope["payload"]["type"] == "legacy_action"


def test_events_route_returns_event_envelopes(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    audit_path = tmp_path / "runtime.audit.jsonl"
    monkeypatch.setattr(routes, "AUDIT_PATH", str(audit_path))
    _write_audit(
        audit_path,
        [
            {"type": "backend_probe_result", "timestamp": "2026-06-18T14:00:00+00:00", "summary": "Backend ready"},
            {"event_type": "telemetry_sample", "timestamp": "2026-06-18T14:00:01+00:00", "source": "telemetry"},
        ],
    )

    status, payload = dispatch("GET", "/api/events", query="n=50")

    assert status == 200
    assert [event["event_type"] for event in payload] == ["backend_probe_result", "telemetry_sample"]
    assert all("payload" in event for event in payload)


def test_events_route_returns_empty_list_when_audit_missing(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "missing.audit.jsonl"))

    status, payload = dispatch("GET", "/api/events", query="n=50")

    assert status == 200
    assert payload == []


def test_actions_recent_returns_action_result_view(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    audit_path = tmp_path / "runtime.audit.jsonl"
    monkeypatch.setattr(routes, "AUDIT_PATH", str(audit_path))
    _write_audit(
        audit_path,
        [
            {
                "type": "px4_sitl_smoke_takeoff",
                "timestamp": "2026-06-18T14:00:00+00:00",
                "action": "takeoff",
                "backend": "px4_sitl",
                "backend_mode": "sitl",
                "result": "pass",
                "policy_decision": {"decision_code": "allow"},
                "ack": {
                    "takeoff_ack": {
                        "command_name": "MAV_CMD_NAV_TAKEOFF",
                        "result": 0,
                        "result_name": "MAV_RESULT_ACCEPTED",
                    }
                },
                "altitude_observation": {"target_altitude_m": 3.0},
                "max_altitude_m": 2.12,
                "threshold_reached": True,
            }
        ],
    )

    status, payload = dispatch("GET", "/api/actions/recent", query="n=20")

    assert status == 200
    assert payload[0]["action_type"] == "takeoff"
    assert payload[0]["adapter"] == "mavlink"
    assert payload[0]["command_results"][0]["accepted"] is True
    assert payload[0]["observations"]["max_altitude_m"] == 2.12
    assert payload[0]["observations"]["threshold_reached"] is True


def test_policy_decisions_returns_policy_decision_view(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    audit_path = tmp_path / "runtime.audit.jsonl"
    monkeypatch.setattr(routes, "AUDIT_PATH", str(audit_path))
    _write_audit(
        audit_path,
        [
            {
                "type": "policy_decision_event",
                "timestamp": "2026-06-18T14:00:00+00:00",
                "action_type": "takeoff",
                "decision_code": "allow",
                "primary_reason_code": None,
                "effective_profile_id": "standard",
                "effective_scope": "self_only",
                "audit_tags": ["sitl", "policy_checked"],
            }
        ],
    )

    status, payload = dispatch("GET", "/api/policy/decisions", query="n=20")

    assert status == 200
    assert payload[0]["action_type"] == "takeoff"
    assert payload[0]["decision_code"] == "allow"
    assert payload[0]["effective_profile_id"] == "standard"
    assert "policy_checked" in payload[0]["audit_tags"]


def test_skills_default_hides_dangerous_actions() -> None:
    status, payload = dispatch("GET", "/api/skills")

    assert status == 200
    action_types = {skill["action_type"] for skill in payload["skills"]}
    assert "payload_release" not in action_types
    assert "drop" not in action_types
    assert "strike" not in action_types


def test_skills_include_dangerous_shows_forbidden_metadata() -> None:
    status, payload = dispatch("GET", "/api/skills", query="include_dangerous=true")

    assert status == 200
    dangerous_actions = {skill["action_type"] for skill in payload["skills"] if skill["safety"]["dangerous"]}
    assert {"payload_release", "drop", "deploy", "strike", "attack"} <= dangerous_actions


def test_skills_domain_filter_returns_only_requested_domain() -> None:
    status, payload = dispatch("GET", "/api/skills", query="domain=flight")

    assert status == 200
    assert payload["skills"]
    assert {skill["domain"] for skill in payload["skills"]} == {"flight"}


def test_skills_adapter_filter_returns_only_supported_adapter() -> None:
    status, payload = dispatch("GET", "/api/skills", query="adapter=mavlink")

    assert status == 200
    assert payload["skills"]
    assert all("mavlink" in skill["supported_adapters"] for skill in payload["skills"])
