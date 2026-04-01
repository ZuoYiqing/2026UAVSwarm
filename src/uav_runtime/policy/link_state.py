"""链路状态转移合法性定义。"""
from __future__ import annotations

from uav_runtime.protocol.enums import LinkState


ALLOWED_LINK_TRANSITIONS: set[tuple[LinkState, LinkState]] = {
    (LinkState.HEALTHY, LinkState.DEGRADED),
    (LinkState.DEGRADED, LinkState.HEALTHY),
    (LinkState.DEGRADED, LinkState.LOST),
    (LinkState.LOST, LinkState.DEGRADED),
    (LinkState.HEALTHY, LinkState.LOST),
}


def is_valid_link_transition(old: LinkState, new: LinkState) -> bool:
    return old == new or (old, new) in ALLOWED_LINK_TRANSITIONS
