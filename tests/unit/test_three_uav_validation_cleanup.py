from __future__ import annotations

from typing import Any

from simulation.px4_gazebo.scripts import validate_three_uav as validator


def _accepted(command: int) -> dict[str, Any]:
    return {"command": command, "result": 0, "timeout": False}


def test_failed_landing_observation_triggers_recovery_without_masking_original(
    monkeypatch,
) -> None:
    class Session:
        connected = False
        target_system = 2

        def __init__(self) -> None:
            self.land_calls = 0
            self.closed = False

        def connect(self, *, timeout_s: float) -> None:
            del timeout_s
            self.connected = True

        def start_gcs_heartbeat(self) -> None: pass
        def request_local_position_stream(self, **kwargs: Any) -> dict[str, Any]:
            return _accepted(511)
        def arm(self, **kwargs: Any) -> dict[str, Any]: return _accepted(400)
        def takeoff(self, **kwargs: Any) -> dict[str, Any]: return _accepted(22)
        def observe_local_position_altitude(self, **kwargs: Any) -> dict[str, Any]:
            return {"observed": True, "threshold_reached": True}
        def land(self, **kwargs: Any) -> dict[str, Any]:
            self.land_calls += 1
            return _accepted(21)
        def close(self) -> None:
            self.connected = False
            self.closed = True

    session = Session()
    landing_results = iter(
        [
            {"observed": True, "landed": False, "sample_count": 3},
            {"observed": True, "landed": True, "sample_count": 3},
        ]
    )
    monkeypatch.setattr(validator, "_session", lambda vehicle: session)
    monkeypatch.setattr(
        validator,
        "_observe_passive_state",
        lambda vehicle, timeout_s: {"node_id": vehicle["node_id"], "isolated": True},
    )
    monkeypatch.setattr(
        validator,
        "_wait_for_landing",
        lambda session, timeout_s: next(landing_results),
    )

    result = validator._validate_active_vehicle(
        {"node_id": "UAV-02", "system_id": 2},
        [{"node_id": "UAV-01", "system_id": 1}],
        altitude_m=2.0,
        command_timeout_s=1.0,
        observe_timeout_s=1.0,
    )

    assert result["status"] == "FAIL"
    assert "landing was not observed" in result["error"]
    assert result["takeoff_observed"] is True
    assert result["land_command_accepted"] is True
    assert result["landed_observed"] is True
    assert result["recovery_land_ack"]["result"] == 0
    assert session.land_calls == 2
    assert session.closed is True
