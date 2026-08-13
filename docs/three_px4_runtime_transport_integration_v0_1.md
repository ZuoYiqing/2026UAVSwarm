# Three-PX4 Runtime Transport & Integration Contract v0.1

## Status

Software contract implemented and unit-tested. A real three-PX4 Runtime run
proved independent sysid 1/2/3 bindings, telemetry, snapshots, and an isolated
UAV-02 TAKEOFF. That run also exposed the action-scoped heartbeat defect below.
Post-fix persistent-hover and explicit-LAND revalidation remains pending in this
worktree environment.

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
  starts the sole RX owner and persistent GCS heartbeat, and marks only that
  node connected.
- Actions reuse the same session and consume dispatcher state; they never open a
  parallel command socket or start/stop the GCS heartbeat.
- Stop unsubscribes telemetry, stops RX/TX heartbeat threads, closes only the
  selected node's connection, and marks that node offline.
- A telemetry subscriber exception cannot terminate the RX owner.

## GCS Heartbeat Ownership

GCS heartbeat ownership follows the persistent Vehicle Session Lifecycle, not
the TAKEOFF/LAND Action Lifecycle:

```text
VehicleRegistry.start_vehicle
  -> connect persistent session
  -> start the sole RX owner
  -> start persistent per-node GCS heartbeat

TAKEOFF / LAND
  -> reuse the connected session, RX owner, and heartbeat
  -> execute commands, wait for ACK, and collect observations only

VehicleRegistry.stop_vehicle / stop_all
  -> stop GCS heartbeat
  -> stop RX owner
  -> close the selected session
```

Repeated starts are idempotent and each node has a separately named heartbeat
thread. Heartbeat and `COMMAND_LONG` writes share a per-session TX lock, so one
node's heartbeat cannot interleave bytes with its own command or block another
node's independent session.

The real UAV-02 integration run that exposed this issue successfully received
ARM and TAKEOFF ACKs, reached about 1.8 m, and left UAV-01/UAV-03 grounded. After
the HTTP action returned, however, action-scoped cleanup stopped the GCS
heartbeat and UAV-02 landed and disarmed before an explicit LAND request. This
finding remains integration history and motivates the persistent ownership
contract above. The post-fix 45-60 second hover followed by explicit LAND must
still be revalidated in the real three-PX4 environment.

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

## Post-fix real three-PX4 validation

Use the existing mapping without introducing a second MAVLink connection:

```text
UAV-01 -> udpin:127.0.0.1:14540 -> sysid 1
UAV-02 -> udpin:127.0.0.1:14541 -> sysid 2
UAV-03 -> udpin:127.0.0.1:14542 -> sysid 3
```

After Runtime starts all three VehicleHandles, verify their RX and GCS
heartbeat threads remain alive. Send a Runtime TAKEOFF to UAV-02 with target
altitude 2.0 m and `auto_land=false`. Confirm UAV-02 is armed and reaches at
least 1.4 m while UAV-01/UAV-03 remain disarmed near the ground.

After the TAKEOFF HTTP action returns, do not run the link-loss gate. Poll
`/api/telemetry/latest?node_id=UAV-02` and retain snapshots at T+0, T+10, T+30,
and T+60 seconds. UAV-02 must remain armed and airborne for at least 45-60
seconds. Only then send an explicit Runtime LAND to UAV-02 and verify an
accepted LAND ACK followed by altitude returning to ground and `armed=false`.
Throughout the sequence UAV-01/UAV-03 must remain connected, disarmed, and near
ground.
