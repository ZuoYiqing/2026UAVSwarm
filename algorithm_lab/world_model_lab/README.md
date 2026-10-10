# World Model Lab v0.1

Independent, offline-first algorithm experiment. No Runtime, HTTP, flight adapter,
MAVLink, PX4, camera access, cloud inference or automatic model download.

## What this first experiment is

An original **tiny state-JEPA prototype**, not an official SkyJEPA reproduction or
a pretrained visual model. It predicts a toy 3D point mass with actuator lag,
drag and wind. It has no attitude, rigid-body dynamics, obstacles, perception,
coverage planning, fleet allocation or safety certificate. It is not fit for flight.
The toy controller input is a **candidate desired acceleration**, not a motor command
or a Runtime action. No conversion to executable actions is provided.

The encoder receives 8 position/velocity samples and 7 past acceleration inputs,
at 0.1 s spacing. Positions are relative to the last observation; all position,
velocity and acceleration vectors use shared `scene_ned`, down positive.
A latent predictor advances a 16-dimensional embedding. Stage 1 minimizes
multi-step embedding error plus an independently implemented characteristic-function
Gaussian regularizer inspired by SIGReg. Stage 2 freezes the encoder/predictor
and trains a residual-acceleration prober on top of kinematic integration.
The encoder is 69 -> 32 -> 16, predictor 19 -> 32 -> 16, prober 19 -> 24 -> 3.

Baselines: constant velocity, instantaneous nominal acceleration, learned linear
residual. The latter is fitted on train data only. Its regularization is fixed at
0.01 before testing. A neural result worse than a baseline stays in the report.
The data are smooth synthetic excitations; no claim about real aircraft follows.

## Run locally

Inference needs **Python >=3.10 only**, no pip install. Training needs existing
PyTorch and NumPy. This first run uses CPU/one thread to avoid CUDA initialization
under low host memory. No installation or root dependency change is performed.
Tested dependency versions are recorded by each run, not assumed portable.
No GPU training or TensorRT engine is claimed in this milestone.

From this module directory:

```text
python -m unittest discover -s tests -v
python -m worldlab.cli inventory
python -m worldlab.cli train --output artifacts/runs/seed11 --seed 11
python -m worldlab.cli infer --model artifacts/runs/seed11/model.json --input artifacts/runs/seed11/example_request.json
python -m worldlab.cli bundle --run artifacts/runs/seed11 --output artifacts/bundles/seed11
```

Run directories must not exist; no previous result is overwritten. CPU training
requires at least 2 GiB available RAM before import, stops below 1.5 GiB during
training/evaluation, and has a 300 s budget. A resource refusal is not model failure.
Place caches/TEMP and outputs on D: on this Windows machine. No process is closed.

Data seeds are frozen: 101/202/303 for train/validation/test, 32/8/16 independent
episodes/parameter domains, 7 windows per episode. Entire trajectories remain in
one split; window-level random splitting is prohibited. Best epochs are selected
only by validation loss. Test is evaluated after selection, never used to choose
weights. Report data/weight hashes, model seed, exact epochs, all 3 horizon errors,
portable inference timing, native/export parity and example input/output/truth.
One-seed smoke is an implementation check, not a scientific ranking.

## Input/output contract (research, not integration-owner-approved)

`example_request.json` in each run is a complete example. Required input fields:
`contract_version=state_prediction_v0.1`, `scene_id`, `map_version`, `node_id`,
`coordinate_frame=scene_ned`, `dt_s=0.1`, `snapshot_age_s` in [0,0.5],
8 `state_history` objects (`t_s`, `position_ned_m`, `velocity_ned_mps`),
7 `action_history` vectors and 1..10 `candidate_acceleration_ned_mps2` vectors.
Limits: abs position <=10000 m, abs velocity <=30 m/s, abs acceleration <=4 m/s2.
These are input-domain guards, **not certified safe limits**. The caller supplies
snapshot age; this experiment cannot authenticate telemetry age or scene binding.
Unknown fields, stale input, local NED, irregular timestamps, NaN/Inf and unsupported
horizons are refused, not repaired.

