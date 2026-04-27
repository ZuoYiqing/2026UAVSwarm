from __future__ import annotations

from .messages import CanonicalMessage
from .schema import validate_canonical_payload


def map_plan_to_message(plan_action: dict, source: str = "planner", target: str = "executor") -> CanonicalMessage:
    payload = {
        "msg_type": plan_action.get("action", "noop"),
        "source": source,
        "target": target,
        "body": {"params": plan_action.get("params", {})},
    }
    validate_canonical_payload(payload)
    return CanonicalMessage(**payload)
