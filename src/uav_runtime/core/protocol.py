from __future__ import annotations

from dataclasses import dataclass

from uav_runtime.canonical.canonical_mapper import map_plan_to_message
from uav_runtime.core.planner import Plan


@dataclass(slots=True)
class ProtocolBundle:
    messages: list[dict]


class ProtocolSynthesizer:
    def synthesize(self, plan: Plan) -> ProtocolBundle:
        msgs = [map_plan_to_message(action).to_dict() for action in plan.tasks]
        return ProtocolBundle(messages=msgs)
