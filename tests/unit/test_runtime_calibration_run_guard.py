"""Simulation run changes are independent of calibration delivery and health TTL."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event, current_thread, main_thread
from types import SimpleNamespace

import pytest

from uav_runtime.http import routes
from tests.unit.test_runtime_shared_view_contract import build_store, calibration, update_local


def stamp(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).isoformat()


def health(run_id: str, now: float) -> dict:
    return {
        "contract_version": "1.0",
        "evidence_source": "simulation_integrated_health",
        "scene_id": "simple_recon_v0_1",
        "map_version": "map-v1",
        "source_timestamp": stamp(now),
        "valid_for_ms": 5000,
        "process_identity_valid": True,
        "run_id": run_id,
    }


def sample(run_id: str, now: float, *, node: str = "UAV-01", east: float = 8.0) -> dict:
    return {
        **calibration(node_id=node, east=east, valid_for_ms=60000),
        "source_timestamp": stamp(now),
        "context": {"run_id": run_id},
    }


@pytest.fixture
def runtime(monkeypatch):
    now = [1_700_000_000.0]
    registry, store = build_store(now, nodes=3)
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", store)
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", registry)
    monkeypatch.setattr(routes, "PLATFORM_GATEWAY", None)
    monkeypatch.setattr(routes, "DEMO_REHEARSAL", None)
    return now, registry, store


def post_calibration(evidence: dict):
    return routes.dispatch("POST", "/api/coordinates/calibration", body=evidence)


def test_restart_retires_public_poses_and_rejects_late_packets(runtime):
    now, registry, store = runtime
    node_ids = ("UAV-01", "UAV-02", "UAV-03")
    for node in node_ids:
        update_local(registry, node, x=1.0, y=2.0, z=-3.0, now=now[0])
    assert routes.dispatch("POST", "/api/simulation/evidence", body=health("old", now[0]))[0] == 200
    for node in node_ids:
        assert post_calibration(sample("old", now[0], node=node))[0] == 200
    assert all(row["spatial"]["public_position_usable"] for row in routes.vehicle_snapshot()["vehicles"])

    now[0] += 1
    # A calibration POST cannot change the active run itself.
    assert post_calibration(sample("new", now[0]))[0] == 400
    assert store.active_simulation_run_id() == "old"
    assert routes.dispatch("POST", "/api/simulation/evidence", body=health("new", now[0]))[0] == 200
    assert store.active_simulation_run_id() == "new"
    for row in routes.vehicle_snapshot()["vehicles"]:
        assert row["spatial"]["public_position_usable"] is False
        assert row["spatial"]["calibration_status"] == "unavailable"
        assert "scene_pose" not in row["spatial"]
        assert row["spatial"]["raw_vehicle_local_pose"]["frame"] == "vehicle_local_ned"

    assert post_calibration(sample("new", now[0], east=19.0))[0] == 200
    code, rejected = post_calibration(sample("old", now[0], east=9.0))
    assert (code, rejected["error"], rejected["message"]) == (
        400, "invalid_coordinate_calibration", "coordinate_calibration_run_mismatch",
    )
    cal, status = store.coordinate_calibration("UAV-01")
    assert (cal["context"]["run_id"], cal["translation_scene_ned_m"]["east"], status) == ("new", 19.0, "calibrated")
    assert store.coordinate_calibration("UAV-03") == (None, "unavailable")

    # Even a still-fresh health sample from a retired run cannot restore it.
    now[0] += 1
    code, rejected = routes.dispatch("POST", "/api/simulation/evidence", body=health("old", now[0]))
    assert (code, rejected["message"]) == (400, "simulation_evidence_run_retired")
    assert store.active_simulation_run_id() == "new"


@pytest.mark.parametrize("change", ["expired", "older", "equal", "unverified", "no_identity", "wrong_source", "missing"])
def test_unconfirmed_health_cannot_move_run_authority(runtime, change):
    now, _, store = runtime
    store.update_simulation_evidence(health("active", now[0]))
    store.update_coordinate_calibration(sample("active", now[0]))
    now[0] += 1
    other = health("other", now[0])
    if change in {"expired", "older", "equal"}:
        other["source_timestamp"] = stamp(now[0] - {"expired": 6, "older": 2, "equal": 1}[change])
    elif change == "unverified":
        other["process_identity_valid"] = False
    elif change == "no_identity":
        other.pop("process_identity_valid")
    elif change == "wrong_source":
        other["evidence_source"] = "not_integrated_health"
    else:
        other.pop("run_id")
    store.update_simulation_evidence(other)
    assert store.active_simulation_run_id() == "active"
    assert store.coordinate_calibration("UAV-01")[1] == "calibrated"
    assert post_calibration(sample("other", now[0]))[0] == 400


def test_in_flight_calibration_checks_run_at_cache_write(runtime, monkeypatch):
    now, _, store = runtime
    store.update_simulation_evidence(health("prior", now[0]))
    pending = sample("prior", now[0])
    arrived, release = Event(), Event()
    original_clock = store._monotonic

    def pause_before_cache_write():
        if current_thread() is not main_thread():
            arrived.set()
            assert release.wait(timeout=5)
        return original_clock()

    monkeypatch.setattr(store, "_monotonic", pause_before_cache_write)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(post_calibration, pending)
        try:
            assert arrived.wait(timeout=5)
            now[0] += 1
            store.update_simulation_evidence(health("current", now[0]))
        finally:
            release.set()
        code, rejected = result.result(timeout=5)
    assert (code, rejected["message"]) == (400, "coordinate_calibration_run_mismatch")
    assert store.coordinate_calibration("UAV-01") == (None, "unavailable")


def test_bootstrap_compatibility_and_bound_renewal_do_not_use_health_ttl(runtime):
    now, registry, store = runtime
    assert post_calibration(calibration())[0] == 200
    assert post_calibration(sample("active", now[0], node="UAV-02"))[0] == 200
    assert store.active_simulation_run_id() is None
    store.update_simulation_evidence(health("active", now[0]))
    assert store.coordinate_calibration("UAV-01") == (None, "unavailable")
    assert store.coordinate_calibration("UAV-02")[1] == "calibrated"

    for elapsed in (45, 90, 135):
        now[0] = 1_700_000_000.0 + elapsed
        update_local(registry, "UAV-02", x=1.0, y=2.0, z=-3.0, now=now[0])
        assert store.simulation_status()["evidence_fresh"] is False
        code, rejected = post_calibration(calibration(node_id="UAV-02"))
        assert (code, rejected["message"]) == (400, "coordinate_calibration_run_required")
        assert post_calibration(sample("active", now[0], node="UAV-02"))[0] == 200
        row = next(row for row in routes.vehicle_snapshot()["vehicles"] if row["id"] == "UAV-02")
        assert row["spatial"]["calibration_run_id"] == "active"
        assert row["spatial"]["public_position_usable"] is True


def test_ground_relay_rejects_old_posts_and_hides_cached_public_pose(runtime, monkeypatch):
    now, registry, store = runtime
    store.update_simulation_evidence(health("prior", now[0]))
    store.update_coordinate_calibration(sample("prior", now[0], node="UAV-02"))
    update_local(registry, "UAV-02", x=1.0, y=2.0, z=-3.0, now=now[0])
    snapshot = store.vehicle_snapshot()
    cached = next(row for row in snapshot["vehicles"] if row["id"] == "UAV-02")
    cached.update(link_quality=89, link_quality_measured=89, link_quality_mode="LIVE")
    projections = {"vehicle_snapshot": {"scene_id": snapshot["scene_id"], "vehicles": [cached]}}
    relayed = []

    def publish(path, evidence):
        relayed.append((path, evidence))
        return 200, {"accepted": True}

    monkeypatch.setattr(routes, "PLATFORM_GATEWAY", SimpleNamespace(
        cached_view=lambda: {"fresh": True, "projections": projections}, publish_diagnostic=publish,
    ))
    assert routes.vehicle_snapshot()["vehicles"][1]["spatial"]["public_position_usable"] is True
    now[0] += 1
    store.update_simulation_evidence(health("current", now[0]))

    row = routes.vehicle_snapshot()["vehicles"][1]
    assert row["id"] == "UAV-02"
    assert row["connected"] and row["link_quality"] == 89
    assert row["spatial"]["public_position_usable"] is False
    assert "scene_pose" not in row["spatial"]
    assert "translation_scene_ned_m" not in row["spatial"]
    assert row["pose_source"] == "px4_telemetry"
    assert row["pose"]["position_m"]["y"] == 2.0
    assert cached["spatial"]["public_position_usable"] is True  # projection only, not cache mutation

    assert post_calibration(sample("prior", now[0], node="UAV-02"))[0] == 400
    assert relayed == []
    assert post_calibration(sample("current", now[0], node="UAV-02"))[0] == 200
    assert len(relayed) == 1
