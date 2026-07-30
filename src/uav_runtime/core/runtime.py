from __future__ import annotations

from dataclasses import dataclass

from uav_runtime.adapters.fake_adapter import FakeAdapter
from uav_runtime.adapters.gateway import AdapterGateway
from uav_runtime.core.mission import Mission
from uav_runtime.core.planner import RulePlanner
from uav_runtime.core.protocol import ProtocolSynthesizer
from uav_runtime.core.scene import Scene


@dataclass(slots=True)
class RuntimeResult:
    plan: dict
    protocol: dict
    dispatch: list[dict]


class Runtime:
    def __init__(self) -> None:
        self.planner = RulePlanner()
        self.protocol = ProtocolSynthesizer()
        self.gateway = AdapterGateway()
        self.gateway.register(FakeAdapter())

    def run(self, mission: Mission, scene: Scene) -> RuntimeResult:
        plan = self.planner.make_plan(mission, scene)
        proto = self.protocol.synthesize(plan)
        dispatch = []
        for msg in proto.messages:
            dispatch.append(self.gateway.send("fake", msg).__dict__)
        return RuntimeResult(plan={"mission": plan.mission, "tasks": plan.tasks}, protocol={"messages": proto.messages}, dispatch=dispatch)
