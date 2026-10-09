"""Toy point-mass plant: lag, drag, wind. Not quadrotor/SITL physics."""
import math
import random
from .contracts import DT, HISTORY, HORIZON, features, integrate


def dataset(seed, episodes):
    rng, windows, domains = random.Random(seed), [], []
    for index in range(episodes):
        domain = {"domain_id": f"{seed}:{index}", "lag_s": rng.uniform(0.12, 0.4),
                  "drag": rng.uniform(0.08, 0.35), "wind": [rng.uniform(-0.2, 0.2) for _ in range(3)]}
        domains.append(domain)
        state = [rng.uniform(-3, 3) for _ in range(3)] + [rng.uniform(-1, 1) for _ in range(3)]
        acceleration = [0.0] * 3
        amplitude = [rng.uniform(0.3, 1.5) for _ in range(3)]
        frequency = [rng.uniform(0.4, 1.8) for _ in range(3)]
        phase = [rng.uniform(-math.pi, math.pi) for _ in range(3)]
        states, actions = [state], []
        for t in range(80):
            action = [amplitude[i] * math.sin(frequency[i] * DT * t + phase[i]) for i in range(3)]
            beta = 1 - math.exp(-DT / domain["lag_s"])
            acceleration = [a + beta * (u - a) for a, u in zip(acceleration, action)]
            effective = [acceleration[i] - domain["drag"] * state[i + 3] + domain["wind"][i] for i in range(3)]
            state = integrate(state, effective)
            states.append(state)
            actions.append(action)
        for start in range(HISTORY - 1, 80 - HORIZON + 1, 10):
            history = states[start - HISTORY + 1:start + 1]
            past_actions = actions[start - HISTORY + 1:start]
            targets = [features(states[start + k - HISTORY + 1:start + k + 1],
                                actions[start + k - HISTORY + 1:start + k]) for k in range(1, HORIZON + 1)]
            windows.append({"domain_id": domain["domain_id"], "states": history, "history": past_actions,
                            "x": features(history, past_actions), "u": actions[start:start + HORIZON],
                            "target_features": targets, "truth": states[start + 1:start + HORIZON + 1]})
    return windows, domains


def request_for(window):
    return {"contract_version": "state_prediction_v0.1", "scene_id": "synthetic_point_mass_v0.1",
            "map_version": "toy-v1", "node_id": "SYNTHETIC-UAV-01", "coordinate_frame": "scene_ned",
            "dt_s": DT, "snapshot_age_s": 0.0,
            "state_history": [{"t_s": round(i * DT, 8), "position_ned_m": s[:3], "velocity_ned_mps": s[3:]}
                              for i, s in enumerate(window["states"])],
            "action_history": window["history"], "candidate_acceleration_ned_mps2": window["u"]}
