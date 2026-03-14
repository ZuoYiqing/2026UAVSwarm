"""fake adapter 模拟执行结果。"""
from __future__ import annotations

from uav_runtime.adapters.mappers.canonical_mapper import to_adapter_command
from uav_runtime.protocol.schema import ActionRequest


class FakeAdapter:
    name = "fake"

    def execute(self, request: ActionRequest) -> dict:
        cmd = to_adapter_command(request)
        return {"accepted": True, "detail": "simulated", "adapter": self.name, "command": cmd}
