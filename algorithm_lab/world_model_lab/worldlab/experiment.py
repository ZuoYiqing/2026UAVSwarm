"""Small CPU training experiment; PyTorch is never imported by inference."""
import copy
import json
import math
import platform
import statistics
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

from .contracts import DT, digest, features, integrate
from .inference import rollout
from .simulation import dataset, request_for


def network(ni, hidden, no):
    return nn.Sequential(nn.Linear(ni, hidden), nn.Tanh(), nn.Linear(hidden, no))


class TinyJEPA(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = network(69, 32, 16)
        self.predictor = network(19, 32, 16)
        self.prober = network(19, 24, 3)

    def latents(self, x, u):
        z, outputs = self.encoder(x), []
        for k in range(u.shape[1]):
            outputs.append(z)
            z = z + DT * self.predictor(torch.cat((z, u[:, k] / 2), dim=-1))
        return torch.stack(outputs, dim=1), z

    def predict_states(self, x, initial, u):
        zs, _ = self.latents(x, u)
        state, outputs = initial, []
        for k in range(u.shape[1]):
            acc = u[:, k] + self.prober(torch.cat((zs[:, k], u[:, k] / 2), dim=-1))
            velocity = state[:, 3:] + DT * acc
            position = state[:, :3] + DT * (state[:, 3:] + velocity) / 2
            state = torch.cat((position, velocity), dim=-1)
            outputs.append(state)
        return torch.stack(outputs, dim=1)


def sigreg(z, directions):
    # Independent characteristic-function implementation, not upstream code.
    t = torch.linspace(0, 3, 17, device=z.device)
    projected = z @ directions
    angles = projected[:, :, None] * t
    real, imag = angles.cos().mean(0), angles.sin().mean(0)
    gaussian = torch.exp(-t.square() / 2)
    error = ((real - gaussian).square() + imag.square()) * gaussian
    return z.shape[0] * torch.trapz(error, t, dim=-1).mean()


def tensors(windows):
    values = tuple(torch.tensor(np.array([w[key] for w in windows]), dtype=torch.float32)
                   for key in ("x", "u", "target_features", "truth"))
    initial = torch.tensor([w["states"][-1] for w in windows], dtype=torch.float32)
    return values + (initial,)


def fit(net, data, validation, epochs, stage, guard):
    x, u, target, truth, initial = data
    vx, vu, vt, vtruth, vinitial = validation
    modules = [net.encoder, net.predictor] if stage == "latent" else [net.prober]
    parameters = [p for module in modules for p in module.parameters()]
    optimizer = torch.optim.Adam(parameters, lr=0.003)
    directions = torch.randn(16, 32)
    directions = directions / directions.norm(dim=0, keepdim=True)
    best, best_loss, best_epoch, log = None, float("inf"), 0, []
    for epoch in range(epochs):
        guard()
        order = torch.randperm(len(x))
        for ids in order.split(64):
            optimizer.zero_grad()
            if stage == "latent":
                zs, final = net.latents(x[ids], u[ids])
                predicted = torch.cat((zs[:, 1:], final[:, None]), dim=1)
                target_z = net.encoder(target[ids])
                loss = (predicted - target_z).square().mean() + 0.02 * sigreg(target_z.reshape(-1, 16), directions)
            else:
                predicted = net.predict_states(x[ids], initial[ids], u[ids])
                loss = (predicted - truth[ids]).square().mean()
            if not torch.isfinite(loss):
                raise ValueError("TRAINING_NONFINITE")
            loss.backward()
            nn.utils.clip_grad_norm_(parameters, 1.0)
            optimizer.step()
        with torch.no_grad():
            if stage == "latent":
                zs, final = net.latents(vx, vu)
                pred = torch.cat((zs[:, 1:], final[:, None]), dim=1)
                val = (pred - net.encoder(vt)).square().mean() + 0.02 * sigreg(net.encoder(vt).reshape(-1, 16), directions)
            else:
                val = (net.predict_states(vx, vinitial, vu) - vtruth).square().mean()
            val = float(val)
        if val < best_loss:
            best, best_loss, best_epoch = copy.deepcopy(net.state_dict()), val, epoch + 1
        if (epoch + 1) % 10 == 0 or epoch == 0:
            log.append({"epoch": epoch + 1, "validation_loss": val})
            print(json.dumps({"stage": stage, **log[-1]}), flush=True)
    net.load_state_dict(best)
    return {"selected_epoch": best_epoch, "validation_loss": best_loss, "log": log}


def export_json(net, seed):
    result = {"format": "tiny_state_jepa_v0.1", "dt_s": DT, "seed": seed,
              "scope": "synthetic_point_mass_only", "training_device": "cpu"}
    for name in ("encoder", "predictor", "prober"):
        result[name] = [{"weight": layer.weight.detach().tolist(), "bias": layer.bias.detach().tolist()}
                        for layer in getattr(net, name) if isinstance(layer, nn.Linear)]
    return result


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def metrics(prediction, truth):
    error = np.array(prediction) - np.array(truth)
    return {str(k): {"position_rmse_m": float(np.sqrt(np.mean(np.sum(error[:, k - 1, :3] ** 2, axis=-1)))),
                     "velocity_rmse_mps": float(np.sqrt(np.mean(np.sum(error[:, k - 1, 3:] ** 2, axis=-1))))}
            for k in (1, 5, 10)}


def ridge_fit(rows, labels, ridge=0.01):
    """Small SPD solve without BLAS/OpenMP; all inputs must be train-only."""
    n = len(rows[0])
    gram = [[sum(row[i] * row[j] for row in rows) + (ridge if i == j else 0.0)
             for j in range(n)] for i in range(n)]
    rhs = [[sum(row[i] * label[j] for row, label in zip(rows, labels))
            for j in range(3)] for i in range(n)]
    lower = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            value = gram[i][j] - sum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                if value <= 0 or not math.isfinite(value):
                    raise ValueError("RIDGE_FACTOR_INVALID")
                lower[i][j] = math.sqrt(value)
            else:
                lower[i][j] = value / lower[j][j]
    result = [[0.0] * 3 for _ in range(n)]
    for axis in range(3):
        intermediate = [0.0] * n
        for i in range(n):
            intermediate[i] = (rhs[i][axis] - sum(lower[i][j] * intermediate[j]
                                                for j in range(i))) / lower[i][i]
        for i in range(n - 1, -1, -1):
            result[i][axis] = (intermediate[i] - sum(lower[j][i] * result[j][axis]
                                                   for j in range(i + 1, n))) / lower[i][i]
    return result


def run(output, seed=11, epochs=40, probe_epochs=60, guard=lambda: None):
    started = time.perf_counter()
    output = Path(output)
    if output.exists():
        raise ValueError("OUTPUT_EXISTS_NO_OVERWRITE")
    guard()
    output.mkdir(parents=True)
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    splits = {"train": dataset(101, 32), "validation": dataset(202, 8), "test": dataset(303, 16)}
    train, validation = tensors(splits["train"][0]), tensors(splits["validation"][0])
    net = TinyJEPA()
    latent = fit(net, train, validation, epochs, "latent", guard)
    for module in (net.encoder, net.predictor):
        for p in module.parameters():
            p.requires_grad_(False)
    probe = fit(net, train, validation, probe_epochs, "prober", guard)
    model = export_json(net, seed)
    write_json(output / "model.json", model)
    # A strong learned linear-residual baseline, fitted on train only.
    rows = [w["x"] + [a / 2 for a in w["u"][0]] + [1] for w in splits["train"][0]]
    labels = [[(w["truth"][0][i + 3] - w["states"][-1][i + 3]) / DT - w["u"][0][i]
               for i in range(3)] for w in splits["train"][0]]
    linear = ridge_fit(rows, labels)
    print(json.dumps({"stage": "evaluation", "baseline_fit": "complete"}), flush=True)
    predictions = {name: [] for name in ("constant_velocity", "nominal_acceleration", "linear_residual", "tiny_jepa")}
    records, parity = [], 0.0
    for w in splits["test"][0]:
        guard()
        jepa = rollout(model, w["states"], w["history"], w["u"])
        with torch.no_grad():
            native = net.predict_states(torch.tensor([w["x"]]), torch.tensor([w["states"][-1]]), torch.tensor([w["u"]]))[0].tolist()
        parity = max(parity, float(np.max(np.abs(np.array(native) - np.array(jepa)))))
        for name in ("constant_velocity", "nominal_acceleration", "linear_residual"):
            state, history, past, trajectory = w["states"][-1][:], copy.deepcopy(w["states"]), copy.deepcopy(w["history"]), []
            for action in w["u"]:
                acc = [0.0] * 3 if name == "constant_velocity" else action[:]
                if name == "linear_residual":
                    inputs = features(history, past) + [a / 2 for a in action] + [1]
                    residual = [sum(value * row[i] for value, row in zip(inputs, linear)) for i in range(3)]
                    acc = [a + r for a, r in zip(action, residual)]
                state = integrate(state, acc)
                trajectory.append(state[:])
                history, past = history[1:] + [state[:]], past[1:] + [action[:]]
            predictions[name].append(trajectory)
        predictions["tiny_jepa"].append(jepa)
        records.append({"request": request_for(w), "truth": w["truth"], "prediction": jepa})
        if len(records) % 28 == 0:
            print(json.dumps({"stage": "evaluation", "test_windows": len(records)}), flush=True)
    truth = [w["truth"] for w in splits["test"][0]]
    errors = {name: metrics(values, truth) for name, values in predictions.items()}
    timings = []
    w = splits["test"][0][0]
    for _ in range(110):
        t = time.perf_counter()
        rollout(model, w["states"], w["history"], w["u"])
        timings.append((time.perf_counter() - t) * 1000)
    write_json(output / "example_request.json", request_for(w))
    write_json(output / "test_predictions.json", records)
    report = {"status": "experimental_only", "seed": seed, "epochs": epochs, "probe_epochs": probe_epochs,
              "data": {name: {"episodes": len(d), "windows": len(ws), "sha256": digest(ws), "domains": d}
                       for name, (ws, d) in splits.items()}, "latent_training": latent, "probe_training": probe,
              "model_sha256": digest(model), "parameter_count": sum(p.numel() for p in net.parameters()),
              "metrics": errors, "python_torch_max_abs_difference": parity,
              "portable_inference_ms": {"median": statistics.median(timings[10:]), "p95": float(np.percentile(timings[10:], 95))},
              "latent_std_mean": float(net.encoder(validation[0]).std(dim=0).mean()),
              "environment": {"python": platform.python_version(), "machine": platform.machine(),
                              "torch": torch.__version__, "numpy": np.__version__, "device": "cpu",
                              "torch_threads": torch.get_num_threads()},
              "total_seconds": time.perf_counter() - started, "execution_authorized": False,
              "limitations": ["One seed; synthetic smooth inputs only; no attitude, obstacles or real data.",
                              "Not SkyJEPA reproduction; no flight or board validation."]}
    write_json(output / "report.json", report)
    print(json.dumps({"output": str(output), "metrics": errors, "seconds": report["total_seconds"]}), flush=True)
    return report
