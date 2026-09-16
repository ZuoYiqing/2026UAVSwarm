"""Physical-frame counterexamples and fail-closed evidence boundaries."""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from simulation.px4_gazebo import calibration as cal
from simulation.px4_gazebo.evidence import freshness
from simulation.px4_gazebo.gazebo_evidence import clock_summary
from simulation.px4_gazebo.runtime_evidence import prepare_publication, publish


def _pairs():
    # Independent ENU -> NED expected values, including a measured z datum.
    return [{"sim_time_s": i * .2, "skew_s": .004, "model_id": 68,
             "scene_position": {"frame": "scene_ned", "x_m": i*.2+1.2, "y_m": i*.3+7.8, "z_m": -i*.2+.04},
             "vehicle_local_position": {"frame": "vehicle_local_ned", "x_m": i*.2, "y_m": i*.3, "z_m": -i*.2}}
            for i in range(20)]


def _calibration(before=None, after=None, pairs=None):
    context = {"run_id": "run-1", "origin": {"ref_timestamp": 123, "xy_reset_counter": 2, "z_reset_counter": 3},
               "process_identity": {"pid": 12, "proc_start_time_ticks": 4321}}
    return cal.build_calibration({"node_id": "UAV-02", "spawn_ned": {"x_m": 0, "y_m": 8, "z_m": 0, "yaw_deg": 90}},
                                  {"scene_id": "simple_recon_v0_1"}, pairs or _pairs(), before or context, after or context)


def test_calibration_measures_translation_from_independent_world_and_local_samples():
    result = _calibration()
    assert result["translation_scene_ned_m"] == pytest.approx({"north": 1.2, "east": 7.8, "down": .04})
    assert result["evidence"]["maximum_residual_m"] < 1e-12
    assert all(result["evidence"]["physical_axes_exercised"].values())


@pytest.mark.parametrize("key", ["run_id", "origin", "process_identity"])
def test_calibration_rejects_restart_or_origin_reset(key):
    result = _calibration()
    before = {k:v for k,v in result["context"].items() if k != "model_id"}
    after = copy.deepcopy(before)
    after[key] = "changed"
    with pytest.raises(ValueError, match="origin_or_process_reset"):
        _calibration(before, after)
    with pytest.raises(ValueError, match="origin_process_or_model_changed"):
        cal.check_context(result, after)


def test_calibration_rejects_model_replacement_and_incoherent_samples():
    pairs = _pairs()
    pairs[-1]["model_id"] = 69
    with pytest.raises(ValueError, match="model_respawned"):
        _calibration(pairs=pairs)
    pairs = _pairs()
    pairs[-1]["scene_position"]["x_m"] += 4
    with pytest.raises(ValueError, match="residual_exceeded"):
        _calibration(pairs=pairs)


@pytest.mark.parametrize("rotation", [90, -10, float("nan")])
def test_unverified_nonzero_frame_rotation_is_rejected(rotation):
    with pytest.raises(ValueError, match="unsupported_frame_rotation"):
        cal.aligned_translation({"x_m": 0, "y_m": 0, "z_m": 0, "frame_rotation_deg": rotation})


def test_static_calibration_does_not_claim_motion_axis_verification():
    pairs = _pairs()
    for pair in pairs:
        pair["scene_position"] = {"x_m": 0, "y_m": 8, "z_m": .013}
        pair["vehicle_local_position"] = {"x_m": .01, "y_m": .02, "z_m": -.03}
    result = _calibration(pairs=pairs)
    assert not any(result["evidence"]["physical_axes_exercised"].values())


def test_time_pairing_uses_sim_time_not_vehicle_heading_or_wall_delay():
    poses = [{"header": {"stamp": {"sec": 2}}, "pose": [
        {"name": "x500_1", "id": 68, "position": {"x": 8, "y": 4, "z": 3}}]}]
    samples = [{"time_boot_ms": 2004, "x_m": 1, "y_m": 2, "z_m": -3},
               {"time_boot_ms": 3000, "x_m": 1, "y_m": 2, "z_m": -3}]
    pairs = cal.pair_samples(poses, samples, "x500_1")
    assert len(pairs) == 1
    assert pairs[0]["scene_position"] == {"frame": "scene_ned", "x_m": 4, "y_m": 8, "z_m": -3}


def test_saved_evidence_cannot_refresh_its_own_timestamp():
    now = datetime(2026, 9, 12, tzinfo=timezone.utc).timestamp()
    evidence = {"contract_version": "1.0", "source_timestamp": "2026-09-12T00:00:00Z", "valid_for_ms": 1000}
    assert freshness(evidence, now=now+.5)[0]
    assert freshness(evidence, now=now+2)[1] == "evidence_stale"
    assert freshness(evidence, now=now-1)[1] == "evidence_from_future"
    evidence["valid_for_ms"] = True
    assert not freshness(evidence, now=now)[0]


def _clocks(sim_step):
    return [{"sim": {"sec": int(i*sim_step), "nsec": int((i*sim_step % 1)*1e9)},
             "real": {"sec": i//2, "nsec": (i%2)*500000000}} for i in range(5)]


def test_clock_requires_wall_window_and_reports_pause_slow_or_reset():
    assert clock_summary(_clocks(.5))["clock_advancing"]
    assert clock_summary(_clocks(0))["reason"] == "gazebo_clock_stalled"
    assert clock_summary(_clocks(.05))["reason"] == "gazebo_clock_slow"
    assert clock_summary(_clocks(.5)[:2])["reason"] == "gazebo_clock_insufficient_samples"
    messages = _clocks(.5)
    messages[-1]["sim"] = {"sec": 0}
    assert clock_summary(messages)["reason"] == "gazebo_clock_reset"


def test_publication_preserves_sample_time_and_consumes_elapsed_ttl():
    evidence = {"contract_version": "1.0", "source_timestamp": "2026-09-12T00:00:00Z", "valid_for_ms": 5000}
    now = datetime(2026, 9, 12, tzinfo=timezone.utc).timestamp()
    result = prepare_publication(evidence, now=now+2)
    assert result["source_timestamp"] == evidence["source_timestamp"]
    assert result["valid_for_ms"] == 3000
    assert evidence["valid_for_ms"] == 5000
    with pytest.raises(ValueError, match="stale"):
        prepare_publication(evidence, now=now+6)
    with pytest.raises(ValueError, match="ttl_exhausted"):
        prepare_publication(evidence, now=now+4.95)


@pytest.mark.parametrize("url", ["https://example.com/api", "http://127.0.0.1/actions", "http://user:password@localhost/api", "http://localhost/api?x=1"])
def test_publisher_refuses_non_evidence_destinations_without_network(url):
    with pytest.raises(ValueError, match="loopback_api"):
        publish(url, {})
