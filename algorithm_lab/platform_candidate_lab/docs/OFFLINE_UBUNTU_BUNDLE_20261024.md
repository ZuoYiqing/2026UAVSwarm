# Ubuntu 22.04 offline candidate bundle, 2026-10-24

Status: **CPU backend prepared; Linux model inference and the Runtime two-second
deadline are not verified. No flight was attempted.**

The transfer archive is local-only and Git-ignored:

- Path: `D:\2026UAVSwarm-worktrees\algorithm-uav02-local-candidate\algorithm_lab\platform_candidate_lab\artifacts\linux-b10964-cpu\uav02-candidate-b10964-cpu-ubuntu22.04.tar.gz`
- Size: 535,831,312 bytes
- SHA-256: `4c5c25e37146c39599746effc3e29334386a43970bdad83c24d73f96eb7168ef`
- Sidecar: the adjacent `SHA256SUMS`; `sha256sum -c SHA256SUMS` passed.

Contents: algorithm candidate source at `17017cd711c96fbabb424540ae8467565e3c9f70`,
official Linux CPU llama.cpp b10964/b29c606e2, the already-downloaded
Qwen3.5-0.8B Q4 GGUF, model and engine notices, `manifest.json`, and
`README.md`. Nothing under this artifact path is committed to Git.

## Provenance and dependencies

| Item | Source / licence | Verified SHA-256 |
| --- | --- | --- |
| Linux engine, 16,825,086-byte release archive | [Official b10964 Ubuntu x64 CPU asset](https://github.com/ggml-org/llama.cpp/releases/download/b10964/llama-b10964-bin-ubuntu-x64.tar.gz), [upstream attestation](https://github.com/ggml-org/llama.cpp/attestations/47376843); MIT in bundled LICENSE | `9abf88aea48a55d0f80edb1ee20220b186848cca0b4e919d71518cfd7ca67443` |
| Qwen3.5-0.8B Q4, 532,517,120 bytes | Existing D: community GGUF from `unsloth/Qwen3.5-0.8B-GGUF`, revision `cb02287e2172232d38d9eb470061351961ce1ba6`; Apache-2.0 upstream notice and quantizer card included | `bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517` |

In default WSL Ubuntu 22.04 x86-64, `file` reports an ELF 64-bit Linux
executable, `llama-server --version` reports build 10964 commit b29c606e2,
and `ldd` reports no missing libraries for the server or CPU backend.
Bundled shared libraries include llama/ggml; baseline OS links include
glibc/libm, libstdc++, libgcc_s, libgomp, libssl.so.3 and libcrypto.so.3.
This CPU build does not require CUDA. A different desktop must rerun `ldd`
and should not silently install/replace system libraries.

The official b10964 release has an Ubuntu CPU asset, but not an Ubuntu CUDA
asset. The available WSL NVIDIA driver reports CUDA 12.7 and has no CUDA
toolkit/user-space runtime in this distro. A newer Linux CUDA bundle was not
downloaded or treated as compatible by assumption.

## Reproduction

After extracting the archive into an Ubuntu 22.04 directory and setting
`BUNDLE` to that absolute directory, first run:

```bash
cd "$BUNDLE"
sha256sum models/Qwen3.5-0.8B-Q4_K_M.gguf
file runtime/llama-b10964/llama-server
LD_LIBRARY_PATH="$BUNDLE/runtime/llama-b10964" ldd runtime/llama-b10964/llama-server
LD_LIBRARY_PATH="$BUNDLE/runtime/llama-b10964" runtime/llama-b10964/llama-server --version
cd "$BUNDLE/algorithm_lab"
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s platform_candidate_lab/tests -v
```

Exact loopback-only server commands, synthetic-test flag rules, and notices
are in the bundle's own README. Do not start the model unless ports 18080/8872
are free and the existing 3 GiB available-host-RAM admission guard passes.
Production/SITL use must omit the test-only `--allow-fake` flag.

## Evidence and limitations

- Release archive SHA-256 matched upstream attestation; bundle archive and
  official download both passed the sidecar SHA-256 check. Copied GGUF hash
  matched the existing pinned model hash.
- From the copied bundle in WSL: 13/13 algorithm tests passed, including
  temporary localhost HTTP binding. This is not a model inference test.
- A short-lived candidate process on WSL `127.0.0.1:8872` was given a
  synthetic request while model port 18080 was intentionally absent. It
  returned `status=no_candidate`, `failure_reason_code=MODEL_UNAVAILABLE`,
  `execution_authorized=false`; the process was then stopped and both ports
  verified free.
- Packaged deterministic fixtures yielded `MODEL_TIMEOUT` and
  `MODEL_OUTPUT_INVALID`, both `no_candidate` and unauthorized for flight.
- Windows host free RAM at the model-admission check was about 1.59 GiB,
  below the project's 3 GiB guard. The model was **not loaded in WSL**.
  CPU latency, cold start, sustained two-second response rate and combined
  Runtime/SITL behavior remain unverified. A Windows GPU result is not
  substituted for these results.
