"""Payload/device adapter skeleton contract tests."""
from __future__ import annotations

import pytest

from uav_runtime.adapters.gateway import AdapterGateway
from uav_runtime.adapters.payload_adapter import PayloadAdapter
from uav_runtime.adapters.payload_mapping import SUPPORTED_PAYLOAD_ACTIONS, resolve_payload_mapping
from uav_runtime.protocol.enums import AuthorityScope, CommandSource
from uav_runtime.protocol.schema import ActionRequest


SUPPORTED_COMMANDS = {
    "camera_capture": {},
    "gimbal_set_angle": {"pitch_deg": -10, "yaw_deg": 25},
    "speaker_play_message": {"message": "test message"},
    "light_set_state": {"state": "on"},
    "sensor_read": {},
    "health_query": {},
}


REQUIRED_RAW_RESULT_FIELDS = {
    "accepted",
    "code",
    "message",
    "detail",
    "adapter",
    "evidence_ref",
    "execution_trace",
}


def _req(action: str, params: dict | None = None) -> ActionRequest:
    return ActionRequest(
        action=action,
        params=params or {},
        source=CommandSource.SELF_LOCAL,
        scope=AuthorityScope.SELF_ONLY,
        action_type=action,
        skill_group="payload",
        target_set=["self"],
        risk_hint=1,
        priority_hint=50,
        requires_confirmation_hint=False,
    )


def test_payload_adapter_can_be_instantiated() -> None:
    adapter = PayloadAdapter()

    assert adapter.name == "payload"


@pytest.mark.parametrize("action,args", SUPPORTED_COMMANDS.items())
def test_supported_payload_action_returns_stable_placeholder_result(action: str, args: dict) -> None:
    adapter = PayloadAdapter()

    raw = adapter.execute({"command": action, "arguments": args, "meta": {}})

    assert raw["accepted"] is True
    assert raw["code"] == "payload_placeholder_ok"
    assert raw["message"] == "payload_device_placeholder_result"
    assert raw["detail"] == "placeholder"
    assert raw["adapter"] == "payload"
    assert raw["evidence_ref"].startswith("payload://")
    assert REQUIRED_RAW_RESULT_FIELDS.issubset(raw.keys())
    assert raw["execution_trace"]["mode"] == "payload_device_stub"
    assert raw["execution_trace"]["action"] == action
    assert raw["execution_trace"]["supported"] is True
    assert raw["execution_trace"]["hardware_connected"] is False
    assert raw["execution_trace"]["safe_non_destructive"] is True


def test_unsupported_payload_action_returns_exec_unsupported() -> None:
    adapter = PayloadAdapter()

    raw = adapter.execute({"command": "payload_release", "arguments": {}, "meta": {}})

    assert raw["accepted"] is False
    assert raw["code"] == "exec_unsupported"
    assert raw["message"] == "payload_device_unsupported_action"
    assert raw["detail"] == "unsupported"
    assert raw["adapter"] == "payload"
    assert REQUIRED_RAW_RESULT_FIELDS.issubset(raw.keys())
    assert raw["execution_trace"]["supported"] is False
    assert raw["execution_trace"]["reason"] == "mapping_not_defined"


def test_required_placeholder_params_are_validated_without_hardware() -> None:
    adapter = PayloadAdapter()

    raw = adapter.execute({"command": "gimbal_set_angle", "arguments": {"pitch_deg": 0}, "meta": {}})

    assert raw["accepted"] is False
    assert raw["code"] == "payload_param_missing"
    assert raw["detail"] == "missing_required_params"
    assert raw["execution_trace"]["missing_params"] == ["yaw_deg"]
    assert raw["execution_trace"]["validated"] is False


def test_gateway_can_dispatch_payload_adapter_with_raw_result_contract() -> None:
    gateway = AdapterGateway()
    gateway.register(PayloadAdapter())

    out = gateway.execute("payload", _req("camera_capture"))

    assert out["accepted"] is True
    assert out["status"] == "accepted"
    assert out["code"] == "payload_placeholder_ok"
    assert out["adapter"] == "payload"
    assert out["execution_trace"]["device_type"] == "camera"


def test_payload_mapping_is_limited_to_safe_non_destructive_device_classes() -> None:
    assert set(SUPPORTED_PAYLOAD_ACTIONS) == set(SUPPORTED_COMMANDS)

    device_types = {mapping["device_type"] for mapping in SUPPORTED_PAYLOAD_ACTIONS.values()}
    assert device_types == {"camera", "gimbal", "speaker", "light", "sensor", "health_monitor"}
    assert resolve_payload_mapping("payload_release") is None
