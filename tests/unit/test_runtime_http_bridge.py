"""Runtime HTTP Bridge v0.1 route tests."""
from __future__ import annotations

from pathlib import Path

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

    assert status == 200
    assert payload["action"] == "takeoff"
    assert payload["result"] == "fail"
    assert payload["failure_reason"] == "sitl_only_required"
    assert payload["policy_decision"]["decision_code"] == "allow"


def test_land_non_sitl_is_rejected_after_policy_check(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    _set_audit_path(monkeypatch, tmp_path)

    status, payload = dispatch(
        "POST",
        "/api/actions/land",
        body={"backend_mode": "stub", "backend_enabled": True, "transport_endpoint": "udpin:127.0.0.1:14540"},
    )

    assert status == 200
    assert payload["action"] == "land"
    assert payload["result"] == "fail"
    assert payload["failure_reason"] == "sitl_only_required"
    assert payload["policy_decision"]["decision_code"] == "allow"


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
