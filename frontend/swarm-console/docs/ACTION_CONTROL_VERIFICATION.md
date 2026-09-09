# Main Console Action Control Verification

Browser checks: 2026-09-08. Release checks: 2026-09-09.
Baseline: `b4e2f6e`. Branch: `codex/frontend-runtime-action-control`.

## Scope and dependencies

Only the main console, its tests and documentation changed. Runtime, Gazebo,
configuration and `simulation-3d` source were not modified.

Runtime dependency: PR #76, commit `3fa42eb`. Implementation was checked against
its `docs/runtime_control_execution_contract_v1.md` and
`docs/fixtures/runtime_control_contract_v1.json`. The console consumes lifecycle
1.1 and does not define new server routes. The existing 3D contract module is
imported for validation only; original coordinates and sample times are forwarded.

## Automated verification

Run in `frontend/swarm-console`: `npm test` and `npm run check`.

34 tests passed, 0 failed, 0 skipped. Coverage: selected-node routing, selection
during pending requests, duplicate clicks, LAND exclusion, ACK without completion,
Policy rejection, HTTP busy/conflicting identity, old-service fields, GET-only
refresh recovery, Runtime restart, stale/offline guards, event correlation,
response-body timeout and bridge source/origin/version/schema validation.

The main console is a static SPA with no build command or bundle output.
`git diff --check` passed; LF/CRLF notices are not whitespace errors.

## Browser fixture evidence

Action POSTs used only `http://127.0.0.1:8876/api`, a local Node fixture that
does not connect to MAVLink or a simulator. Browser Playwright interfaces and
screenshots were used for these checks:

- Desktop 1280 x 720 and narrow 390 x 844 inspected; document width stayed within
  viewport width (1265/1280 and 375/390 respectively).
- UAV-02 TAKEOFF requested node UAV-02, sysid 2, compid 1, endpoint 14541,
  stable request/trace/idempotency identifiers and no auto-land flag.
- ACK accepted remained executing / awaiting telemetry, not flight success.
- Switching to UAV-03 showed NO ACTION rather than UAV-02's result.
- Explicit fixture completion showed historical stable-height evidence at 3 m.
- Separate UAV-02 LAND showed landed/disarmed evidence, height 0 and armed=false.
  UAV-01/UAV-03 received no action POSTs.
- stale telemetry disabled both flight buttons; Policy rejection showed DENY,
  no ACK evidence and no completion confirmation.
- Terminal-result reload was exercised. GET-only recovery during an unresolved
  request is covered by automated tests, not claimed as a browser flight test.
- Browser console inspection reported no JavaScript errors.

Fixture changes are explicit test inputs, not frontend timer-generated progress.
Busy and Runtime-restart behavior are unit-tested, not real-environment verified.

## Real environment and remaining risks

NOT RUN: real UAV-02 takeoff / hold / LAND / disarm, UAV-01/03 isolation,
three-PX4 ACK ordering, Gazebo observation, Cesium iframe LIVE visualization and
four-module agreement. No real flight command was sent this round.

Keep the PR Draft pending Runtime #76 and joint real-environment acceptance.
HOLD/GOTO/RETURN_HOME have no operational route. TAKEOFF completion proves past
height stability, not ongoing hold; LAND priority belongs to Runtime.

Runtime idempotency state is in memory. Lost unresolved records remain unknown
and block repeat takeoff; the console never automatically replays POST. Operator
reconciliation is still needed after such a restart.

Matching Runtime/Simulation scene IDs does not prove Cesium loaded the same map.
Missing/mismatched metadata remains unknown/not aligned. Deployment must include
the existing shared 3D contract file even if the 3D application is served separately.
