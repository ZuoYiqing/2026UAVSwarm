# Three-PX4 Runtime Transport & Integration Contract v0.1

## Status

Software contract implemented and unit-tested. Real three-PX4 Runtime
integration is pending because this Windows environment has no installed WSL
distribution and therefore cannot start the Linux PX4/Gazebo harness.

## Current transport findings

The authoritative simulation manifest maps UAV-01/02/03 to PX4 instances
0/1/2, MAVLink systems 1/2/3, and offboard receive endpoints
`udpin:127.0.0.1:14540/14541/14542`. Each vehicle uses the same endpoint for
command and telemetry. This matches the checked-in PX4 discovery evidence and
the harness port validator.

The previous Runtime mapping used `14540` for commands and a second `14030`
collector for UAV-01, while UAV-02/03 were disabled. Runtime also created a
command session and a collector-owned session, and command ACK, altitude
observation, and telemetry each called `recv_match` independently. That model
does not satisfy the actual manifest contract.

## Chosen architecture: shared session

Each `VehicleHandle` owns exactly one persistent `MavlinkBackendSession`, one
connection, one receive thread, and one per-node command lock. The receive
thread is the only Runtime caller of `recv_match` and routes messages as follows:

```text
PX4 endpoint -> one Registry session -> one RX owner
                                  |-> identity filter
                                  |-> command-scoped ACK mailbox
                                  |-> LOCAL_POSITION_NED condition/cache
                                  `-> telemetry subscriber -> Registry cache
```

The ACK waiter is installed before a command is sent. Unclaimed ACKs are
dropped, each command generation clears its mailbox, and a wrong command ACK
cannot satisfy another waiter. MAVLink does not carry an application correlation
token for repeated identical `COMMAND_LONG` requests, so the contract also
serializes commands per node and does not allow overlapping same-command waits.

## Ownership and lifecycle

- Register creates one session and immutable expected sysid/component binding.
- Start connects, waits for heartbeat, validates identity, subscribes telemetry,
  starts the sole RX owner, and marks only that node connected.
- Actions reuse the same session and consume dispatcher state; they never open a
  parallel command socket.
- Stop unsubscribes telemetry, stops RX/TX heartbeat threads, closes only the
  selected node's connection, and marks that node offline.
- A telemetry subscriber exception cannot terminate the RX owner.

## Endpoint and identity invariants

- Same-node command and telemetry endpoints must be equal in this shared-session
  release and therefore share one socket.
- An endpoint owned by one node cannot be used by another node in any role.
- Concrete sysid/component values are 1..255; broadcast IDs are invalid.
- Initial heartbeat and every message carrying source identity are checked
  against the handle's expected sysid/component before dispatch.
- Backend temporary probes validate both IDs and close their connection in a
  `finally` block. An already connected Registry session is reused instead.

## Deployment truth

Runtime now reads and converts
`simulation/px4_gazebo/config/three_uav_sitl.json` directly. The manifest also
names `UAV-01` as the explicit default. The retained
`config/vehicles.sitl.json` declares its generator source and is checked by
`validate_runtime_mapping`; drift fails validation.

| node | instance | sysid/component | endpoint | enabled |
| --- | ---: | --- | --- | --- |
| UAV-01 | 0 | 1/1 | `udpin:127.0.0.1:14540` | yes |
| UAV-02 | 1 | 2/1 | `udpin:127.0.0.1:14541` | yes |
| UAV-03 | 2 | 3/1 | `udpin:127.0.0.1:14542` | yes |

## Safety hardening

- Harness state records Linux process start time, expected executable, exact
  command line, runtime directory, node, PID, and PGID. Stop validates all live
  identities before sending TERM/KILL. PID reuse or any mismatch produces
  `stale_process_identity` and sends no signal.
- Scene v0.1 accepts `local_ned` only. `local_enu` is rejected until all
  consumers implement explicit frame-aware conversion.
- Active integration validation records `takeoff_observed`,
  `land_command_accepted`, and `landed_observed`. If takeoff may have occurred
  and landing was not observed, cleanup sends a best-effort LAND and observes
  landing without masking the original failure.
- pytest sets `UAV_RUNTIME_AUDIT_PATH` to a per-test temporary file and redirects
  the already-imported HTTP audit path. Formal `audit/runtime.audit.jsonl` is not
  changed by tests.

## Validation layers

1. Unit/contract: dispatcher owner count, three-owner isolation, ACK routing,
   subscriber telemetry, source identity, lifecycle, endpoint collision,
   manifest consistency, PID reuse, NED-only scene, landing recovery, and audit
   isolation.
2. Full pytest: includes opt-in real-PX4 tests, which skip without
   `UAV_RUNTIME_PX4_MULTI_CONFIG`.
3. Harness static/config: manifest and scene validation run without opening UDP.
4. Real Runtime: start harness, end the short-lived health probe, start Runtime,
   confirm three connected handles/snapshots, take off and land UAV-02, verify
   UAV-01/UAV-03 isolation, then stop safely. Pending in this environment.

The historical July harness validation remains useful evidence for PX4/Gazebo
itself, but it is not substituted for a post-change real Runtime integration
run.
