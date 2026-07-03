"""进程内事件总线骨架。"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[dict], None]]] = defaultdict(list)

    def subscribe(self, topic: str, fn: Callable[[dict], None]) -> None:
        self._subs[topic].append(fn)

    def publish(self, topic: str, event: dict) -> None:
        for fn in self._subs.get(topic, []):
            fn(event)
