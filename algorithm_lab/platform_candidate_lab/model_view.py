"""Versioned, bounded decision view for the local model.

The full Runtime request is validated and hashed before this view is built.
Identity, correlation and duplicated option parameters remain in that full
request and response evidence, but do not consume the model's context window.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .contracts import utc_time


MODEL_VIEW_VERSION = "uav02_candidate_view_v1"


def build_model_view(request: dict[str, Any], *, now: datetime,
                     observation_age_s: float) -> dict[str, Any]:
    """Keep all local observations and decision limits, omit correlation IDs.

    Call only after validate_request and the time/source prechecks in decide.
    The two option IDs have fixed meanings, and validate_request already
    proves the execute option equals next_step and the abort option is LAND.
    """
    authorization = request["authorization"]
    expires_in_s = (
        utc_time(authorization["expires_at"], "AUTHORIZATION_EXPIRY") - now
    ).total_seconds()
    step = request["next_step"]
    return {
        "view_version": MODEL_VIEW_VERSION,
        "authorization": {
            "expires_in_ms": max(0, round(expires_in_s * 1000)),
            "max_altitude_m": authorization["max_altitude_m"],
            "max_hold_s": authorization["max_hold_s"],
            "offline_policy": authorization["offline_policy"],
        },
        "ground_link": request["ground_link"],
        "next_step": {"action": step["action"], "params": step["params"]},
        "observation": request["observation"],
        "observation_age_ms": round(observation_age_s * 1000),
        "options": ["execute_authorized_step", "abort_to_land"],
    }