Output: ordered predicted `position_ned_m`/`velocity_ned_mps` and offsets, node/scene
binding, canonical input/model hashes, `reason_code=SYNTHETIC_MODEL_ONLY`, warnings,
`execution_authorized=false`, `safety_verified=false`. No plan or flight command.
CLI refusal is `status=blocked`, diagnostic reason and exit code 2.

## Offline migration: desktop and Jetson AGX Orin 32GB

Copy the whole generated bundle via removable storage. Check manifest hashes:

```text
cd <copied-bundle>
python -m worldlab.cli verify --bundle .
python offline_selftest.py
python -m worldlab.cli infer --model model.json --input example_request.json
python -m worldlab.cli inventory
```

The selftest refuses Python socket audit events and compares a golden response;
metadata must match exactly and predicted coordinates/velocities have a fixed
absolute tolerance of 1e-5 for cross-architecture floating-point rounding.
it does not import Torch/NumPy. This is **not an OS-level isolated-network test**.
Before deployment acceptance, boot target with networking disconnected, use an
empty cache, verify hashes, run selftest/inference and record actual hardware,
latency, memory and repeated cold starts. Linux ARM64/JetPack and Windows/x86
training dependencies must be provisioned separately; this tiny inference bundle
does not require them. Do not copy Windows wheels or a desktop TensorRT engine to
Jetson. No `pip install` from the internet is part of target startup.

Board is not accessible in this chat. JetPack/Ubuntu/Python, storage, power/cooling
and desktop GPU remain to be confirmed. AGX Orin 32GB uses shared memory; 200 TOPS
is an INT8/sparse hardware specification, not this model's measured performance.
TensorRT/ONNX acceleration is a later target-specific validation step, not needed
to run the initial standard-library bundle. Current artifact is experimental only.

## Sources / candidates checked 2026-10-09

| Family | Purpose | Current role |
| --- | --- | --- |
| [I-JEPA](https://github.com/facebookresearch/ijepa) | Image representations | Archived official implementation; not an action-conditioned drone predictor |
| [V-JEPA](https://github.com/facebookresearch/jepa) | Video representations | Visual baseline candidate |
| [V-JEPA 2 / 2-AC / 2.1](https://github.com/facebookresearch/vjepa2) | Video features; separate action-conditioned model | 2.1 has an 80M ViT-B checkpoint; AC checkpoints are robot-task-specific, not plug-in aerial control |
| [LeJEPA](https://github.com/galilai-group/lejepa) | Self-supervised learning / SIGReg | Training method, not a ready-made drone brain |
| [LeWorldModel](https://github.com/lucas-maes/le-wm) | Small action-conditioned visual world model | About 15M parameters; existing environment checkpoints need domain validation |
| [DINO-WM](https://github.com/gaoyuezhou/dino_wm) | Latent world modeling on frozen visual features | Related comparison, not interchangeable with all JEPA implementations |
| [SkyJEPA](https://github.com/arplaboratory/SkyJEPA) | Quadrotor state dynamics | Official code/checkpoints still marked pending; do not claim official replication |

This is a task-oriented candidate map, not an exhaustive list. The state prototype
does not copy upstream models. A separate visual load experiment pins official
LeWorldModel code and weights in ignored artifacts; see [LEWM_OFFLINE.md](LEWM_OFFLINE.md).
No upstream weights are tracked in Git. Verify each code/weight license
separately before redistribution. The image's [AGX Orin specification](https://www.nvidia.com/content/dam/en-zz/Solutions/gtcf21/jetson-orin/nvidia-jetson-agx-orin-technical-brief.pdf)
defines target hardware, not acceptance results. No upstream research benchmark
score is presented as an experiment run on our machine.
