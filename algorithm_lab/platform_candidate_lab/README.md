# UAV-02 local model candidate lab (v0.1)

This isolated research adapter proposes one of two *already authorized* options for
the next UAV-02 platform step. It does not send flight commands, grant execution
authority, change action parameters, read Gazebo truth, or provide ground-side
realtime data. Runtime owns task persistence, Policy Gate, deterministic fallback,
and every actual action. This phase supports only takeoff, hold_position, and land;
it is **not** navigation or inspection.

## Wire contract

Runtime calls loopback `POST http://127.0.0.1:8872/candidate` with a JSON body
containing contract_version 1.0, UAV-02 and task/step/request/trace identities,
snapshot_id equal to request_id, decision_timeout_ms, ground_link, authorization,
next_step, local observation, and exactly these allowed_options:

```json
[
  {"option_id":"execute_authorized_step","action_type":"hold_position","params":{"hold_s":3}},
  {"option_id":"abort_to_land","action_type":"land","params":{}}
]
```

See [the complete synthetic request](fixtures/uav02_hold_request.json). The
authorization carries operator_id, expiry, offline_policy, altitude and hold
limits. Observation comes from PX4 telemetry in SITL; fake input is rejected
unless the test-only `--allow-fake` flag is set. Timestamps accept UTC `Z` or
`+00:00`. Local position is **vehicle-local NED** and is never interpreted as
shared scene NED or used to compare vehicles.

On success the response echoes all identities and returns `status:candidate`,
`decision` plus `candidate.option_id`, evidence hashes, and
`execution_authorized:false`. On timeout, bad model output, stale input,
expired authorization, or disconnected new takeoff it returns
`status:no_candidate`, null decision/candidate, and a reason code. Invalid
request structure receives HTTP 400. Runtime must treat every non-candidate,
error, or missed 2-second deadline as model unavailable and perform its own
authorized deterministic handling; it must never execute model text as an action.
The adapter has no automatic retry or remote inference path.

The inference backend is a local `llama.cpp` process exposing a loopback JSON
chat endpoint. `/health` reports only that the adapter process is alive, **not**
that the model is loaded or ready. Model weights, binaries, logs, and experiment
records stay in ignored D: artifact directories and are not in Git.

## Reproduce without a model

From `algorithm_lab`:

```powershell
D:\anaconda\python.exe -S -m unittest discover -s platform_candidate_lab/tests -v
D:\anaconda\python.exe -S -m platform_candidate_lab validate --input platform_candidate_lab/fixtures/uav02_hold_request.json --at 2026-10-22T12:00:01Z --model-output-file platform_candidate_lab/fixtures/model_valid.json --allow-fake
D:\anaconda\python.exe -S -m platform_candidate_lab validate --input platform_candidate_lab/fixtures/uav02_hold_request.json --at 2026-10-22T12:00:01Z --model-output-file platform_candidate_lab/fixtures/model_unauthorized.json --allow-fake
D:\anaconda\python.exe -S -m platform_candidate_lab validate --input platform_candidate_lab/fixtures/uav02_hold_request.json --at 2026-10-22T12:00:01Z --model-failure MODEL_TIMEOUT --allow-fake
```

Only the first output may contain a candidate. Unauthorized output and timeout
must return `no_candidate`; all three keep
`execution_authorized:false`. The input SHA-256 is over UTF-8 JSON with sorted
keys, compact separators, default ASCII escaping, and non-finite values
forbidden.

## Local-only model experiment

Run a separately started and verified local model on port 18080, then:

```powershell
D:\anaconda\python.exe -S -m platform_candidate_lab serve --model-url http://127.0.0.1:18080/v1/chat/completions --model-id qwen3.5-0.8b-q4-lab --port 8872
```

The adapter binds 127.0.0.1 only. For synthetic offline testing, explicitly add
`--allow-fake`; do not use that flag for the SITL deployment. A single synthetic
experiment can be recorded with `python -S -m platform_candidate_lab.experiment`
and its `--model-url`, `--model-id`, and an unused `--output` path under
`platform_candidate_lab/artifacts/runs/`.

On 2026-10-22, the already-downloaded Qwen3.5-0.8B Q4 model on this desktop
returned `execute_authorized_step` for a **synthetic lost-link HOLD request**
twice through the adapter: 2419.32 ms at a 10-second budget, then 1080.47 ms at
a 2-second budget after warm-up. A direct `POST /candidate` on the same local
model with the corrected Runtime-shaped request returned five candidates
under a 2-second model budget; localhost HTTP wall times were 1313.61,
229.97, 236.15, 235.12, and 220.08 ms. The repeated prompt may benefit
from cache, so these numbers do not estimate diverse-task latency. These are
inference observations, not a
latency distribution, safety proof, real telemetry test, or flight validation.
In particular, 2419.32 ms would miss Runtime's current hard 2-second deadline.
The response was a proposal only; no PX4, Gazebo, or other module was started
by this experiment.

Runtime's platform implementation is being developed in another worktree; the
adapter has not yet passed a combined Runtime/flight acceptance test.

The already-downloaded MiniCPM5-1B Q4 profile was also attempted separately on
2026-10-22. Its launcher refused admission **before model loading** because
available host RAM was about 1.93 GiB, below its 3 GiB safety budget. No
MiniCPM inference or quality result is claimed, and the guard was not bypassed.
