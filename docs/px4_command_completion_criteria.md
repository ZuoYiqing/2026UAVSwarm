# PX4 Command Completion Criteria

## 1) COMMAND_ACK Meaning

`COMMAND_ACK` is a command acceptance / rejection signal from PX4.
It is not, by itself, proof that the requested physical action completed.

Examples:

- ARM ACK accepted: PX4 accepted the arm command.
- TAKEOFF ACK accepted: PX4 accepted the takeoff command.
- LAND ACK accepted: PX4 accepted the land command.

An accepted ACK can still be followed by no movement, limited movement, failsafe behavior, or a later state transition. Completion must be judged with telemetry or simulation observation.

---

## 2) Takeoff Smoke Pass Criteria

For the current PX4 SITL takeoff smoke:

| Field | Expected value |
| --- | --- |
| `target_altitude_m` | `3` |
| `threshold_ratio` | `0.7` |
| `threshold_altitude_m` | `2.1` |
| `max_altitude_m` | `>= 2.1` |
| `threshold_reached` | `true` |
| `result` | `pass` |

The altitude source is `LOCAL_POSITION_NED`.
PX4 NED `z` is positive down, so runtime computes:

```python
altitude_m = max(0.0, -float(z))
```

The takeoff smoke is considered passed only when the observed altitude reaches the threshold, not merely when `MAV_CMD_NAV_TAKEOFF` ACK is accepted.

---

## 3) Land Completion Guidance

Current runtime v0.1 records LAND ACK and optional altitude observation evidence.
For a later stronger landing-complete check, use telemetry criteria such as:

- LAND ACK accepted;
- altitude decreases below `0.25m`;
- vertical velocity settles near zero;
- PX4 landed / disarmed state is observed when available.

This stage does not implement full landing completion. It only records LAND ACK and leaves full landing-state validation for a later phase.
