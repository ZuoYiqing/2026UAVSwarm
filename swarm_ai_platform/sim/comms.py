from __future__ import annotations

import random
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional

from swarm_ai_platform.sim.types import Link, Message


@dataclass
class CommsStats:
    sent: int = 0
    delivered: int = 0
    dropped: int = 0
    bytes_sent: int = 0


class MessageBus:
    """A simple discrete-time message bus with:

    - per-link packet loss
    - coarse bandwidth budgeting (bytes per second)
    - optional latency (delays delivery by N steps)

    It is designed to be deterministic given a random seed.
    """

    def __init__(self, links: List[Link], *, rng_seed: int = 7) -> None:
        self.links: Dict[tuple[str, str], Link] = {(l.src, l.dst): l for l in links}
        self.queues: Dict[str, Deque[Message]] = defaultdict(deque)  # inbox per node
        self.stats_by_type: Dict[str, CommsStats] = defaultdict(CommsStats)
        self._rng = random.Random(rng_seed)
        self._pending: List[tuple[int, Message]] = []  # (deliver_at_s, msg)
        self._bytes_budget_by_link: Dict[tuple[str, str], int] = {}

    def reset_budget(self) -> None:
        self._bytes_budget_by_link = {}

    def _estimate_bytes(self, msg: Message) -> int:
        # Very rough estimate (demo only)
        return 64 + 8 * len(msg.payload)

    def send(self, msg: Message) -> None:
        key = (msg.src, msg.dst)
        link = self.links.get(key)
        # Allow broadcast (dst='*'): deliver to any neighbor from src
        if msg.dst == "*":
            for (s, d), lk in self.links.items():
                if s == msg.src:
                    self.send(Message(msg_type=msg.msg_type, src=msg.src, dst=d, payload=msg.payload, timestamp_s=msg.timestamp_s))
            return

        bytes_len = self._estimate_bytes(msg)
        st = self.stats_by_type[msg.msg_type]
        st.sent += 1
        st.bytes_sent += bytes_len

        if link is None:
            st.dropped += 1
            return

        # bandwidth budgeting (per second, reset externally)
        budget_key = (link.src, link.dst)
        used = self._bytes_budget_by_link.get(budget_key, 0)
        cap = max(1, int(link.bandwidth_bps // 8))  # bytes per second
        if used + bytes_len > cap:
            st.dropped += 1
            return
        self._bytes_budget_by_link[budget_key] = used + bytes_len

        # loss (with a small retry budget for command-like messages, demo only)
        retries = 0
        if msg.msg_type in {"CMD_ACTION", "CLUSTER_CMD", "CMD_MISSION"}:
            retries = 2
        delivered = False
        for _ in range(retries + 1):
            if self._rng.random() >= link.loss_rate:
                delivered = True
                break
        if not delivered:
            st.dropped += 1
            return

        deliver_at = msg.timestamp_s + max(0, int(link.latency_ms / 1000.0))
        self._pending.append((deliver_at, msg))

    def step(self, now_s: int) -> None:
        # deliver pending
        remain: List[tuple[int, Message]] = []
        for t, msg in self._pending:
            if t <= now_s:
                self.queues[msg.dst].append(msg)
                self.stats_by_type[msg.msg_type].delivered += 1
            else:
                remain.append((t, msg))
        self._pending = remain

    def recv_all(self, node_id: str) -> List[Message]:
        q = self.queues[node_id]
        out = list(q)
        q.clear()
        return out
