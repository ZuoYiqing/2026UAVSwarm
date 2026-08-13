import inspect

import pytest

import uav_runtime.runtime.fleet_coordinator as fleet_module
from uav_runtime.runtime.fleet_coordinator import FleetCoordinator


def test_coordinator_emits_intent_but_has_no_execution_dependency() -> None:
    rows = [
        {"node_id": "UAV-01", "enabled": True, "connected": False, "stale": True},
        {"node_id": "UAV-02", "enabled": True, "connected": True, "stale": False},
    ]
    out = FleetCoordinator().propose(action_type="inspect_area", vehicle_states=rows)
    assert out[0].to_dict() == {"node_id": "UAV-02", "action_type": "inspect_area", "reason": "selected_available_vehicle"}


def test_explicit_node_requires_an_eligible_matching_node() -> None:
    rows = [
        {"node_id": "UAV-01", "enabled": True, "connected": True, "stale": False},
        {"node_id": "UAV-02", "enabled": True, "connected": False, "stale": True},
    ]
    coordinator = FleetCoordinator()
    assert coordinator.propose(
        action_type="inspect_area", vehicle_states=rows,
        strategy="explicit_node", explicit_node_id="UAV-01",
    )[0].reason == "explicit_node"
    assert coordinator.propose(
        action_type="inspect_area", vehicle_states=rows,
        strategy="explicit_node", explicit_node_id="UAV-02",
    ) == []


def test_round_robin_is_deterministic_over_eligible_nodes() -> None:
    rows = [
        {"node_id": "UAV-01", "enabled": True, "connected": True, "stale": False},
        {"node_id": "UAV-02", "enabled": True, "connected": True, "stale": False},
    ]
    coordinator = FleetCoordinator()
    selected = [
        coordinator.propose(action_type="inspect_area", vehicle_states=rows, strategy="round_robin")[0].node_id
        for _ in range(3)
    ]
    assert selected == ["UAV-01", "UAV-02", "UAV-01"]


def test_capability_filter_and_unsupported_strategy_are_explicit() -> None:
    rows = [{"node_id": "UAV-01", "enabled": True, "connected": True, "stale": False}]
    coordinator = FleetCoordinator()
    assert coordinator.propose(
        action_type="inspect_area", vehicle_states=rows, capabilities={"UAV-01": ["report_status"]},
    ) == []
    with pytest.raises(ValueError, match="unsupported_fleet_strategy"):
        coordinator.propose(action_type="inspect_area", vehicle_states=rows, strategy="optimizer")


def test_module_has_no_execution_layer_dependency() -> None:
    source = inspect.getsource(fleet_module)
    for forbidden in ("AdapterGateway", "Px4SitlBackend", "MavlinkBackendSession"):
        assert forbidden not in source
