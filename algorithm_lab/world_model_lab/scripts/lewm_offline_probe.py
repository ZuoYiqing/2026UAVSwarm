"""Local visual smoke and timing; training and hardware execution are absent."""
import argparse
import ctypes
import json
import os
import platform
import socket
import statistics
import sys
import time
from importlib.metadata import version
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worldlab.contracts import digest
from worldlab.lewm_contract import ASSETS, MODEL_REVISION, SOURCE_REVISION, checked_assets, checked_request
from worldlab.lewm_fixture import create_fixture
from worldlab.offline import file_hash, free_memory_bytes, guard


def deny_network(event, arguments):
    if event.startswith("socket."):
        raise RuntimeError("NETWORK_FORBIDDEN_BY_LEWM_PROBE")


def memory():
    if os.name == "nt":
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
                (name, ctypes.c_size_t) for name in ("peak_working", "working", "peak_paged", "paged",
                                                    "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        current = ctypes.windll.kernel32.GetCurrentProcess
        current.restype = ctypes.c_void_p
        query = ctypes.windll.psapi.GetProcessMemoryInfo
        query.argtypes = (ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong)
        if not query(current(), ctypes.byref(counters), counters.cb):
            return {"rss_bytes": None, "peak_rss_bytes": None}
        return {"rss_bytes": counters.working, "peak_rss_bytes": counters.peak_working}
    import resource
    # Linux ru_maxrss is KiB; current RSS is read separately.
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    current = None
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            current = int(line.split()[1]) * 1024
    return {"rss_bytes": current, "peak_rss_bytes": peak}


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--request")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError("OUTPUT_EXISTS_NO_OVERWRITE")
    if not 1 <= args.runs <= 100:
        raise ValueError("TIMING_RUN_BUDGET_INVALID")
    started = time.perf_counter()
    root = checked_assets(args.assets)
    output.mkdir(parents=True)
    input_path = Path(args.request).resolve() if args.request else create_fixture(output / "inputs")
    request, images = checked_request(input_path)
    report = {"status": "prepared", "scope": "official_pusht_checkpoint_synthetic_rgb_load_smoke",
              "source_revision": SOURCE_REVISION, "model_revision": MODEL_REVISION,
              "assets": ASSETS, "request_sha256": digest(request),
              "input_images": [{"name": p.name, "sha256": file_hash(p)} for p in images],
              "available_memory_before_bytes": free_memory_bytes(), "model_loaded": False,
              "inference_completed": False, "board_validated": False, "execution_authorized": False,
              "limitations": ["Synthetic RGB and zero normalized PushT actions, no task-quality evaluation.",
                              "No scene localization, decoded future image, or drone action mapping.",
                              "Python network API blocking is not OS firewall isolation.",
                              "Board power and whole-system memory require actual target measurement."]}
    write(output / "report.json", report)
    if args.prepare_only:
        print(json.dumps(report, indent=2))
        return 0
    try:
        guard(3.0)
        # Set process-only offline/cache controls BEFORE importing any ML package.
        cache = output / "empty-cache"
        cache.mkdir()
        for name in ("HF_HOME", "TORCH_HOME", "XDG_CACHE_HOME"):
            os.environ[name] = str(cache)
        for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
            os.environ[name] = "1"
        for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS"):
            os.environ[name] = "1"
        os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
        sys.addaudithook(deny_network)
        try:
            socket.socket()
        except RuntimeError as error:
            if str(error) != "NETWORK_FORBIDDEN_BY_LEWM_PROBE":
                raise
        else:
            raise ValueError("NETWORK_BLOCK_TEST_FAILED")
        report["network_api_block_test"] = "pass"
        import torch
        from worldlab.lewm import image_tensor, load
        torch.set_num_threads(1)
        torch.manual_seed(11)
        torch.use_deterministic_algorithms(True)
        if args.device == "cuda" and not torch.cuda.is_available():
            raise ValueError("CUDA_NOT_AVAILABLE")
        if args.device == "cuda":
            torch.cuda.reset_peak_memory_stats()
        guard(1.5)
        model, cfg, keys = load(root, args.device)
        report.update(model_loaded=True, strict_state_dict_keys=keys,
                      parameters=sum(p.numel() for p in model.parameters()),
                      memory_after_load=memory())
        pixels = image_tensor(images, args.device)
        actions = torch.tensor([request["normalized_action_blocks"]], dtype=torch.float32, device=args.device)
        def synchronize():
            if args.device == "cuda":
                torch.cuda.synchronize()
        def forward():
            info = model.encode({"pixels": pixels, "action": actions})
            return info["emb"], model.predict(info["emb"], info["act_emb"])
        with torch.inference_mode():
            synchronize()
            first_start = time.perf_counter()
            embeddings, predicted = forward()
            synchronize()
            report["first_forward_ms"] = (time.perf_counter() - first_start) * 1000
            for _ in range(3):
                forward()
            synchronize()
            timings = []
            for _ in range(args.runs):
                guard(1.5)
                tick = time.perf_counter()
                forward()
                synchronize()
                timings.append((time.perf_counter() - tick) * 1000)
            repeated_emb, repeated_pred = forward()
            altered_actions = actions + 0.25
            info = model.encode({"pixels": pixels, "action": altered_actions})
            altered_pred = model.predict(info["emb"], info["act_emb"])
        if list(embeddings.shape) != [1, 3, 192] or list(predicted.shape) != [1, 3, 192]:
            raise ValueError("EMBEDDING_SHAPE_MISMATCH")
        if not all(bool(torch.isfinite(x).all()) for x in (embeddings, predicted, altered_pred)):
            raise ValueError("MODEL_OUTPUT_NONFINITE")
        raw = {"observed_embeddings": embeddings.cpu().tolist(), "predicted_embeddings": predicted.cpu().tolist(),
               "action_perturbed_predictions": altered_pred.cpu().tolist()}
        write(output / "embeddings.json", raw)
        repeat_error = float((repeated_pred - predicted).abs().max())
        if repeat_error > 1e-5:
            raise ValueError("REPEATED_FORWARD_MISMATCH")
        report.update(status="load_and_inference_pass", inference_completed=True, device=args.device,
                      embedding_shape=list(embeddings.shape), prediction_shape=list(predicted.shape),
                      output_sha256=digest(raw), repeat_max_abs_error=repeat_error,
                      action_perturbation_max_abs_difference=float((altered_pred - predicted).abs().max()),
                      latency_ms={"median": statistics.median(timings),
                                  "p95_nearest_rank": sorted(timings)[max(0, int(0.95 * len(timings) + 0.999) - 1)],
                                  "raw": timings, "warmups": 3,
                                  "scope": "three-frame encoder plus one three-context latent predictor forward; no image IO"},
                      process_memory=memory(), available_memory_after_bytes=free_memory_bytes(),
                      environment={"python": platform.python_version(), "system": platform.system(),
                                   "machine": platform.machine(),
                                   "versions": {n: version(n) for n in ("torch", "numpy", "transformers", "Pillow", "einops")}},
                      total_seconds=time.perf_counter() - started)
        if args.device == "cuda":
            report["gpu_name"] = torch.cuda.get_device_name()
            report["gpu_peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
        write(output / "report.json", report)
        print(json.dumps(report, indent=2))
        return 0
    except Exception as error:
        report.update(status="blocked", reason=str(error), process_memory=memory())
        write(output / "report.json", report)
        print(json.dumps(report, indent=2))
        return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error), "execution_authorized": False}))
        raise SystemExit(2)
