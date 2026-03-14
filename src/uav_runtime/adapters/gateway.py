"""adapter gateway，衔接 canonical 请求与 adapter 执行。"""
from __future__ import annotations

from dataclasses import dataclass, field

from uav_runtime.protocol.schema import ActionRequest


@dataclass(slots=True)
class AdapterGateway:
    adapters: dict[str, object] = field(default_factory=dict)

    def register(self, adapter: object) -> None:
        self.adapters[getattr(adapter, "name")] = adapter

    def execute(self, adapter_name: str, request: ActionRequest) -> dict:
        adapter = self.adapters.get(adapter_name)
        if adapter is None:
            return {"accepted": False, "detail": f"adapter_not_found:{adapter_name}", "adapter": adapter_name}
        return adapter.execute(request)
