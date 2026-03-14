from __future__ import annotations

from dataclasses import dataclass, field

from .base import AdapterResult


@dataclass(slots=True)
class AdapterGateway:
    adapters: dict[str, object] = field(default_factory=dict)

    def register(self, adapter: object) -> None:
        name = getattr(adapter, "name", None)
        if not isinstance(name, str) or not name:
            raise ValueError("adapter.name must be non-empty string")
        self.adapters[name] = adapter

    def send(self, adapter_name: str, payload: dict) -> AdapterResult:
        adapter = self.adapters.get(adapter_name)
        if adapter is None:
            return AdapterResult(False, f"adapter not found: {adapter_name}")
        return adapter.send(payload)
