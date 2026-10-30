"""Build a new, immutable Ubuntu CPU bundle without altering the 2026-10-24 one.

Only standard-library tooling is used. Production Python bytes come from the
fixed Git commit, not from possibly dirty working-tree files. No model is run.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1]
REPOSITORY = MODULE.parents[1]
OLD = MODULE / "artifacts" / "linux-b10964-cpu"
DESTINATION = MODULE / "artifacts" / "linux-b10964-cpu-compact-v1"
SOURCE_COMMIT = "735af7485a5d953bdea2e48c8d634e256d325af5"
OLD_ARCHIVE_SHA256 = "4c5c25e37146c39599746effc3e29334386a43970bdad83c24d73f96eb7168ef"
ENGINE_ARCHIVE_SHA256 = "9abf88aea48a55d0f80edb1ee20220b186848cca0b4e919d71518cfd7ca67443"
MODEL_SHA256 = "bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517"
ARCHIVE_NAME = "uav02-candidate-compact-v1-b10964-cpu-ubuntu22.04.tar.gz"
SOURCE_FILES = (
    "__init__.py", "__main__.py", "candidate.py", "contracts.py",
    "experiment.py", "local_model.py", "model_view.py", "server.py",
    "fixtures/model_unauthorized.json", "fixtures/model_valid.json",
    "fixtures/uav02_hold_request.json", "tests/test_candidate.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_hash(path: Path, expected: str) -> None:
    if not path.is_file() or sha256(path) != expected:
        raise RuntimeError(f"asset hash mismatch: {path}")


def git_blob(relative: str) -> bytes:
    reference = f"{SOURCE_COMMIT}:algorithm_lab/platform_candidate_lab/{relative}"
    command = ["git"]
    # A Windows-created worktree has a D:/ .git pointer that WSL Git cannot
    # resolve. Pass the main object database explicitly inside WSL instead.
    git_dir = os.environ.get("UAV_BUNDLE_GIT_DIR")
    if git_dir:
        command.append(f"--git-dir={git_dir}")
    return subprocess.check_output([*command, "show", reference], cwd=REPOSITORY)


def bundle_readme() -> str:
    return """# UAV-02 compact-view Ubuntu 22.04 CPU bundle

This is a **new** offline research bundle. It uses algorithm production source
735af7485a5d953bdea2e48c8d634e256d325af5, llama.cpp b10964 and the pinned
Qwen3.5-0.8B Q4 GGUF. It does not contain Runtime, Policy Gate, PX4, Gazebo,
flight authorization or a Jetson/ARM64 executable. The original 2026-10-24
archive is unchanged and contains older algorithm source 17017cd.

Before use, verify the external archive SHA256SUMS, then extract and verify the
internal bundle/SHA256SUMS. On target Ubuntu 22.04 x86-64, check executable
format, `ldd` dependencies and all package tests. Confirm available host RAM
is at least 3 GiB and that ports 18080/8872 have no other listener. The two
services must run in the same Linux instance, under one designated owner.

From the extracted `bundle` directory, model service:

```bash
export LD_LIBRARY_PATH="$PWD/runtime/llama-b10964"
"$PWD/runtime/llama-b10964/llama-server" \\
  -m "$PWD/models/Qwen3.5-0.8B-Q4_K_M.gguf" \\
  --alias qwen3.5-0.8b-q4-lab --host 127.0.0.1 --port 18080 \\
  --offline --no-webui --no-agent --no-ui-mcp-proxy \\
  --ctx-size 512 --parallel 1 --threads 4 --threads-batch 4 \\
  --gpu-layers 0 --reasoning off --no-context-shift
```

In a second terminal in the **same** Linux instance, candidate service:

```bash
cd /absolute/path/to/bundle/algorithm_lab
PYTHONDONTWRITEBYTECODE=1 python3 -B -m platform_candidate_lab serve \\
  --model-url http://127.0.0.1:18080/v1/chat/completions \\
  --model-id qwen3.5-0.8b-q4-lab --port 8872
```

The candidate service command for SITL/production must **omit --allow-fake**.
That flag is only for isolated synthetic experiments. The model returns a
candidate, never execution authorization. Runtime retains its own authorization,
Policy Gate and two-second deadline. Do not infer flight readiness from the
12/12 fake-task Runtime replay: real PX4 telemetry has a different input size,
and its ctx512 token budget and latency still require dedicated validation.

To run package tests without loading the model:

