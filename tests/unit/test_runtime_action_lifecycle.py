from __future__ import annotations

import threading
from typing import Any

import pytest

import uav_runtime.http.routes as routes
from uav_runtime.http.state_store import ACTION_LIFECYCLE_STATUSES, RuntimeStateStore
from uav_runtime.runtime.vehicle_registry import VehicleConfig, VehicleRegistry


class FakeSession:
    def __init__(self, config: object) -> None:
        self.config = config
        self.calls: list[str] = []

    def close(self) -> None:
        pass


def install_registry(monkeypatch: pytest.MonkeyPatch) -> tuple[VehicleRegistry, RuntimeStateStore]:
    registry = VehicleRegistry(session_factory=FakeSession)
    for index in range(1, 4):
        registry.register_vehicle(VehicleConfig(
            node_id=f"UAV-0{index}",
            endpoint=f"udpin:127.0.0.1:{14539 + index}",
            telemetry_endpoint=f"udpin:127.0.0.1:{14539 + index}",
            system_id=index,
            component_id=1,
        ))
        registry.mark_connected(f"UAV-0{index}")
    store = RuntimeStateStore(vehicle_registry=registry)
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", registry)
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", store)
    return registry, store


def action_body(node_id: str, *, key: str, altitude_m: float = 3.0) -> dict[str, Any]:
    index = int(node_id[-1])
    return {
        "node_id": node_id,
        "backend_enabled": True,
        "transport_endpoint": f"udpin:127.0.0.1:{14539 + index}",
        "altitude_m": altitude_m,
        "altitude_tolerance_m": 0.2,
        "stable_duration_ms": 500,
        "request_id": f"req-{key}",
        "trace_id": f"trace-{key}",
        "idempotency_key": key,
    }


def successful_takeoff(self: Any, **_: Any) -> dict[str, Any]:
    self.session.calls.append("takeoff")
    return {
        "action": "takeoff",
        "result": "pass",
        "ack_evidence": [{"stage": "takeoff", "command": 22, "result": 0, "timeout": False}],
        "completion_state": "succeeded",
        "completion_evidence": {"telemetry_state": "fresh", "completion_reached": True},
    }


def successful_land(self: Any, **_: Any) -> dict[str, Any]:
    self.session.calls.append("land")
    return {
        "action": "land",
        "result": "pass",
        "ack_evidence": [{"stage": "land", "command": 21, "result": 0, "timeout": False}],
        "completion_state": "succeeded",
        "completion_evidence": {
            "telemetry_state": "fresh",
            "landed_state_name": "on_ground",
            "armed": False,
            "completion_reached": True,
        },
    }


def test_action_lifecycle_contract_exposes_all_required_states() -> None:
    assert set(ACTION_LIFECYCLE_STATUSES) == {
        "requested",
        "policy_rejected",
        "accepted",
        "executing",
        "succeeded",
        "failed",
        "timed_out",
    }


