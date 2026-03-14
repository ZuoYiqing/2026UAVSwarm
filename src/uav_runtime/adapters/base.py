"""Adapter 协议接口（确定性执行层抽象）。"""
from __future__ import annotations

from typing import Protocol

from uav_runtime.protocol.schema import ActionRequest


class Adapter(Protocol):
    name: str

    def execute(self, request: ActionRequest) -> dict:
        ...
