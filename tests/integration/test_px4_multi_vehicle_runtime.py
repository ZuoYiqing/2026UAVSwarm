"""Opt-in real three-PX4 discovery/snapshot test.

The default suite never opens UDP endpoints. The simulation owner must provide a
fully populated config through ``UAV_RUNTIME_PX4_MULTI_CONFIG`` before this test
creates collectors and waits for real heartbeat/telemetry.
"""
from __future__ import annotations

import json
import os
import threading
import time
import warnings
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

import uav_runtime.http.routes as routes
from uav_runtime.http.state_store import RuntimeStateStore
from uav_runtime.runtime.vehicle_registry import VehicleRegistry


def _multi_config() -> Path:
    value = os.environ.get("UAV_RUNTIME_PX4_MULTI_CONFIG")
    if not value:
        pytest.skip("BLOCKED_WAITING_FOR_PX4_MULTI_ENDPOINTS")
    path = Path(value)
    assert path.is_file(), f"multi-PX4 config not found: {path}"
    return path


def _wait_until(predicate: Callable[[], bool], *, timeout_s: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return bool(predicate())


def _start_connected_registry() -> VehicleRegistry:
    registry = VehicleRegistry.from_json(_multi_config())
    handles = registry.list_vehicles()
    assert len(handles) == 3
    assert all(handle.config.enabled for handle in handles)
    assert len({handle.config.node_id for handle in handles}) == 3
    assert len({handle.config.system_id for handle in handles}) == 3
    assert all(handle.config.endpoint and handle.config.telemetry_endpoint for handle in handles)
    registry.start_all()
    try:
        assert _wait_until(lambda: all(registry.refresh_state(handle).connected for handle in handles))
    except BaseException:
        registry.stop_all()
        raise
    return registry


def _node_observation(
    registry: VehicleRegistry, node_id: str
) -> tuple[float | None, bool | None]:
    handle = registry.get_vehicle(node_id)
    registry.refresh_state(handle)
    with handle.state_lock:
        raw_altitude = handle.telemetry.local_position.altitude_m
        altitude = float(raw_altitude) if raw_altitude is not None else None
        armed = handle.telemetry.armed
    return altitude, armed


def _grounded_and_disarmed(registry: VehicleRegistry, node_id: str) -> bool:
    altitude, armed = _node_observation(registry, node_id)
    return altitude is not None and altitude <= 0.3 and armed is False


def _action_body(registry: VehicleRegistry, node_id: str) -> dict[str, Any]:
    config = registry.get_vehicle(node_id).config
    body: dict[str, Any] = {
        "node_id": node_id,
        "backend": "px4_sitl",
        "backend_mode": "sitl",
        "backend_enabled": True,
        "transport_endpoint": config.endpoint,
        "system_id": config.system_id,
    }
    if config.component_id is not None:
        body["component_id"] = config.component_id
    return body


def _dispatch_land(registry: VehicleRegistry, node_id: str) -> bool:
    status, result = routes.dispatch(
        "POST", "/api/actions/land", body=_action_body(registry, node_id)
    )
    return bool(
        status == 200
        and isinstance(result, dict)
        and result.get("result") == "pass"
        and result.get("resolved_node_id") == node_id
    )


def _best_effort_land_and_confirm(
    registry: VehicleRegistry,
    node_id: str,
    *,
    timeout_s: float = 30.0,
) -> tuple[bool, bool, str | None]:
    """Try HTTP LAND, fall back to the Registry session, then observe ground.

    ``land_completed`` is set only after an accepted LAND result. Regardless of
    command outcome, this helper waits for grounded/disarmed evidence or an
    explicit timeout before its caller is allowed to stop the Registry.
    """
    land_completed = False
    errors: list[str] = []
    if routes.VEHICLE_REGISTRY is registry:
        try:
            land_completed = _dispatch_land(registry, node_id)
            if not land_completed:
                errors.append("http_land_not_completed")
        except Exception as exc:  # pragma: no cover - real-environment evidence
            errors.append(f"http_land_error:{type(exc).__name__}:{exc}")

    if not land_completed:
        try:
            handle = registry.get_vehicle(node_id)
            with handle.command_lock:
                ack = handle.session.land(timeout_s=min(10.0, timeout_s))
            land_completed = bool(
                isinstance(ack, dict)
                and ack.get("result") == 0
                and not ack.get("timeout", False)
            )
            if not land_completed:
                errors.append("direct_land_not_completed")
        except Exception as exc:  # pragma: no cover - real-environment evidence
            errors.append(f"direct_land_error:{type(exc).__name__}:{exc}")

    grounded_confirmed = _wait_until(
        lambda: _grounded_and_disarmed(registry, node_id), timeout_s=timeout_s
    )
    if not grounded_confirmed:
        errors.append(f"grounded_disarmed_timeout:{timeout_s:.1f}s")
    failure = ";".join(errors) if not (land_completed and grounded_confirmed) else None
    return land_completed, grounded_confirmed, failure


@pytest.mark.requires_px4_multi
def test_three_px4_nodes_connect_and_publish_one_full_snapshot() -> None:
    registry = _start_connected_registry()
    try:
        snapshot = RuntimeStateStore(vehicle_registry=registry).vehicle_snapshot()
        schema_path = Path("frontend/swarm-console/simulation-3d/public/contracts/vehicle-snapshot.schema.json")
        assert schema_path.is_file(), "authoritative Vehicle Snapshot schema is required"
        jsonschema = pytest.importorskip("jsonschema")
        jsonschema.validate(snapshot, json.loads(schema_path.read_text(encoding="utf-8")))
        assert snapshot["full_state"] is True
        assert snapshot["source"]["kind"] == "simulation"
        assert {vehicle["id"] for vehicle in snapshot["vehicles"]} == {"UAV-01", "UAV-02", "UAV-03"}
        assert all(vehicle["connected"] for vehicle in snapshot["vehicles"])
    finally:
        registry.stop_all()


@pytest.mark.requires_px4_multi
@pytest.mark.parametrize("node_id", ["UAV-01", "UAV-02", "UAV-03"])
def test_each_uav_takeoff_and_land_do_not_command_other_nodes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, node_id: str
) -> None:
    """Real SITL action proof; skipped unless three external endpoints are supplied."""
    registry = _start_connected_registry()
    store = RuntimeStateStore(vehicle_registry=registry)
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", registry)
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", store)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "px4-multi.audit.jsonl"))
    land_completed = False
    grounded_confirmed = False
    cleanup_errors: list[str] = []
    captured_failure: tuple[BaseException, Any] | None = None
    try:
        baseline = {
            candidate: _node_observation(registry, candidate)
            for candidate in ("UAV-01", "UAV-02", "UAV-03")
        }
        assert all(
            altitude is not None and altitude <= 0.5 and armed is False
            for altitude, armed in baseline.values()
        ), "REAL_PX4_MULTI_REQUIRES_GROUNDED_DISARMED_START"
        grounded_confirmed = _grounded_and_disarmed(registry, node_id)
        body = _action_body(registry, node_id) | {
            "altitude_m": 3.0,
            "threshold_ratio": 0.70,
            "auto_land": False,
            "observe_timeout_ms": 30000,
        }
        status, result = routes.dispatch("POST", "/api/actions/smoke-takeoff", body=body)
        assert status == 200
        assert result["result"] == "pass" and result["accepted"] is True
        assert result["resolved_node_id"] == node_id
        grounded_confirmed = False
        assert _wait_until(
            lambda: (_node_observation(registry, node_id)[0] or 0.0) >= 2.1,
            timeout_s=10.0,
        )
        for other_node_id in {"UAV-01", "UAV-02", "UAV-03"} - {node_id}:
            other_altitude, other_armed = _node_observation(registry, other_node_id)
            baseline_altitude = baseline[other_node_id][0]
            assert other_altitude is not None and baseline_altitude is not None
            assert other_altitude <= baseline_altitude + 0.5 and other_armed is False

        land_completed = _dispatch_land(registry, node_id)
        assert land_completed
        grounded_confirmed = _wait_until(
            lambda: _grounded_and_disarmed(registry, node_id), timeout_s=30.0
        )
        assert grounded_confirmed
    except BaseException as exc:
        captured_failure = (exc, exc.__traceback__)
    finally:
        # Never trust a previous flag over current telemetry. Check every node,
        # because a routing defect could have made a non-target aircraft fly.
        # Any node without grounded/disarmed proof gets LAND + observation
        # before Registry transports are stopped.
        for cleanup_node_id in ("UAV-01", "UAV-02", "UAV-03"):
            observation_error = None
            try:
                cleanup_grounded = _grounded_and_disarmed(
                    registry, cleanup_node_id
                )
            except Exception as exc:  # pragma: no cover - real-environment evidence
                cleanup_grounded = False
                observation_error = (
                    f"pre_cleanup_observation_error:{cleanup_node_id}:"
                    f"{type(exc).__name__}:{exc}"
                )
            if not cleanup_grounded:
                cleanup_land_completed, cleanup_grounded, cleanup_error = (
                    _best_effort_land_and_confirm(
                        registry, cleanup_node_id, timeout_s=30.0
                    )
                )
                if cleanup_node_id == node_id:
                    land_completed = cleanup_land_completed
                if cleanup_error:
                    if observation_error:
                        cleanup_errors.append(observation_error)
                    cleanup_errors.append(f"{cleanup_node_id}:{cleanup_error}")
            if cleanup_node_id == node_id:
                grounded_confirmed = cleanup_grounded
        try:
            registry.stop_all()
        except Exception as exc:  # pragma: no cover - real-environment evidence
            cleanup_errors.append(f"registry_stop_error:{type(exc).__name__}:{exc}")

    if cleanup_errors:
        detail = ";".join(cleanup_errors)
        if captured_failure is None:
            pytest.fail(f"PX4 cleanup failed after LAND/wait: {detail}")
        warnings.warn(f"PX4 cleanup evidence after original failure: {detail}", RuntimeWarning)
    if captured_failure is not None:
        exc, traceback = captured_failure
        raise exc.with_traceback(traceback)
    assert land_completed and grounded_confirmed


