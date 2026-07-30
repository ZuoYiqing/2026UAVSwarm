"""Opt-in real three-PX4 discovery/snapshot test.

The default suite never opens UDP endpoints. The simulation owner must provide a
fully populated config through ``UAV_RUNTIME_PX4_MULTI_CONFIG`` before this test
creates collectors and waits for real heartbeat/telemetry.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from uav_runtime.http.state_store import RuntimeStateStore
from uav_runtime.runtime.vehicle_registry import VehicleRegistry


def _multi_config() -> Path:
    value = os.environ.get("UAV_RUNTIME_PX4_MULTI_CONFIG")
    if not value:
        pytest.skip("BLOCKED_WAITING_FOR_PX4_MULTI_ENDPOINTS")
    path = Path(value)
    assert path.is_file(), f"multi-PX4 config not found: {path}"
    return path


@pytest.mark.requires_px4_multi
def test_three_px4_nodes_connect_and_publish_one_full_snapshot() -> None:
    registry = VehicleRegistry.from_json(_multi_config())
    handles = registry.list_vehicles()
    assert len(handles) == 3
    assert all(handle.config.enabled for handle in handles)
    assert len({handle.config.node_id for handle in handles}) == 3
    assert len({handle.config.system_id for handle in handles}) == 3
    assert all(handle.config.endpoint and handle.config.telemetry_endpoint for handle in handles)

    registry.start_all()
    try:
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            if all(registry.refresh_state(handle).connected for handle in handles):
                break
            time.sleep(0.1)
        assert all(registry.refresh_state(handle).connected for handle in handles)

        snapshot = RuntimeStateStore(vehicle_registry=registry).vehicle_snapshot()
        assert snapshot["full_state"] is True
        assert snapshot["source"]["kind"] == "simulation"
        assert {vehicle["id"] for vehicle in snapshot["vehicles"]} == {"UAV-01", "UAV-02", "UAV-03"}
        assert all(vehicle["connected"] for vehicle in snapshot["vehicles"])
    finally:
        registry.stop_all()
