"""Standard-library-only research predictor boundary."""
import hashlib
import json
import math

HISTORY, HORIZON, DT = 8, 10, 0.1


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def number(value, name, bound):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: finite number required")
    if not math.isfinite(value) or abs(value) > bound:
        raise ValueError(f"{name}: outside research envelope")
    return float(value)


def vector(value, name, bound):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{name}: three components required")
    return [number(x, name, bound) for x in value]


def validate(request):
    fields = {"contract_version", "scene_id", "map_version", "node_id",
              "coordinate_frame", "dt_s", "snapshot_age_s", "state_history",
              "action_history", "candidate_acceleration_ned_mps2"}
    if not isinstance(request, dict) or set(request) != fields:
        raise ValueError("REQUEST_FIELDS_INVALID")
    if request["contract_version"] != "state_prediction_v0.1":
        raise ValueError("CONTRACT_VERSION_UNSUPPORTED")
    if request["coordinate_frame"] != "scene_ned":
        raise ValueError("SHARED_SCENE_NED_REQUIRED")
    for name in ("scene_id", "map_version", "node_id"):
        if not isinstance(request[name], str) or not request[name].strip():
            raise ValueError(f"{name}: nonempty identifier required")
    if number(request["dt_s"], "dt_s", 1) != DT:
        raise ValueError("TIMESTEP_UNSUPPORTED")
    if number(request["snapshot_age_s"], "snapshot_age_s", 0.5) < 0:
        raise ValueError("SNAPSHOT_AGE_INVALID")
    states = request["state_history"]
    if not isinstance(states, list) or len(states) != HISTORY:
        raise ValueError("STATE_HISTORY_LENGTH_INVALID")
    parsed, times = [], []
    for state in states:
        if not isinstance(state, dict) or set(state) != {"t_s", "position_ned_m", "velocity_ned_mps"}:
            raise ValueError("STATE_FIELDS_INVALID")
        times.append(number(state["t_s"], "t_s", 1e12))
        parsed.append(vector(state["position_ned_m"], "position", 1e4) +
                      vector(state["velocity_ned_mps"], "velocity", 30))
    if any(abs(b - a - DT) > 1e-4 for a, b in zip(times, times[1:])):
        raise ValueError("HISTORY_TIMING_INVALID")
    history, future = request["action_history"], request["candidate_acceleration_ned_mps2"]
    if not isinstance(history, list) or len(history) != HISTORY - 1:
        raise ValueError("ACTION_HISTORY_LENGTH_INVALID")
    if not isinstance(future, list) or not 1 <= len(future) <= HORIZON:
        raise ValueError("HORIZON_UNSUPPORTED")
    return parsed, [vector(a, "history_action", 4) for a in history], [vector(a, "candidate_action", 4) for a in future]


def features(states, actions):
    origin, result = states[-1][:3], []
    for state in states:
        result.extend((state[i] - origin[i]) / 2 for i in range(3))
        result.extend(v / 3 for v in state[3:])
    for action in actions:
        result.extend(a / 2 for a in action)
    return result


def integrate(state, acceleration):
    velocity = [state[i + 3] + DT * acceleration[i] for i in range(3)]
    position = [state[i] + DT * (state[i + 3] + velocity[i]) / 2 for i in range(3)]
    return position + velocity
