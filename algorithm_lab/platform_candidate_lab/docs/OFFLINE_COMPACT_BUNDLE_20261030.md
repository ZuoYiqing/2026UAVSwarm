# Compact-view Ubuntu CPU offline bundle — 2026-10-30

## Identity and scope

This is a **new** archive. It does not edit or replace the 2026-10-24 CPU bundle
whose algorithm source is `17017cd`. The new package carries production Python
bytes from algorithm commit `735af7485a5d953bdea2e48c8d634e256d325af5`,
including `model_view.py`; it reuses the previously pinned llama.cpp b10964
Linux x86-64 CPU engine and Qwen3.5-0.8B Q4 GGUF. No new model was downloaded.

Archive on D: (ignored by Git):

```text
D:\2026UAVSwarm-worktrees\algorithm-uav02-local-candidate\algorithm_lab\platform_candidate_lab\artifacts\linux-b10964-cpu-compact-v1\uav02-candidate-compact-v1-b10964-cpu-ubuntu22.04.tar.gz
```

| Artifact | Exact result |
| --- | --- |
| Archive size | 549,502,795 bytes |
| Archive SHA-256 | `bf77d4f18411608526fa4da69532d05c020d26e2a2ff6f2e15cadf1add451e4a` |
| GGUF SHA-256 | `bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517` |
| Old immutable bundle SHA-256 | `4c5c25e37146c39599746effc3e29334386a43970bdad83c24d73f96eb7168ef` |
| Engine release archive SHA-256 | `9abf88aea48a55d0f80edb1ee20220b186848cca0b4e919d71518cfd7ca67443` |

The new bundle has its own `manifest.json`, `README.md` and internal
`SHA256SUMS`; the parent directory has a sidecar archive `SHA256SUMS`.
Manifest `schema_version=2.0` identifies the fixed algorithm production
commit, per-source-file hashes, reused model/engine provenance, and explicitly
states `new_bundle_model_inference=not_run` and `real_px4_or_ugv_executed=false`.
Neither hashes nor prior fake replay are execution authorization.

## How it was built and checked

The standard-library builder is
`algorithm_lab/platform_candidate_lab/scripts/build_compact_cpu_bundle.py`.
It refuses to overwrite an existing output, refuses a Windows build because
the Linux shared libraries use symbolic links, verifies the old archive,
official engine archive and GGUF hashes, obtains packaged Python files from
the fixed Git commit, runs 16 packaged tests, then writes file hashes and a
new tar.gz. The command in this Windows-created worktree was run in Ubuntu WSL
with the main Git object database supplied explicitly:

```bash
UAV_BUNDLE_GIT_DIR=/mnt/d/2026UAVSwarm/.git python3 -B \
  /mnt/d/2026UAVSwarm-worktrees/algorithm-uav02-local-candidate/algorithm_lab/platform_candidate_lab/scripts/build_compact_cpu_bundle.py
```

The first Windows attempt stopped while copying the Linux symbolic links. Its
newly created partial output was resolved under this module's `artifacts/`
directory and removed; it never produced an archive or touched the old bundle.
The Ubuntu build then completed. Independent checks after creation:

- Windows `Get-FileHash` matched the archive SHA-256 above.
- `tar -tzf` decoded the entire archive and listed 86 entries.
- `sha256sum -c bundle/SHA256SUMS --quiet` passed for every staged bundle file. The archive was separately decoded in full, but was not installed on a second machine.
- Ubuntu `ldd` on the new `llama-server` found no missing dependency; `--version`
  returned `0.4.1-dev build 10964 commit b29c606e2`.
- From the **new bundle directory**, 16/16 algorithm tests passed in Ubuntu.
- In the source worktree, 19/19 tests passed on Windows and on Ubuntu; the
  three extra tests exercise the builder and are intentionally not claimed as
  part of the fixed `735af74` production-source package.

The new bundle's model was **not loaded** in this round. Runtime's earlier
12/12 complete fake-task candidate result used the same algorithm production
source, model weight and engine, but loaded the source separately with
`--candidate-source`; that result must not be relabeled as a test of this
new archive. Before a controlled SITL deployment, verify the transferred
archive and internal hashes on the target, check host RAM and port ownership,
then test the actual PX4 observation size and two-second latency. The previous
fake observation has fewer fields than a full PX4 battery/status snapshot.
Do not turn `--allow-fake` on for SITL or production. No flight command was
sent and no model service was started during this packaging work.

Ubuntu x86-64 binaries are **not** suitable for Jetson/ARM64 or a physical UGV.
Those targets require a separately built and measured package. Model weights,
engine binaries and this new archive remain Git-ignored and need an explicit
offline transfer; pulling the code branch will not download them.
