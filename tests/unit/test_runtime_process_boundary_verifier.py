"""Guard tests do not launch services or connect to PX4."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location("runtime_process_verifier", Path(__file__).resolve().parents[2] / "scripts/verify_runtime_process_boundary.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


@pytest.mark.parametrize("available,measured", [(2.99, 1000), (4, 939), (4, 1001), (float("nan"), 1000)])
def test_memory_guard_rejects_low_stale_future_or_nonfinite(available, measured):
    with pytest.raises(RuntimeError, match="fresh_host_memory"):
        verifier.memory_admission(available, measured, now=1000)


def test_memory_guard_accepts_fresh_measurement():
    verifier.memory_admission(3, 999, now=1000)


@pytest.fixture
def responses():
    return ({"vehicles": [{"id": f"UAV-0{n}", "connected": False, "telemetry": {"stale": True},
                           "spatial": {"public_position_usable": False}} for n in (1, 2, 3)]},
            {"fresh": False}, {"status": "unknown"},
            {"vehicles": [{"heartbeat_fresh": False, "telemetry_fresh": False} for _ in range(3)],
             "execution_authorized": False, "flight_command_sent": False})


def test_unknown_projection_is_not_mislabeled_live(responses):
    verifier.assert_offline_projections(*responses)


@pytest.mark.parametrize("bad", ["missing_node", "connected", "position_usable", "telemetry", "gazebo", "heartbeat"])
def test_false_live_or_missing_node_fails_check(responses, bad):
    snapshot, telemetry, simulation, evidence = deepcopy(responses)
    if bad == "missing_node": snapshot["vehicles"].pop()
    elif bad == "connected": snapshot["vehicles"][1]["connected"] = True
    elif bad == "position_usable": snapshot["vehicles"][1]["spatial"]["public_position_usable"] = True
    elif bad == "telemetry": telemetry["fresh"] = True
    elif bad == "gazebo": simulation["status"] = "ready"
    else: evidence["vehicles"][1]["heartbeat_fresh"] = True
    with pytest.raises(RuntimeError, match="became_live"):
        verifier.assert_offline_projections(snapshot, telemetry, simulation, evidence)
