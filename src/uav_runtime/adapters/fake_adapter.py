"""本轮最后修补点：适配 gateway command 下游路径，fake adapter 仅消费 command/intention。"""
from __future__ import annotations


class FakeAdapter:
    name = "fake"

    def execute(self, command: dict) -> dict:
        # fake/stub: no real protocol execution
        return {
            "accepted": True,
            "detail": "simulated",
            "adapter": self.name,
            "command": command,
        }