def test_formal_takeoff_is_idempotent_and_queryable(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    registry, store = install_registry(monkeypatch)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(routes.Px4SitlBackend, "execute_takeoff_action", successful_takeoff)
    body = action_body("UAV-02", key="takeoff-uav02-001")

    first_status, first = routes.dispatch("POST", "/api/actions/takeoff", body=body)
    second_status, second = routes.dispatch("POST", "/api/actions/takeoff", body=body)
    query_status, queried = routes.dispatch("GET", f"/api/actions/{first['action_id']}")

    assert first_status == second_status == query_status == 200
    assert first["status"] == queried["status"] == "succeeded"
    assert second["idempotent_replay"] is True
    assert second["action_id"] == first["action_id"]
    assert registry.get_vehicle("UAV-02").session.calls == ["takeoff"]
    assert store.runtime_snapshot()["active_actions"] == []
    ack = first["ack_evidence"][0]
    assert ack["request_id"] == body["request_id"]
    assert ack["trace_id"] == body["trace_id"]
    assert ack["node_id"] == "UAV-02"
    assert ack["action_id"] == first["action_id"]
    assert ack["timestamp"]


def test_agent_request_uses_same_policy_and_node_bound_adapter_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    registry, store = install_registry(monkeypatch)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(routes.Px4SitlBackend, "execute_takeoff_action", successful_takeoff)
    body = action_body("UAV-03", key="agent-uav03-001")
    body["command_source"] = "agent"

    status, result = routes.dispatch("POST", "/api/actions/takeoff", body=body)

    assert status == 200
    assert result["status"] == "succeeded"
    assert result["command_source"] == "agent"
    assert store.action(result["action_id"])["source"] == "agent"
    assert registry.get_vehicle("UAV-03").session.calls == ["takeoff"]


def test_idempotency_key_reuse_with_different_request_is_conflict(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    install_registry(monkeypatch)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(routes.Px4SitlBackend, "execute_takeoff_action", successful_takeoff)

    first_status, _ = routes.dispatch(
        "POST", "/api/actions/takeoff", body=action_body("UAV-02", key="same-key", altitude_m=3.0)
    )
    second_status, second = routes.dispatch(
        "POST", "/api/actions/takeoff", body=action_body("UAV-02", key="same-key", altitude_m=4.0)
    )

    assert first_status == 200
    assert second_status == 409
    assert second["error"] == "idempotency_conflict"


def test_active_idempotent_retry_returns_same_action_without_second_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    registry, _store = install_registry(monkeypatch)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    entered = threading.Event()
    release = threading.Event()

    def blocking_takeoff(self: Any, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        entered.set()
        assert release.wait(timeout=2)
        return successful_takeoff(self)

    monkeypatch.setattr(routes.Px4SitlBackend, "execute_takeoff_action", blocking_takeoff)
    body = action_body("UAV-02", key="active-retry")
    first: list[tuple[int, dict[str, Any]]] = []
    thread = threading.Thread(
        target=lambda: first.append(routes.dispatch("POST", "/api/actions/takeoff", body=body))
    )
    thread.start()
    assert entered.wait(timeout=2)

    retry_status, retry = routes.dispatch("POST", "/api/actions/takeoff", body=body)
    release.set()
    thread.join(timeout=2)

    assert thread.is_alive() is False
    assert retry_status == 202
    assert retry["status"] == "executing"
    assert retry["idempotent_replay"] is True
    assert first[0][0] == 200
    assert retry["action_id"] == first[0][1]["action_id"]
    assert registry.get_vehicle("UAV-02").session.calls == ["takeoff"]


def test_busy_is_per_node_and_does_not_block_another_vehicle(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    registry, store = install_registry(monkeypatch)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(routes.Px4SitlBackend, "execute_takeoff_action", successful_takeoff)
    active, _ = store.request_action(
        "takeoff", backend="px4_sitl", backend_mode="sitl", node_id="UAV-02", idempotency_key="active"
    )
    registry.admit_action("UAV-02", "takeoff", active["action_id"])

    busy_status, busy = routes.dispatch(
        "POST", "/api/actions/takeoff", body=action_body("UAV-02", key="busy")
    )
    other_status, other = routes.dispatch(
        "POST", "/api/actions/takeoff", body=action_body("UAV-03", key="other")
    )

    assert busy_status == 409
    assert busy["code"] == "node_busy"
    assert busy["details"]["active_action_id"] == active["action_id"]
    assert other_status == 200 and other["status"] == "succeeded"
    assert registry.get_vehicle("UAV-03").session.calls == ["takeoff"]


def test_stale_node_is_rejected_before_policy_or_adapter_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [10.0]
    registry = VehicleRegistry(session_factory=FakeSession, clock=lambda: now[0])
    registry.register_vehicle(VehicleConfig(
        node_id="UAV-02",
        endpoint="udpin:127.0.0.1:14541",
        telemetry_endpoint="udpin:127.0.0.1:14541",
        system_id=2,
        component_id=1,
    ))
    registry.mark_connected("UAV-02")
    registry.get_vehicle("UAV-02").telemetry_received_at = 0.0
    store = RuntimeStateStore(vehicle_registry=registry)
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", registry)
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", store)

    status, result = routes.dispatch(
        "POST",
        "/api/actions/takeoff",
        body=action_body("UAV-02", key="stale"),
    )

    assert status == 503
    assert result["error"] == "node_offline"
    assert registry.get_vehicle("UAV-02").session.calls == []
    assert store.recent_actions() == []


@pytest.mark.parametrize(
    "updates",
    [
        {"altitude_m": 1.0, "altitude_tolerance_m": 1.0},
        {"stable_duration_ms": 0},
    ],
)
def test_formal_takeoff_rejects_completion_settings_that_can_bypass_hold(
    monkeypatch: pytest.MonkeyPatch,
    updates: dict[str, Any],
) -> None:
    registry, store = install_registry(monkeypatch)
    body = action_body("UAV-02", key="unsafe-completion")
    body.update(updates)

    status, result = routes.dispatch("POST", "/api/actions/takeoff", body=body)

    assert status == 400
    assert result["error"] == "invalid_parameter"
    assert registry.get_vehicle("UAV-02").session.calls == []
    assert store.recent_actions() == []


def test_land_preempts_takeoff_and_finishes_old_lifecycle(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    registry, store = install_registry(monkeypatch)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(routes.Px4SitlBackend, "execute_land_action", successful_land)
    old, _ = store.request_action(
        "takeoff", backend="px4_sitl", backend_mode="sitl", node_id="UAV-02", idempotency_key="old"
    )
    store.transition_action(old["action_id"], "executing")
    old_lease = registry.admit_action("UAV-02", "takeoff", old["action_id"])

    land_status, landed = routes.dispatch(
        "POST", "/api/actions/land", body=action_body("UAV-02", key="land")
    )

    assert land_status == 200 and landed["status"] == "succeeded"
    assert old_lease["cancel_event"].is_set() is True
    old_result = store.action(old["action_id"])
    assert old_result["status"] == "failed"
    assert old_result["failure_reason"] == "action_preempted_by_land"
    assert old_result["preempted_by_action_id"] == landed["action_id"]
    assert registry.get_vehicle("UAV-02").runtime_state.active_action is None
    assert '"type": "action_preempted"' in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")

    class NullAudit:
        def append(self, event: dict[str, Any]) -> None:
            del event

    handle = registry.get_vehicle("UAV-02")
    late = routes._finalize_action(
        action_id=old["action_id"],
        out={
            "action": "takeoff",
            "result": "pass",
            "request_id": old["request_id"],
            "trace_id": old["trace_id"],
            "ack_evidence": [{"stage": "takeoff", "command": 22, "result": 0}],
            "completion_state": "cancelled",
            "completion_evidence": {"cancelled": True},
        },
        handle=handle,
        rt=type("Runtime", (), {"audit": NullAudit()})(),
        cfg=handle.config.to_mavlink_config(),
        event_type="http_takeoff",
    )
    assert late["status"] == "failed"
    assert late["result"] == "fail"
    assert late["failure_reason"] == "action_preempted_by_land"
    assert store.action(old["action_id"])["ack_evidence"][0]["action_id"] == old["action_id"]


def test_policy_rejection_is_terminal_and_adapter_is_not_called(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    registry, store = install_registry(monkeypatch)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(routes.Px4SitlBackend, "execute_takeoff_action", successful_takeoff)
    original = routes._policy_checked_sitl_action

    def reject(*args: Any, **kwargs: Any):
        _decision, event, runtime, request = original(*args, **kwargs)
        event = {**event, "decision_code": "deny", "primary_reason_code": "test_policy_denied"}
        return "deny", event, runtime, request

    monkeypatch.setattr(routes, "_policy_checked_sitl_action", reject)
    status, result = routes.dispatch(
        "POST", "/api/actions/takeoff", body=action_body("UAV-01", key="denied")
    )

    assert status == 200
    assert result["status"] == "policy_rejected"
    assert result["code"] == "policy_deny"
    assert registry.get_vehicle("UAV-01").session.calls == []
    assert store.action(result["action_id"])["status"] == "policy_rejected"


def test_policy_exception_finishes_requested_action_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, store = install_registry(monkeypatch)

    def explode(*args: Any, **kwargs: Any):
        del args, kwargs
        raise RuntimeError("policy unavailable")

    monkeypatch.setattr(routes, "_policy_checked_sitl_action", explode)
    with pytest.raises(RuntimeError, match="policy unavailable"):
        routes.takeoff(action_body("UAV-02", key="policy-exception"))

    failed = store.recent_actions(limit=1)[0]
    assert failed["status"] == "failed"
    assert failed["failure_reason"] == "policy_evaluation_exception"
    assert failed["node_id"] == "UAV-02"
    assert registry.get_vehicle("UAV-02").runtime_state.active_action is None


def test_formal_takeoff_exception_finishes_action_and_reraises(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    registry, store = install_registry(monkeypatch)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))

    def explode(self: Any, **_: Any) -> dict[str, Any]:
        raise RuntimeError("backend-private")

    class ExplodingGateway:
        def register(self, adapter: object) -> None:
            del adapter

        def execute(self, adapter_name: str, action_request: object) -> dict[str, Any]:
            del adapter_name, action_request
            raise RuntimeError("gateway exploded")

    original = routes._policy_checked_sitl_action

    def install_gateway(*args: Any, **kwargs: Any):
        decision, event, runtime, request = original(*args, **kwargs)
        runtime.gateway = ExplodingGateway()  # type: ignore[assignment]
        return decision, event, runtime, request

    monkeypatch.setattr(routes, "_policy_checked_sitl_action", install_gateway)
    monkeypatch.setattr(routes.Px4SitlBackend, "execute_takeoff_action", explode)

    with pytest.raises(RuntimeError, match="gateway exploded"):
        routes.takeoff(action_body("UAV-02", key="exception"))

    failed = store.recent_actions(limit=1)[0]
    assert failed["status"] == "failed"
    assert failed["failure_reason"] == "adapter_execution_exception"
    assert failed["node_id"] == "UAV-02"
    assert registry.get_vehicle("UAV-02").runtime_state.active_action is None
