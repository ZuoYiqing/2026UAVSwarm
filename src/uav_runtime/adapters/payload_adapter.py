"""Payload/device adapter skeleton for non-destructive onboard devices.

The adapter is intentionally hardware-free.  It validates placeholder action
metadata and returns contract-compatible raw results for future camera, gimbal,
speaker, light, sensor, and health-monitor integrations.
"""
from __future__ import annotations

from typing import Any

from uav_runtime.adapters.payload_mapping import resolve_payload_mapping


class PayloadAdapter:
    """Non-destructive payload/device adapter skeleton.

    This class does not connect to real payload hardware and does not enforce
    policy.  Runtime requests must still pass through Policy Gate before this
    adapter is selected by the execution path.
    """

    name = "payload"

    def _unsupported(self, action: str) -> dict[str, Any]:
        # Unsupported means "this payload skeleton has no safe placeholder mapping".
        # Dangerous actions should normally be denied by Policy Gate before reaching this adapter.
        return {
            "accepted": False,
            "code": "exec_unsupported",
            "message": "payload_device_unsupported_action",
            "detail": "unsupported",
            "adapter": self.name,
            "evidence_ref": "payload://unsupported",
            "execution_trace": {
                "mode": "payload_device_stub",
                "action": action,
                "supported": False,
                "reason": "mapping_not_defined",
            },
        }

    def _missing_params(self, action: str, missing: list[str], mapping: dict[str, Any]) -> dict[str, Any]:
        # Some future payload actions need parameters (for example gimbal angle).
        # We validate presence only; no real device command is sent in this stage.
        return {
            "accepted": False,
            "code": "payload_param_missing",
            "message": "payload_device_required_param_missing",
            "detail": "missing_required_params",
            "adapter": self.name,
            "evidence_ref": f"payload://{mapping['device_type']}/param_missing",
            "execution_trace": {
                "mode": "payload_device_stub",
                "action": action,
                "device_type": mapping["device_type"],
                "placeholder_action": mapping["placeholder_action"],
                "supported": True,
                "validated": False,
                "missing_params": missing,
                "safe_non_destructive": bool(mapping.get("safe_non_destructive", False)),
            },
        }

    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        # The gateway passes {"command": action_type, "arguments": params, ...}.
        # Keep this adapter deterministic and hardware-free so tests never require cameras/gimbals/speakers.
        cmd = command if isinstance(command, dict) else {}
        action = str(cmd.get("command", "") or "")
        args = cmd.get("arguments") if isinstance(cmd.get("arguments"), dict) else {}

        mapping = resolve_payload_mapping(action)
        if mapping is None:
            return self._unsupported(action)

        required_params = list(mapping.get("required_params") or [])
        missing = [name for name in required_params if name not in args]
        if missing:
            return self._missing_params(action, missing, mapping)

        # Placeholder success: "mapping exists and required params are present".
        # This is not hardware success and must not be described as real capture/angle/audio/light execution.
        return {
            "accepted": True,
            "code": "payload_placeholder_ok",
            "message": "payload_device_placeholder_result",
            "detail": "placeholder",
            "adapter": self.name,
            "evidence_ref": f"payload://{mapping['device_type']}/placeholder",
            "execution_trace": {
                "mode": "payload_device_stub",
                "action": action,
                "device_type": mapping["device_type"],
                "placeholder_action": mapping["placeholder_action"],
                "supported": True,
                "validated": True,
                "args_keys": sorted(args.keys()),
                "required_params": required_params,
                "optional_params": list(mapping.get("optional_params") or []),
                "safe_non_destructive": bool(mapping.get("safe_non_destructive", False)),
                "hardware_connected": False,
                "policy_enforced_in_adapter": False,
            },
        }
