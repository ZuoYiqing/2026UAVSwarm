# Landing evidence baseline (contract proposal v0.1)

This offline research module checks a narrow, stated **scene-ground contact evidence**
criterion. Its result is not an action result, landing-surface safety proof, mission
completion, or execution authorization. It imports no Runtime, simulator, flight
controller, network client, model weights or third-party packages.

From the `algorithm_lab` directory:

```text
python -m unittest discover -s landing_assessment_lab/tests -v
python -m landing_assessment_lab --input landing_assessment_lab/fixtures/roof_contact.json
python -m landing_assessment_lab --input landing_assessment_lab/fixtures/ground_contact.json
```

No files are written unless `--output NEW_PATH` is provided; an existing output is
refused. Input and output shapes are in `schemas/`. Python also enforces cross-field
conditions, finite numbers, unique sample IDs and scene/calibration matching that
JSON Schema alone does not prove. The fixture values are **synthetic replays** based
on the rooftop failure shape, not original ULog or live vehicle telemetry.
`examples/roof_assessment_result.json` is the checked-in output for the roof fixture.

## Meaning of the three statuses

- `criteria_met`: fresh, distinct, time-ordered samples span the required duration;
  every sample reports landed and disarmed, and every shared `scene_ned.down_m`
  lies within tolerance of the **supplied** scene-ground reference. This says only
  that the supplied evidence meets that criterion. It does not prove the reference
  is authentic or that an unfamiliar surface supports an aircraft.
- `criteria_not_met`: adequate comparable observations explicitly contradict the
  criterion, such as the rooftop samples 9.98 m above the stated scene ground.
- `unknown`: evidence cannot be compared: unknown surface, absent calibration or
  ground reference, wrong scene/map binding, stale/future samples, too short a
  stable window or missing scene position. A short downward range alone never
  identifies the surface or its bearing capacity.

The current rule never declares a newly discovered surface feasible. It never
calculates confidence: the result is always `null`. `surface_safety` remains
`unknown`; `execution_authorized` and `task_completed` are always false.

## Ownership and timing

The request separates `goal` (what must be shown) from `observation` (sensor/state
reports with source references) and `correlation` (Runtime IDs). Each sample time
and `evaluated_at_s` must use the same declared timebase (`unix_s`,
`simulation_s`, or `px4_boot_s`). `max_sample_age_s` applies to the dynamic sample
window only. Static geometry and capability evidence must instead bind to scene,
map, model and software versions in a future agreed contract. No supplied
`source_ref`, `source_kind`, time or scene version is authenticated by this module.
The Runtime would have to verify source identity, freshness and calibration before
consuming any future algorithm result.

For this proposal, Runtime supplies normalized per-node `scene_ned` positions with
their calibration version. `vehicle_local_ned` is deliberately not accepted; the
algorithm must not compare different vehicles' local origins. An image reference
means only that a frame exists. Even `rgb_capture` does not imply a detection.

Action progress/completion, Policy, operator approval and final task completion
stay in Runtime. In particular, `criteria_met` must not be mapped to Runtime
`succeeded`. Current-position landing, actual PX4 home return and designated-site
task fulfillment need separate goal and completion semantics. This module implements
only the first stated scene-ground contact criterion; `unknown_surface` is a
deliberate unknown. It does not modify the existing executor contract.

## Failure-case record for independent evaluation

Keep immutable raw observation and decision JSON, request/action/trace IDs,
source clock and wall-clock mapping, scene/map/world hash, software/model versions,
calibration, input and output SHA-256, Policy/ACK/mode sequence, post-action
telemetry, and reason codes. Store truth **separately**: Simulation can label the
physical collision surface from world geometry and ULog after a run; an independent
reviewer signs off the label with its evidence reference. The assessor must not
receive world collision truth when evaluating sensor-only perception. Runtime's
historic `succeeded` field is an outcome to audit, never the training label.
Preserve roof false-success, missing calibration, stale data and sensor-absence
cases. Split training/evaluation by world layout, run and vehicle configuration;
do not leak near-duplicate windows across splits. Report unknown coverage,
false positive rate and false negative rate separately.

No real flight, camera inference, Orin measurement or new dependency is claimed.
