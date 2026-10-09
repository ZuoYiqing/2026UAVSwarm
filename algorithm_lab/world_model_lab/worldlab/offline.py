"""Local artifact integrity and machine inventory. No downloads/installers."""
import ctypes
import hashlib
import json
import os
import platform
import shutil
import sys
from pathlib import Path


def free_memory_bytes():
    if os.name == "nt":
        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in ("total", "available", "page_total", "page_available",
                                                     "virtual_total", "virtual_available", "extended")]
        status = Memory()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise RuntimeError("MEMORY_STATUS_UNAVAILABLE")
        return status.available
    info = Path("/proc/meminfo")
    if info.exists():
        for line in info.read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    raise RuntimeError("MEMORY_STATUS_UNAVAILABLE")


def guard(minimum_gib=1.5):
    free = free_memory_bytes()
    if free < minimum_gib * 1024 ** 3:
        raise RuntimeError(f"MEMORY_GUARD: {free / 1024 ** 3:.2f} GiB available; require {minimum_gib}")
    return free


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_bundle(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != "worldlab_bundle_v0.1" or not isinstance(manifest.get("files"), dict):
        raise ValueError("BUNDLE_FORMAT_INVALID")
    if not 1 <= len(manifest["files"]) <= 100:
        raise ValueError("BUNDLE_FILE_COUNT_INVALID")
    for relative, expected in manifest["files"].items():
        source = root / relative
        path = source.resolve()
        if not path.is_relative_to(root) or Path(relative).is_absolute():
            raise ValueError("BUNDLE_PATH_ESCAPE")
        if source.is_symlink() or not path.is_file() or file_hash(path) != expected:
            raise ValueError(f"BUNDLE_INTEGRITY_FAILED:{relative}")
    return manifest


def compare_golden(result, expected, tolerance=1e-5):
    """Allow cross-architecture math rounding, never semantic differences."""
    from .contracts import number
    if set(result) != set(expected):
        raise ValueError("GOLDEN_FIELDS_MISMATCH")
    for key in result:
        if key != "predictions" and result[key] != expected[key]:
            raise ValueError(f"GOLDEN_METADATA_MISMATCH:{key}")
    if len(result["predictions"]) != len(expected["predictions"]):
        raise ValueError("GOLDEN_HORIZON_MISMATCH")
    maximum = 0.0
    for actual, golden in zip(result["predictions"], expected["predictions"]):
        if set(actual) != set(golden) or actual["offset_s"] != golden["offset_s"]:
            raise ValueError("GOLDEN_TIME_MISMATCH")
        for field in ("position_ned_m", "velocity_ned_mps"):
            if len(actual[field]) != 3 or len(golden[field]) != 3:
                raise ValueError("GOLDEN_VECTOR_MISMATCH")
            for value, reference in zip(actual[field], golden[field]):
                number(value, field, 1e5)
                number(reference, field, 1e5)
                maximum = max(maximum, abs(value - reference))
    if maximum > tolerance:
        raise ValueError("GOLDEN_NUMERIC_MISMATCH")
    return maximum


def inventory():
    release = Path("/etc/nv_tegra_release")
    return {"python": platform.python_version(), "machine": platform.machine(), "system": platform.system(),
            "available_memory_bytes": free_memory_bytes(),
            "jetson_release": release.read_text() if release.exists() else None,
            "target_hardware": "Jetson AGX Orin 32GB (user supplied)",
            "board_validated": False, "execution_authorized": False,
            "notes": ["Inventory only; collect JetPack, TensorRT, power mode and storage on actual board.",
                      "Windows binaries/wheels and TensorRT engines cannot be reused as ARM64 deployment."]}


def bundle(run, output):
    from .inference import load_model, predict
    root, output = Path(run).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("OUTPUT_EXISTS_NO_OVERWRITE")
    model = load_model(root / "model.json")
    request = json.loads((root / "example_request.json").read_text(encoding="utf-8"))
    golden = predict(model, request)
    output.mkdir(parents=True)
    package = output / "worldlab"
    package.mkdir()
    for name in ("__init__.py", "contracts.py", "inference.py", "offline.py", "cli.py"):
        shutil.copyfile(Path(__file__).parent / name, package / name)
    for name in ("model.json", "example_request.json", "report.json"):
        shutil.copyfile(root / name, output / name)
    (output / "golden_response.json").write_text(json.dumps(golden, indent=2, allow_nan=False), encoding="utf-8")
    # Selftest is first-party source; it installs a Python network audit hook.
    shutil.copyfile(Path(__file__).parents[1] / "scripts" / "offline_selftest.py", output / "offline_selftest.py")
    shutil.copyfile(Path(__file__).parents[1] / "README.md", output / "README.md")
    manifest = {"format": "worldlab_bundle_v0.1", "python_minimum": "3.10", "inference_dependencies": [],
                "network_isolation": "Python audit hook test available; not OS firewall isolation",
                "target_board_verified": False, "execution_authorized": False,
                "files": {p.relative_to(output).as_posix(): file_hash(p)
                          for p in sorted(output.rglob("*")) if p.is_file()}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    verify_bundle(output)
    return {"bundle": str(output), "files": len(manifest["files"]), "bytes": sum(p.stat().st_size for p in output.rglob("*") if p.is_file())}
