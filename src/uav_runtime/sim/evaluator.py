from __future__ import annotations

from dataclasses import dataclass

from .comms import LinkModel
from .world import World


@dataclass(slots=True)
class SimReport:
    steps: int
    coverage: float
    sent: int
    delivered: int
    dropped: int


def run_episode(width: int, height: int, n_agents: int, steps: int, drop_rate: float) -> SimReport:
    world = World.create(width, height, n_agents)
    link = LinkModel(drop_rate=drop_rate)
    delivered_total = 0
    dropped_total = 0

    for step in range(steps):
        world.tick()
        ok, dropped = link.transmit([{"step": step, "agent": i} for i in range(n_agents)])
        delivered_total += len(ok)
        dropped_total += len(dropped)

    sent = steps * n_agents
    return SimReport(
        steps=steps,
        coverage=world.coverage_ratio(),
        sent=sent,
        delivered=delivered_total,
        dropped=dropped_total,
    )
