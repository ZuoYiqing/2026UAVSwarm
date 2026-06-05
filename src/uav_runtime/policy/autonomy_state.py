"""自治/接管待处理状态辅助判断。"""
from __future__ import annotations

from uav_runtime.protocol.enums import AutonomyState, LinkState


def should_enter_local_autonomy(link_state: LinkState) -> bool:
    return link_state == LinkState.LOST


def can_handover_back(state: AutonomyState, link_state: LinkState) -> bool:
    return state == AutonomyState.WAIT_HANDOVER and link_state != LinkState.LOST
