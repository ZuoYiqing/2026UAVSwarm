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

## Verification required before integration

Unit tests inspect the exact model messages, omission of non-decision IDs,
retention of all sensor fields, stable view hash under correlation-ID changes,
hash change under battery/time changes, and pre-model rejections. This is not a
tokenizer measurement, CPU latency result or flight acceptance. The Runtime
owner will separately replay full synthetic tasks using this source with the
previously pinned engine/weight, measure prompt tokens and end-to-end time,
and keep `--allow-fake` confined to that synthetic test. The old offline
bundle remains immutable; any new distribution must be repackaged and hashed
after acceptance.
