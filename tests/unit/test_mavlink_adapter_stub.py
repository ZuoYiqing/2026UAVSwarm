"""MAVLink adapter stub contract and mapping-skeleton tests."""
from __future__ import annotations

import pytest

from uav_runtime.adapters.gateway import AdapterGateway
from uav_runtime.adapters.mavlink_adapter import MavlinkAdapter
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
def test_supported_commands_have_stable_mapping_skeleton_trace(command: str) -> None:
    adapter = MavlinkAdapter()

    raw = adapter.execute({"command": command, "arguments": {"sample": 1}, "meta": {}})

    assert raw["accepted"] is False
    assert raw["code"] == "exec_unavailable"
    assert raw["message"] == "mavlink_stub_unavailable"
    assert raw["detail"] == "unavailable"
    assert raw["adapter"] == "mavlink"
    assert raw["evidence_ref"] == "stub://mavlink/unavailable"
    assert raw["execution_trace"]["mode"] == "mavlink_stub"
    assert raw["execution_trace"]["action"] == command
    assert isinstance(raw["execution_trace"]["mapped_action"], str)
    assert isinstance(raw["execution_trace"]["param_hints"], list)
    assert raw["execution_trace"]["placeholder"] is True


def test_unsupported_command_returns_stable_unsupported_semantics() -> None:
    adapter = MavlinkAdapter()

    raw = adapter.execute({"command": "start_stream", "arguments": {}, "meta": {}})

    assert raw["accepted"] is False
    assert raw["code"] == "exec_unsupported"
    assert raw["message"] == "mavlink_stub_unsupported_command"
    assert raw["detail"] == "unsupported"
    assert raw["adapter"] == "mavlink"
    assert raw["evidence_ref"] == "stub://mavlink/unsupported"
    assert raw["execution_trace"]["supported"] is False


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
