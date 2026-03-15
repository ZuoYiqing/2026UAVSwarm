"""canonical action request -> adapter command 映射。"""
from __future__ import annotations

from uav_runtime.protocol.schema import ActionRequest


def to_adapter_command(req: ActionRequest) -> dict:
    return {
        "cmd": req.action,
        "args": req.params,
        "meta": {
            "source": req.source.value,
            "scope": req.scope.value,
            "priority": req.priority,
        },
    }
