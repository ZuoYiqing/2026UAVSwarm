"""v0.1 baseline：fake adapter 仅消费 gateway 下发的 command 对象。"""
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
