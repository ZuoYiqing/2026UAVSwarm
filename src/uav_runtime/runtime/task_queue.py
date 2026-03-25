"""内存 FIFO 任务队列骨架。"""
from __future__ import annotations

from collections import deque


class TaskQueue:
    def __init__(self) -> None:
        self._q: deque[dict] = deque()

    def put(self, task: dict) -> None:
        self._q.append(task)

    def get(self) -> dict | None:
        return self._q.popleft() if self._q else None

    def __len__(self) -> int:
        return len(self._q)
