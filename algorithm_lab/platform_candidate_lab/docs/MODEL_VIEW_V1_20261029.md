# UAV-02 model decision view v1 — 2026-10-29

## Why this view exists

Runtime's synthetic full-task replay showed that the original full JSON request
did not fit the historical Ubuntu CPU bundle's `--ctx-size 512`: the model
server reported 523–546 prompt tokens for six steps. With a diagnostic 2048
context the overflow disappeared, but Runtime's healthy three steps exceeded
its unchanged two-second model deadline. These are Runtime-side observations,
not a claim that the new view has passed a combined replay.

## Boundary

`POST /candidate` request/response contract v1.0 is unchanged. The candidate
adapter validates the **full** request and computes its original SHA-256 before
constructing the model input. Rejection for fake source without explicit test
opt-in, stale/future observation, expired authorization or lost-link TAKEOFF
still happens before model invocation. The model only chooses one of the two
preauthorized option IDs; its output never authorizes execution.

`uav02_candidate_view_v1` contains:

- `authorization`: remaining milliseconds, max altitude, max hold duration,
  offline policy. The operator identity stays in the full audited request.
- `ground_link`: the entire provided link object, including optional time and
  age evidence.
- `next_step`: the authorized action and all its parameters. The repeated
  step ID is only correlation data and stays in the full request/response.
- `observation`: the **entire** validated local observation, including every
  optional sensor, battery, landed-state, position and velocity field.
- `observation_age_ms`: derived from the same UTC evaluation instant used for
  the prechecks.
- `options`: `execute_authorized_step` and `abort_to_land`. Full-contract
  validation has already proved their action/parameter mapping, so repeating
  those objects to the model would add no decision information.

The system prompt makes the two option meanings explicit. A lost ground link
with `offline_policy=continue_authorized` is not by itself a reason to abort;
the model may still propose abort based on local telemetry. Runtime remains
the final authority, retains its two-second deadline and deterministic
authorized fallback, and must not interpret `no_candidate` as task success.

Response `evidence.input_sha256` continues to hash the full request with
Runtime-compatible canonical serialization. New `model_view_sha256` hashes the
canonical model-view JSON, and `model_view_version` plus `model_view_at` make
the derived time fields reproducible. A failed precheck records null view
metadata because the model was not called. Neither hash is a signature or
proof that the model result is safe.

## Algorithm-side verification

Unit tests inspect the exact model messages, omission of non-decision IDs,
retention of all sensor fields, stable view hash under correlation-ID changes,
hash change under battery/time changes, and pre-model rejections. On the
algorithm worktree at `735af74`, 16/16 tests passed. The synthetic HOLD fixture
model-view JSON has 617 characters versus 996 for the original full request;
these character counts are not tokenizer measurements or latency results.

## Independent Runtime fake replay — reported 2026-10-29

Runtime committed its verification script and evidence report at
`876bb92f04b6bc6c7b74368323ce7b8abd72f861` ([Draft PR #97](https://github.com/ZuoYiqing/2026UAVSwarm/pull/97),
`docs/runtime_local_model_verification_20261029.md`). That report explicitly
pins the algorithm **production Python source** to
`735af7485a5d953bdea2e48c8d634e256d325af5`, supplied through its
`--candidate-source` experiment option. Runtime did not copy or rewrite this
module. The historical 2026-10-24 bundle remained read-only and still contains
the older algorithm source `17017cd`; only its pinned Qwen3.5-0.8B Q4 weight
and llama.cpp b10964 Linux CPU engine were reused.

Both independent model-process starts used Ubuntu 22.04 x86-64, CPU-only,
`ctx512`, four inference threads, loopback services and Runtime's unchanged
2,000 ms deadline. Telemetry and action execution were `fake`; no PX4/Gazebo,
MAVLink, console, 3D display or UGV was connected.

| Measurement | First process | Independently restarted process |
| --- | ---: | ---: |
| Model and candidate service readiness | 21.906 s | 20.403 s |
| Direct synthetic candidate requests | 6/6, first 1286.280 ms | 6/6, first 1287.082 ms |
| Complete healthy task steps | 3/3 model candidates, 0 fallback | 3/3 model candidates, 0 fallback |
| Complete lost-after-takeoff task steps | 3/3 model candidates, 0 fallback | 3/3 model candidates, 0 fallback |
| Full-task candidate step latency | 1004.288–1063.107 ms | 1043.557–1087.854 ms |

Across the two runs, complete tasks yielded **12/12 timely valid candidates**
and no unexpected fallback. The full input SHA-256 in each of those 12 responses
matched Runtime's corresponding `model_request` event. The separate
model-unavailable test still took the preauthorized deterministic fake fallback.
Two independent process restarts do not imply a cold operating-system disk
cache, a load/stress distribution or a p99 bound. The model's slot `n_tokens`
of 324–329 for complete requests includes generated output; it is **not** a
measurement of pure input tokens. There was no `ctx512` overflow in these two
replays. Runtime's final full test suite was reported as 969 passed, 12 skipped;
that is Runtime-side regression evidence, not this module's test count.

The previous full-request experiments remain part of the record: with the old
algorithm source at `ctx512`, full task prompts were 523–546 tokens and six
steps all fell back; raising only context to 2048 removed overflow but often
missed the two-second deadline. The compact view addresses that measured
failure for these synthetic cases. It does **not** authorize execution or
prove performance on a Jetson, another desktop, real telemetry, PX4 flight,
physical UGV, prolonged operation or different task distributions.

Any new offline distribution must be separately built, pinned, licensed,
hashed and tested. Do not describe the unchanged 2026-10-24 archive as if it
already contains algorithm source `735af74`.
