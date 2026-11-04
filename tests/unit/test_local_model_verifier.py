"""Verifier guard/fixture tests never load a model or bind a PX4 endpoint."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import socket

import pytest


@pytest.fixture
def verifier():
    path = Path(__file__).resolve().parents[2] / "scripts/verify_local_model_runtime.py"
    spec = importlib.util.spec_from_file_location("local_model_verifier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def memory_sources(monkeypatch, verifier, *, wsl=True, available_kib=6 * 1024**2):
    class Files:
        def __init__(self, path):
            self.path = path

        def read_text(self):
            return (f"MemAvailable: {available_kib} kB\n" if self.path == "/proc/meminfo"
                    else "microsoft-standard-WSL2" if wsl else "generic-linux")

    monkeypatch.setattr(verifier, "Path", Files)
    monkeypatch.setattr(verifier.time, "time", lambda: 1000)


@pytest.mark.parametrize("host,measured", [(None, None), (2.9, 1000), (5, 939), (5, 1001),
                                           (float("nan"), 1000), (float("inf"), 1000),
                                           (5, float("nan"))])
def test_wsl_requires_fresh_finite_host_memory_proof(monkeypatch, verifier, host, measured):
    memory_sources(monkeypatch, verifier)
    with pytest.raises(RuntimeError):
        verifier.available_memory(host, measured)


def test_wsl_does_not_add_guest_and_host_memory(monkeypatch, verifier):
    memory_sources(monkeypatch, verifier, available_kib=2 * 1024**2)
    with pytest.raises(RuntimeError, match="3 GiB"):
        verifier.available_memory(8, 1000)


def test_valid_wsl_proof_and_native_linux_memory(monkeypatch, verifier):
    memory_sources(monkeypatch, verifier)
    assert verifier.available_memory(5, 1000)["windows_available_gib"] == 5
    memory_sources(monkeypatch, verifier, wsl=False)
    assert verifier.available_memory() == {"linux_available_gib": 6}


@pytest.mark.parametrize("action", ["takeoff", "hold_position", "land"])
def test_synthetic_requests_are_explicitly_fake_and_bounded(verifier, action):
    body = verifier.candidate_request(1, action)
    assert body["observation"]["source"] == "fake"
    assert body["decision_timeout_ms"] == 2000
    assert body["snapshot_id"] == body["request_id"]
    assert body["next_step"]["action"] == action
    assert {o["option_id"] for o in body["allowed_options"]} == {"execute_authorized_step", "abort_to_land"}
    assert body["authorization"]["max_altitude_m"] == 3
    assert body["authorization"]["max_hold_s"] == 10


@pytest.mark.skipif(os.name != "posix", reason="Linux verifier uses Linux TCP reuse semantics")
def test_port_probe_never_takes_an_existing_listener(verifier):
    with socket.socket() as owner:
        owner.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        owner.bind(("127.0.0.1", 0))
        owner.listen(1)
        port = owner.getsockname()[1]
        with pytest.raises(OSError):
            verifier.ensure_ports_available((port,))
    verifier.ensure_ports_available((port,))
