"""MAVLink adapter stub contract and mapping-skeleton tests."""
from __future__ import annotations

import pytest

from uav_runtime.adapters.gateway import AdapterGateway
from uav_runtime.adapters.mavlink_adapter import MavlinkAdapter
from uav_runtime.adapters.mavlink_backend_config import MavlinkBackendConfig
from uav_runtime.protocol.enums import AuthorityScope, CommandSource
from uav_runtime.protocol.schema import ActionRequest

SUPPORTED = ["takeoff", "goto", "hover", "land", "return_home"]


def _req(action: str = "hover") -> ActionRequest:
    return ActionRequest(
        action=action,
        params={},
        source=CommandSource.SELF_LOCAL,
        scope=AuthorityScope.SELF_ONLY,
    )


def test_mavlink_adapter_has_expected_name_for_registration() -> None:
    adapter = MavlinkAdapter()
    assert adapter.name == "mavlink"


@pytest.mark.parametrize("command", SUPPORTED)
def test_stub_mode_supported_commands_keep_unavailable_semantics(command: str) -> None:
    adapter = MavlinkAdapter(MavlinkBackendConfig(backend_mode="stub", backend_enabled=False))

    raw = adapter.execute({"command": command, "arguments": {"sample": 1}, "meta": {}})

    assert raw["accepted"] is False
    assert raw["code"] == "exec_unavailable"
    assert raw["message"] == "mavlink_stub_unavailable"
    assert raw["detail"] == "unavailable"
    assert raw["adapter"] == "mavlink"
    assert raw["execution_trace"]["backend_mode"] == "stub"
    assert raw["execution_trace"]["action"] == command
    assert isinstance(raw["execution_trace"]["mapped_action"], str)
    assert isinstance(raw["execution_trace"]["param_hints"], list)


def test_stub_mode_unsupported_command_returns_exec_unsupported() -> None:
    adapter = MavlinkAdapter(MavlinkBackendConfig(backend_mode="stub", backend_enabled=False))

    raw = adapter.execute({"command": "start_stream", "arguments": {}, "meta": {}})

    assert raw["accepted"] is False
    assert raw["code"] == "exec_unsupported"
    assert raw["message"] == "mavlink_stub_unsupported_command"
    assert raw["detail"] == "unsupported"
    assert raw["execution_trace"]["backend_mode"] == "stub"
    assert raw["execution_trace"]["supported"] is False


@pytest.mark.parametrize("command", SUPPORTED)
def test_sitl_mode_disabled_returns_not_configured_semantics(command: str) -> None:
    adapter = MavlinkAdapter(
        MavlinkBackendConfig(
            backend_mode="sitl",
            backend_enabled=False,
            transport_endpoint="udp://127.0.0.1:14540",
            timeout_ms=5000,
            retry_count=1,
        )
    )

    raw = adapter.execute({"command": command, "arguments": {}, "meta": {}})

    assert raw["accepted"] is False
    assert raw["code"] == "sitl_not_configured"
    assert raw["message"] == "mavlink_sitl_not_configured"
    assert raw["detail"] == "not_configured"
    assert raw["adapter"] == "mavlink"
    assert raw["execution_trace"]["mode"] == "mavlink_sitl"
    assert raw["execution_trace"]["backend_mode"] == "sitl"
    assert raw["execution_trace"]["backend_enabled"] is False
    assert raw["execution_trace"]["connect_timeout_ms"] == 3000


def test_sitl_mode_disabled_unsupported_command_still_exec_unsupported() -> None:
    adapter = MavlinkAdapter(MavlinkBackendConfig(backend_mode="sitl", backend_enabled=False))

    raw = adapter.execute({"command": "start_stream", "arguments": {}, "meta": {}})

    assert raw["accepted"] is False
    assert raw["code"] == "exec_unsupported"
    assert raw["detail"] == "unsupported"


