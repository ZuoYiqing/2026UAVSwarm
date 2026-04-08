"""MAVLink adapter stub contract tests."""
from __future__ import annotations

from uav_runtime.adapters.gateway import AdapterGateway
from uav_runtime.adapters.mavlink_adapter import MavlinkAdapter
from uav_runtime.protocol.enums import AuthorityScope, CommandSource
from uav_runtime.protocol.schema import ActionRequest


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


def test_mavlink_adapter_returns_contract_complete_unavailable_result() -> None:
    adapter = MavlinkAdapter()

    raw = adapter.execute({"command": "takeoff", "arguments": {}, "meta": {}})

    assert raw["accepted"] is False
    assert raw["code"] == "exec_unavailable"
    assert raw["message"] == "mavlink_stub_unavailable"
    assert raw["detail"] == "unavailable"
    assert raw["adapter"] == "mavlink"
    assert raw["evidence_ref"] == "stub://mavlink/unavailable"
    assert isinstance(raw["execution_trace"], dict)
    assert raw["execution_trace"]["mode"] == "mavlink_stub"


def test_gateway_can_dispatch_to_registered_mavlink_adapter_stub() -> None:
    gateway = AdapterGateway()
    gateway.register(MavlinkAdapter())

    out = gateway.execute("mavlink", _req("takeoff"))

    assert out["accepted"] is False
    assert out["status"] == "rejected"
    assert out["code"] == "exec_unavailable"
    assert out["message"] == "mavlink_stub_unavailable"
    assert out["adapter"] == "mavlink"
    assert out["execution_trace"]["mode"] == "mavlink_stub"
