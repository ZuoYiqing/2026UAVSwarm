"""消息类型、决策码、来源、scope、链路与自治状态枚举。"""
from __future__ import annotations

from enum import Enum


class MessageType(str, Enum):
    ACTION_REQUEST = "action_request"
    POLICY_DECISION_EVENT = "policy_decision_event"
    ACTION_RESULT = "action_result"


class DecisionCode(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    PREEMPT = "preempt"


class CommandSource(str, Enum):
    GROUND_STATION = "ground_station"
    HIGHER_COMMAND = "higher_command"
    CLUSTER_HEAD = "cluster_head"
    DELEGATED_PEER = "delegated_peer"
    SELF_LOCAL = "self_local"


class AuthorityScope(str, Enum):
    SELF_ONLY = "self_only"
    PEER_CONTROL_LIMITED = "peer_control_limited"
    SUBCLUSTER_CONTROL = "subcluster_control"


class LinkState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    LOST = "lost"


class AutonomyState(str, Enum):
    REMOTE_CONTROLLED = "remote_controlled"
    LOCAL_AUTONOMY = "local_autonomy"
    WAIT_HANDOVER = "wait_handover"