def test_sitl_mode_enabled_without_endpoint_returns_probe_failed() -> None:
    adapter = MavlinkAdapter(
        MavlinkBackendConfig(
            backend_mode="sitl",
            backend_enabled=True,
            timeout_ms=5000,
            retry_count=1,
        )
    )

    raw = adapter.execute({"command": "takeoff", "arguments": {}, "meta": {}})

    assert raw["accepted"] is False
    assert raw["code"] == "backend_probe_failed"
    assert raw["message"] == "mavlink_sitl_backend_probe_failed"
    assert raw["detail"] == "probe_failed"
    assert raw["execution_trace"]["session_status"] == "not_connected"
    assert raw["execution_trace"]["delegated_backend"] == "sitl_backend_stub"
    assert raw["execution_trace"]["backend_impl"] == "sitl_backend_stub"
    assert raw["execution_trace"]["connect_timeout_ms"] == 3000


def test_sitl_mode_enabled_with_endpoint_returns_smoke_not_connected() -> None:
    adapter = MavlinkAdapter(
        MavlinkBackendConfig(
            backend_mode="sitl",
            backend_enabled=True,
            transport_endpoint="udp://127.0.0.1:14540",
            timeout_ms=5000,
            retry_count=1,
        )
    )

    raw = adapter.execute({"command": "takeoff", "arguments": {}, "meta": {}})

    assert raw["accepted"] is False
    assert raw["code"] == "smoke_not_connected"
    assert raw["message"] == "mavlink_sitl_smoke_not_connected"
    assert raw["detail"] == "not_connected"


@pytest.mark.parametrize("action", SUPPORTED)
def test_gateway_can_dispatch_supported_actions_to_mavlink_stub(action: str) -> None:
    gateway = AdapterGateway()
    gateway.register(MavlinkAdapter())

    out = gateway.execute("mavlink", _req(action))

    assert out["accepted"] is False
    assert out["status"] == "rejected"
    assert out["code"] == "exec_unavailable"
    assert out["adapter"] == "mavlink"


def test_gateway_dispatches_unsupported_action_with_stable_code() -> None:
    gateway = AdapterGateway()
    gateway.register(MavlinkAdapter())

    out = gateway.execute("mavlink", _req("start_stream"))

    assert out["accepted"] is False
    assert out["status"] == "rejected"
    assert out["code"] == "exec_unsupported"
    assert out["message"] == "mavlink_stub_unsupported_command"


def test_takeoff_smoke_wiring_trace_tags_are_stable() -> None:
    adapter = MavlinkAdapter(
        MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udp://127.0.0.1:14540")
    )

    raw = adapter.execute({"command": "takeoff", "arguments": {}, "meta": {}})

    assert raw["code"] == "smoke_not_connected"
    assert raw["execution_trace"]["smoke_action"] is True
    assert raw["execution_trace"]["smoke_path"] == "takeoff_sitl_wiring_v1"


def test_non_takeoff_command_does_not_mark_smoke_action() -> None:
    adapter = MavlinkAdapter(
        MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udp://127.0.0.1:14540")
    )

    raw = adapter.execute({"command": "hover", "arguments": {}, "meta": {}})

    assert raw["code"] == "smoke_not_connected"
    assert raw["execution_trace"]["smoke_action"] is False
    assert raw["execution_trace"]["smoke_path"] is None


def test_sitl_enabled_path_uses_backend_builder_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = MavlinkAdapter(
        MavlinkBackendConfig(backend_mode="sitl", backend_enabled=True, transport_endpoint="udp://127.0.0.1:14540")
    )
    called = {"count": 0}

    original = adapter._build_sitl_backend

    def _wrapped(session):
        called["count"] += 1
        return original(session)

    monkeypatch.setattr(adapter, "_build_sitl_backend", _wrapped)
    raw = adapter.execute({"command": "takeoff", "arguments": {}, "meta": {}})

    assert called["count"] == 1
    assert raw["code"] == "smoke_not_connected"
