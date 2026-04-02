"""v0.1 baseline：fake adapter 仅消费 gateway 下发的 command 对象。"""
from __future__ import annotations

import time
from typing import Any


class FakeAdapter:
    name = "fake"

    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        # fake/stub: no real protocol execution
        sim = command.get("_simulate") if isinstance(command, dict) else None
        sim = sim if isinstance(sim, dict) else {}

        delay_ms = int(sim.get("delay_ms", 0) or 0)
        if delay_ms > 0:
            # keep delay lightweight for test/demo
            delay_ms = min(delay_ms, 50)
            time.sleep(delay_ms / 1000.0)

        if sim.get("timeout"):
            return {
                "accepted": False,
                "code": "exec_timeout",
                "message": "simulated timeout",
                "detail": "timeout",
                "adapter": self.name,
                "evidence_ref": "sim://timeout",
                "execution_trace": {"mode": "fake", "delay_ms": delay_ms, "simulate": "timeout"},
            }

        if sim.get("fail"):
            return {
                "accepted": False,
                "code": "exec_failed",
                "message": "simulated failure",
                "detail": "failed",
                "adapter": self.name,
                "evidence_ref": "sim://failure",
                "execution_trace": {"mode": "fake", "delay_ms": delay_ms, "simulate": "fail"},
            }

        return {
            "accepted": True,
            "code": "exec_ok",
            "message": "simulated success",
            "detail": "simulated",
            "adapter": self.name,
            "evidence_ref": "sim://ok",
            "execution_trace": {"mode": "fake", "delay_ms": delay_ms, "simulate": "success"},
            "command": command,
        }
