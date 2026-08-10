from uav_runtime.runtime.fleet_coordinator import FleetCoordinator


def test_coordinator_emits_intent_but_has_no_execution_dependency() -> None:
    rows = [
        {"node_id": "UAV-01", "enabled": True, "connected": False, "stale": True},
        {"node_id": "UAV-02", "enabled": True, "connected": True, "stale": False},
    ]
    out = FleetCoordinator().propose(action_type="inspect_area", vehicle_states=rows)
    assert out[0].to_dict() == {"node_id": "UAV-02", "action_type": "inspect_area", "reason": "selected_available_vehicle"}
