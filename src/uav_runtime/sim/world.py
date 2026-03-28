from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AgentState:
    x: int
    y: int


@dataclass(slots=True)
class World:
    width: int
    height: int
    agents: list[AgentState]

    @classmethod
    def create(cls, width: int, height: int, n_agents: int) -> "World":
        agents = [AgentState(x=i, y=i) for i in range(n_agents)]
        return cls(width=width, height=height, agents=agents)

    def tick(self) -> None:
        for a in self.agents:
            a.x = (a.x + 1) % self.width
            a.y = (a.y + 1) % self.height

    def coverage_ratio(self) -> float:
        cells = {(a.x, a.y) for a in self.agents}
        return len(cells) / float(self.width * self.height)