def test_best_effort_cleanup_waits_for_ground_before_registry_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cleanup ordering is testable without opening a MAVLink endpoint."""
    sequence: list[str] = []
    telemetry = SimpleNamespace(
        local_position=SimpleNamespace(altitude_m=2.0), armed=True
    )

    class Session:
        def land(self, *, timeout_s: float) -> dict[str, Any]:
            assert timeout_s > 0
            sequence.append("direct_land_completed")
            telemetry.local_position.altitude_m = 0.0
            telemetry.armed = False
            return {"result": 0, "timeout": False}

    handle = SimpleNamespace(
        config=SimpleNamespace(endpoint="udp:test", system_id=2, component_id=1),
        command_lock=threading.RLock(),
        state_lock=threading.RLock(),
        session=Session(),
        telemetry=telemetry,
    )

    class Registry:
        def get_vehicle(self, node_id: str) -> Any:
            assert node_id == "UAV-02"
            return handle

        def refresh_state(self, selected: Any) -> None:
            assert selected is handle
            sequence.append("ground_observed")

        def stop_all(self) -> None:
            sequence.append("registry_stopped")

    registry = Registry()
    monkeypatch.setattr(
        routes,
        "dispatch",
        lambda *args, **kwargs: (503, {"result": "fail"}),
    )
    land_completed, grounded_confirmed, error = _best_effort_land_and_confirm(
        registry, "UAV-02", timeout_s=0.1  # type: ignore[arg-type]
    )
    registry.stop_all()

    assert land_completed is True
    assert grounded_confirmed is True
    assert error is None
    assert sequence.index("direct_land_completed") < sequence.index("ground_observed")
    assert sequence.index("ground_observed") < sequence.index("registry_stopped")


@pytest.mark.requires_px4_multi
def test_uav02_telemetry_loss_isolated_and_http_reads_survive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise Runtime's per-node loss path without claiming PX4 process control."""
    registry = _start_connected_registry()
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", registry)
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", RuntimeStateStore(vehicle_registry=registry))
    try:
        target = registry.get_vehicle("UAV-02")
        assert target.collector is not None
        target.collector.stop()
        assert _wait_until(lambda: registry.refresh_state(target).stale)
        assert registry.refresh_state(target).connected is False
        assert all(
            registry.refresh_state(registry.get_vehicle(node_id)).connected
            for node_id in ("UAV-01", "UAV-03")
        )

        for path in ("/api/telemetry/latest", "/api/vehicle-snapshot", "/api/snapshot", "/api/simulation/status"):
            status, _ = routes.dispatch("GET", path)
            assert status == 200
        _, snapshot = routes.dispatch("GET", "/api/vehicle-snapshot")
        by_id = {vehicle["id"]: vehicle for vehicle in snapshot["vehicles"]}
        assert by_id["UAV-02"]["connected"] is False
        assert by_id["UAV-02"]["telemetry"]["stale"] is True
        assert by_id["UAV-02"]["pose_source"] == "last_known_telemetry"
        assert by_id["UAV-01"]["connected"] is True
        assert by_id["UAV-03"]["connected"] is True
    finally:
        registry.stop_all()
