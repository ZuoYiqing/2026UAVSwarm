"""HTTP observer completion must not unlock a PX4 still flying autonomously."""
from __future__ import annotations

from typing import Any

import pytest

from uav_runtime.runtime.vehicle_registry import VehicleConfig, VehicleRegistry, VehicleRegistryError


class FakeSession:
    def __init__(self, config: Any) -> None:
        self.config = config
        self.evidence: dict[str, Any] = {"fresh": True, "active": True, "mode": "AUTO_RTL"}

    def autonomous_state(self) -> dict[str, Any]:
        return dict(self.evidence)


def make_registry() -> VehicleRegistry:
    registry = VehicleRegistry(session_factory=FakeSession)
    for index in range(1, 4):
        registry.register_vehicle(VehicleConfig(
            node_id=f"UAV-0{index}", endpoint=f"fake://vehicle-{index}", system_id=index,
        ))
    return registry


def retain_return(registry: VehicleRegistry, node: str = "UAV-02") -> None:
    registry.admit_action(node, "return_home", "return-1")
    assert registry.retain_autonomous_action(node, "return-1", "return_home")
    assert registry.release_action(node, "return-1", error="observation_timeout")


def test_terminal_http_observation_keeps_only_selected_node_busy() -> None:
    registry = make_registry()
    retain_return(registry)
    with pytest.raises(VehicleRegistryError, match="node_busy") as caught:
        registry.admit_action("UAV-02", "goto", "goto-2")
    assert caught.value.details["autonomous_execution_may_continue"] is True
    assert caught.value.details["active_action_id"] == "return-1"
    registry.admit_action("UAV-01", "goto", "goto-1")
    registry.admit_action("UAV-03", "takeoff", "takeoff-3")
    rows = {row["node_id"]: row for row in registry.vehicle_rows()}
    assert rows["UAV-02"]["autonomous_action_id"] == "return-1"
    assert rows["UAV-01"]["autonomous_action_id"] is None
    assert rows["UAV-03"]["autonomous_action_id"] is None


def test_pre_command_hold_heartbeat_cannot_clear_new_autonomous_lease() -> None:
    registry = make_registry()
    handle = registry.get_vehicle("UAV-02")
    handle.session.evidence = {"fresh": True, "active": False, "stop_sequence": 10}
    registry.admit_action("UAV-02", "return_home", "return-1")
    assert registry.retain_autonomous_action("UAV-02", "return-1", "return_home", after_sequence=10)
    registry.release_action("UAV-02", "return-1")
    with pytest.raises(VehicleRegistryError, match="node_busy"):
        registry.admit_action("UAV-02", "goto", "goto-2")
    handle.session.evidence["stop_sequence"] = 11
    registry.admit_action("UAV-02", "goto", "goto-2")


@pytest.mark.parametrize("evidence", [
    {"fresh": False, "active": False, "mode": "POSCTL"},
    {"fresh": True, "active": None},
    {"fresh": False, "active": True},
    {},
])
def test_stale_or_unknown_evidence_never_releases_guard(evidence: dict[str, Any]) -> None:
    registry = make_registry()
    retain_return(registry)
    registry.get_vehicle("UAV-02").session.evidence = evidence
    registry._clock = lambda: 10**12
    assert registry.vehicle_rows()[1]["autonomous_action_id"] == "return-1"
    with pytest.raises(VehicleRegistryError, match="node_busy"):
        registry.admit_action("UAV-02", "takeoff", "takeoff-2")


@pytest.mark.parametrize("evidence", [
    {"fresh": True, "active": False, "mode": "POSCTL"},
    {"fresh": True, "active": False, "mode": "ALTCTL"},
    {"fresh": True, "active": False, "mode": "AUTO_LOITER"},
    {"fresh": True, "active": False, "landed": True, "armed": False},
])
def test_fresh_safe_session_evidence_releases_guard(evidence: dict[str, Any]) -> None:
    registry = make_registry()
    retain_return(registry)
    registry.get_vehicle("UAV-02").session.evidence = evidence
    registry.admit_action("UAV-02", "goto", "goto-2")
    assert registry.get_vehicle("UAV-02").runtime_state.autonomous_action_id is None


def test_land_has_priority_but_failed_land_does_not_clear_return_guard() -> None:
    registry = make_registry()
    retain_return(registry)
    registry.admit_action("UAV-02", "land", "land-2")
    assert registry.release_action("UAV-02", "land-2", error="land_ack_timeout")
    with pytest.raises(VehicleRegistryError, match="node_busy"):
        registry.admit_action("UAV-02", "goto", "goto-2")
    registry.admit_action("UAV-02", "land", "land-retry")


def test_preempted_return_observer_cannot_replace_current_land_lease() -> None:
    registry = make_registry()
    lease = registry.admit_action("UAV-02", "return_home", "return-1")
    registry.admit_action("UAV-02", "land", "land-2")
    assert lease["cancel_event"].is_set()
    assert not registry.retain_autonomous_action("UAV-02", "return-1", "return_home")
    assert not registry.release_action("UAV-02", "return-1")
    assert registry.get_vehicle("UAV-02").runtime_state.active_action_id == "land-2"
    assert registry.release_action("UAV-02", "land-2", error="land_ack_timeout")
    with pytest.raises(VehicleRegistryError, match="node_busy"):
        registry.admit_action("UAV-02", "goto", "goto-2")


def test_missing_or_exceptional_session_evidence_keeps_guard() -> None:
    registry = make_registry()
    retain_return(registry)
    session = registry.get_vehicle("UAV-02").session
    session.autonomous_state = None
    assert registry.vehicle_rows()[1]["autonomous_action_id"] == "return-1"

    def broken() -> dict[str, Any]:
        raise RuntimeError("receive_error")

    session.autonomous_state = broken
    assert registry.vehicle_rows()[1]["autonomous_action_id"] == "return-1"
    assert registry.vehicle_rows()[1]["autonomous_execution_evidence"]["fresh"] is False


def test_snapshot_can_clear_guard_from_fresh_landed_disarmed_evidence() -> None:
    registry = make_registry()
    retain_return(registry)
    registry.get_vehicle("UAV-02").session.evidence = {
        "fresh": True, "active": False, "landed": True, "armed": False,
    }
    assert registry.vehicle_rows()[1]["autonomous_action_id"] is None
