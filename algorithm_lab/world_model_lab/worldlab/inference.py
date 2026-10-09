"""Portable JSON-weight inference: Python arithmetic, no third-party imports."""
import json
import math
from pathlib import Path
from .contracts import DT, digest, features, integrate, number, validate

SHAPES = {"encoder": (69, 32, 16), "predictor": (19, 32, 16), "prober": (19, 24, 3)}


def load_model(path):
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError("MODEL_TOO_LARGE")
    model = json.loads(path.read_text(encoding="utf-8"))
    if model.get("format") != "tiny_state_jepa_v0.1" or model.get("dt_s") != DT:
        raise ValueError("MODEL_FORMAT_UNSUPPORTED")
    for name, sizes in SHAPES.items():
        layers = model.get(name)
        if not isinstance(layers, list) or len(layers) != 2:
            raise ValueError("MODEL_LAYERS_INVALID")
        for layer, ni, no in zip(layers, sizes[:-1], sizes[1:]):
            if not isinstance(layer, dict) or set(layer) != {"weight", "bias"}:
                raise ValueError("MODEL_LAYER_INVALID")
            if len(layer["weight"]) != no or len(layer["bias"]) != no:
                raise ValueError("MODEL_SHAPE_INVALID")
            for row in layer["weight"]:
                if len(row) != ni:
                    raise ValueError("MODEL_SHAPE_INVALID")
                for value in row:
                    number(value, "weight", 1e4)
            for value in layer["bias"]:
                number(value, "bias", 1e4)
    return model


def mlp(layers, x):
    for i, layer in enumerate(layers):
        x = [sum(w * v for w, v in zip(row, x)) + bias
             for row, bias in zip(layer["weight"], layer["bias"])]
        if i == 0:
            x = [math.tanh(v) for v in x]
    return x


def rollout(model, states, history, future):
    z, state = mlp(model["encoder"], features(states, history)), list(states[-1])
    trajectory = []
    for action in future:
        inputs = z + [a / 2 for a in action]
        correction = mlp(model["prober"], inputs)
        state = integrate(state, [a + c for a, c in zip(action, correction)])
        z = [v + DT * d for v, d in zip(z, mlp(model["predictor"], inputs))]
        if not all(math.isfinite(v) for v in state + z):
            raise ValueError("PREDICTION_NONFINITE")
        trajectory.append(state[:])
    return trajectory


def predict(model, request):
    states, history, future = validate(request)
    trajectory = rollout(model, states, history, future)
    return {
        "contract_version": "state_prediction_v0.1", "status": "research_prediction",
        "reason_code": "SYNTHETIC_MODEL_ONLY", "scene_id": request["scene_id"],
        "map_version": request["map_version"], "node_id": request["node_id"],
        "coordinate_frame": "scene_ned", "input_sha256": digest(request),
        "model_sha256": digest(model), "execution_authorized": False, "safety_verified": False,
        "warnings": ["Not a flight dynamics model or collision certificate.",
                     "Snapshot age is caller-provided, not live telemetry verification."],
        "predictions": [{"offset_s": round((i + 1) * DT, 8), "position_ned_m": x[:3],
                         "velocity_ned_mps": x[3:]} for i, x in enumerate(trajectory)],
    }
