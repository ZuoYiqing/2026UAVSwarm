"""Adapter 协议接口（v0.1 baseline：与当前 command 级执行路径一致）。"""
from __future__ import annotations

from typing import Any, Protocol


class Adapter(Protocol):
    """v0.1 baseline 接口约定。

    当前 adapter 层输入是 command 级对象（由 gateway 构造），
    不是原始 ActionRequest。
    """

    name: str

    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        ...