```bash
cd /absolute/path/to/bundle/algorithm_lab
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s platform_candidate_lab/tests -v
```
"""


def build() -> tuple[Path, str]:
    if DESTINATION.exists():
        raise FileExistsError(f"refusing to overwrite existing bundle: {DESTINATION}")
    if sys.platform != "linux":
        raise RuntimeError("build this Linux bundle from Ubuntu/WSL to preserve shared-library links")
    old_archive = OLD / "uav02-candidate-b10964-cpu-ubuntu22.04.tar.gz"
    engine_archive = OLD / "downloads" / "llama-b10964-bin-ubuntu-x64.tar.gz"
    old_bundle = OLD / "bundle"
    old_manifest = json.loads((old_bundle / "manifest.json").read_text(encoding="utf-8"))
    if old_manifest["source_control"]["algorithm_commit"] != "17017cd711c96fbabb424540ae8467565e3c9f70":
        raise RuntimeError("unexpected base bundle source")
    require_hash(old_archive, OLD_ARCHIVE_SHA256)
    require_hash(engine_archive, ENGINE_ARCHIVE_SHA256)
    require_hash(old_bundle / "models" / "Qwen3.5-0.8B-Q4_K_M.gguf", MODEL_SHA256)
    bundle = DESTINATION / "bundle"
    bundle.mkdir(parents=True)
    shutil.copytree(old_bundle / "runtime", bundle / "runtime")
    shutil.copytree(old_bundle / "licenses", bundle / "licenses")
    (bundle / "models").mkdir()
    shutil.copy2(old_bundle / "models" / "Qwen3.5-0.8B-Q4_K_M.gguf",
                 bundle / "models" / "Qwen3.5-0.8B-Q4_K_M.gguf")
    require_hash(bundle / "models" / "Qwen3.5-0.8B-Q4_K_M.gguf", MODEL_SHA256)

    source = bundle / "algorithm_lab" / "platform_candidate_lab"
    source_hashes: dict[str, str] = {}
    for relative in SOURCE_FILES:
        content = git_blob(relative)
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        source_hashes[relative] = hashlib.sha256(content).hexdigest()

    result = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "discover", "-s", "platform_candidate_lab/tests"],
        cwd=bundle / "algorithm_lab", capture_output=True, text=True, timeout=60,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, check=False,
    )
    if result.returncode or "Ran 16 tests" not in result.stderr or "OK" not in result.stderr:
        raise RuntimeError(f"bundled algorithm tests failed:\n{result.stdout}\n{result.stderr}")

    manifest = {
        "schema_version": "2.0", "recorded_date": "2026-10-30",
        "purpose": "UAV-02 compact-view local candidate; offline research and controlled SITL validation",
        "flight_authorized": False, "target": old_manifest["target"],
        "source_control": {"algorithm_production_commit": SOURCE_COMMIT,
                           "source_file_sha256": source_hashes,
                           "runtime_fake_replay_commit": "876bb92f04b6bc6c7b74368323ce7b8abd72f861"},
        "engine": old_manifest["engine"], "model": old_manifest["model"],
        "dependencies": old_manifest["dependencies"],
        "provenance": {"original_bundle_sha256": OLD_ARCHIVE_SHA256,
                       "original_bundle_unchanged": True,
                       "engine_archive_sha256": ENGINE_ARCHIVE_SHA256},
        "verification": {"algorithm_tests_in_new_bundle": "16 passed, 0 failed",
                         "new_bundle_model_inference": "not_run",
                         "external_runtime_fake_replay": "12/12 candidates at ctx512, algorithm source 735af74",
                         "real_px4_or_ugv_executed": False},
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                          encoding="utf-8", newline="\n")
    (bundle / "README.md").write_text(bundle_readme(), encoding="utf-8", newline="\n")
    files = sorted(path for path in bundle.rglob("*") if path.is_file())
    checksums = "".join(f"{sha256(path)}  {path.relative_to(bundle).as_posix()}\n" for path in files)
    (bundle / "SHA256SUMS").write_text(checksums, encoding="ascii", newline="\n")

    archive = DESTINATION / ARCHIVE_NAME
    with archive.open("xb") as stream:
        with gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0, compresslevel=1) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as tar:
                for path in sorted(bundle.rglob("*")):
                    info = tar.gettarinfo(str(path), arcname=(Path("bundle") / path.relative_to(bundle)).as_posix())
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ""
                    if path.is_file():
                        with path.open("rb") as source_stream:
                            tar.addfile(info, source_stream)
                    else:
                        tar.addfile(info)
    archive_hash = sha256(archive)
    (DESTINATION / "SHA256SUMS").write_text(f"{archive_hash}  {ARCHIVE_NAME}\n",
                                              encoding="ascii", newline="\n")
    return archive, archive_hash


if __name__ == "__main__":
    result_path, result_hash = build()
    print(json.dumps({"archive": str(result_path), "sha256": result_hash,
                      "bytes": result_path.stat().st_size, "algorithm_source": SOURCE_COMMIT},
                     sort_keys=True))
