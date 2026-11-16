"""Companion autonomy: fake adapters and controlled clocks, never PX4 ports."""
from __future__ import annotations

from copy import deepcopy
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from uav_runtime.platform.contract import PlatformError, stamp
from uav_runtime.platform.service import PlatformService, IDENTITY
from uav_runtime.platform.store import TaskStore
from uav_runtime.platform.server import PlatformHttpServer
from uav_runtime.platform.transport import JsonClient


def task():
    return {"contract_version": "1.0", "node_id": "UAV-02", "task_id": "t-1", "task_version": 1,
            "request_id": "r-1", "trace_id": "trace-1",
            "authorization": {"operator_id": "operator", "expires_at": stamp(1100), "offline_policy": "continue_authorized",
                              "max_altitude_m": 3, "max_hold_s": 10},
            "steps": [{"step_id": "takeoff-1", "action": "takeoff", "params": {"altitude_m": 3}},
                      {"step_id": "hold-1", "action": "hold_position", "params": {"hold_s": 3}},
                      {"step_id": "land-1", "action": "land", "params": {}}]}


@pytest.fixture
def environment(tmp_path):
    store = TaskStore(tmp_path / "agent")
    clock, calls = [1000.0], []
    def execute(t, step):
        calls.append(step["action"])
        return PlatformService._fake_execute(t, step)
    service = PlatformService(store, execute=execute, clock=lambda: clock[0], monotonic=lambda: clock[0])
    service.heartbeat()
    yield service, store, clock, calls
    service.stop.set()
    if service.worker:
        service.worker.join(timeout=2)
    store.close()


def test_persistent_idempotency_and_no_duplicate_execution(environment):
    service, store, _, calls = environment
    first, created = service.submit(task())
    assert created
    replay, created = service.submit(task())
    assert not created and replay["execution_id"] == first["execution_id"]
    service.run_task(first["task_id"])
    assert store.task("t-1")["status"] == "succeeded"
    service.run_task("t-1")
    assert calls == ["takeoff", "hold_position", "land"]
    changed = task()
    changed["steps"][1]["params"]["hold_s"] = 2
    with pytest.raises(PlatformError, match="idempotency_conflict"):
        service.submit(changed)


def test_link_lost_after_takeoff_continues_local_hold_and_land(environment):
    service, store, clock, calls = environment
    def execute(t, step):
        calls.append(step["action"])
        if step["action"] == "takeoff":
            clock[0] += 4
        return PlatformService._fake_execute(t, step)
    service.execute = execute
    service.submit(task())
    service.run_task("t-1")
    assert service.link()["state"] == "lost"
    assert store.task("t-1")["status"] == "succeeded"
    events = store.events()["events"]
    assert any(e["event_type"] == "platform_policy_decision" and e["data"]["ground_link"]["state"] == "lost"
               and e["data"]["action"] == "land" and e["data"]["decision_code"] == "allow" for e in events)
    assert calls == ["takeoff", "hold_position", "land"]


def test_link_lost_before_takeoff_sends_nothing(environment):
    service, store, clock, calls = environment
    service.submit(task())
    clock[0] += 4
    service.run_task("t-1")
    assert store.task("t-1")["status"] == "failed" and calls == []
    assert store.task("t-1")["failure_reason"] == "takeoff_requires_ground_link"


@pytest.mark.parametrize("mutation", ["wrong_node", "expired", "too_high", "too_long", "goto", "disarm", "extra", "repeat_step", "version"])
def test_invalid_or_expanded_authorization_refused(environment, mutation):
    service, _, _, calls = environment
    body = task()
    if mutation == "wrong_node": body["node_id"] = "UAV-01"
    if mutation == "expired": body["authorization"]["expires_at"] = stamp(900)
    if mutation == "too_high": body["steps"][0]["params"]["altitude_m"] = 100
    if mutation == "too_long": body["steps"][1]["params"]["hold_s"] = 100
    if mutation in {"goto", "disarm"}: body["steps"][1]["action"] = mutation
    if mutation == "extra": body["authorization"]["can_do_anything"] = True
    if mutation == "repeat_step": body["steps"][1]["step_id"] = "takeoff-1"
    if mutation == "version": body["task_version"] = True
    with pytest.raises(PlatformError): service.submit(body)
    assert calls == []


def test_new_task_busy_and_failed_land_remains_blocked(environment):
    service, store, _, calls = environment
    service.submit(task())
    another = task(); another.update(task_id="t2", request_id="r2")
    with pytest.raises(PlatformError, match="node_busy"): service.submit(another)
    def execute(t, step):
        calls.append(step["action"])
        return {"status": "accepted", "result": "pass"} if step["action"] == "land" else service._fake_execute(t, step)
    service.execute = execute
    service.run_task("t-1")
    assert calls.count("land") == 1  # An uncertain LAND is not blindly retried.
    assert store.task("t-1")["status"] == "recovery_required"
    assert service.status()["safe_to_stop"] is False
    service.reconcile("t-1", "operator", store.task("t-1")["execution_id"])
    assert store.task("t-1")["status"] == "failed"
    assert service.status()["safe_to_stop"] is True


def test_expired_authorization_during_flight_recovers_without_success(environment):
    service, store, clock, calls = environment
    def execute(t, step):
        calls.append(step["action"])
        if step["action"] == "takeoff": clock[0] = 1200
        return service._fake_execute(t, step)
    service.execute = execute
    service.submit(task()); service.run_task("t-1")
    assert calls == ["takeoff", "land"]
    assert store.task("t-1")["status"] == "failed"
    assert store.task("t-1")["failure_reason"] == "authorization_expired"
    assert service.submit(task())[1] is False  # Reconnection replay after expiry.


def candidate_reply(request):
    return 200, {"contract_version": "1.0", **{key: request[key] for key in IDENTITY}, "status": "candidate",
                 "execution_authorized": False, "decision": "execute_authorized_step", "evidence": {"model_id": "test"}}


@pytest.mark.parametrize("failure", ["exception", "bad_node", "expanded_decision", "no_candidate", "late"])
def test_model_cannot_change_authority_and_failure_has_deterministic_fallback(environment, failure):
    service, store, clock, calls = environment
    def model(request):
        assert "ground_reference" not in request["observation"]
        if failure == "exception": raise TimeoutError
        status, reply = candidate_reply(request)
        if failure == "bad_node": reply["node_id"] = "UAV-01"
        if failure == "expanded_decision": reply["decision"] = "goto_roof"
        if failure == "no_candidate": reply["status"] = "no_candidate"
        if failure == "late": clock[0] += 2.1; service.heartbeat()
        return status, reply
    service.candidate = model
    service.submit(task()); service.run_task("t-1")
    assert calls == ["takeoff", "hold_position", "land"]
    assert store.task("t-1")["status"] == "succeeded"
    assert any(e["event_type"] == "model_unavailable" for e in store.events()["events"])


def test_model_abort_to_land_records_failed_task(environment):
    service, store, _, calls = environment
    def model(request):
        status, reply = candidate_reply(request)
        if request["next_step"]["action"] == "hold_position": reply["decision"] = "abort_to_land"
        return status, reply
    service.candidate = model
    service.submit(task()); service.run_task("t-1")
    assert calls == ["takeoff", "land"]
    assert store.task("t-1")["status"] == "failed"


def test_cancel_during_action_preserves_recovery_semantics(environment):
    service, store, _, calls = environment
    def execute(t, step):
        calls.append(step["action"])
        if step["action"] == "takeoff": service.cancel(t["task_id"])
        return service._fake_execute(t, step)
    service.execute = execute
    service.submit(task()); service.run_task("t-1")
    assert calls == ["takeoff", "land"]
    assert store.task("t-1")["status"] == "cancelled"


def test_restart_recovers_without_replay_and_keeps_cursor(tmp_path):
    store = TaskStore(tmp_path)
    first = PlatformService(store, clock=lambda: 1000)
    first.heartbeat(); record, _ = first.submit(task())
    checkpoint, sid = store.events()["checkpoint_seq"], store.store_id
    store.close()
    reopened = TaskStore(tmp_path)
    try:
        second = PlatformService(reopened, clock=lambda: 1000)
        assert second.boot_id != first.boot_id and reopened.store_id == sid
        assert reopened.task("t-1")["status"] == "recovery_required"
        assert second.submit(task())[1] is False
        second.run_task("t-1")
        assert reopened.events(checkpoint)["events"][0]["event_type"] == "task_recovery_required"
        with pytest.raises(PlatformError, match="event_cursor_ahead"): reopened.events(999999)
        with pytest.raises(PlatformError, match="store_deployment_mismatch"): PlatformService(reopened, node_id="UAV-01")
    finally:
        reopened.close()


def test_store_has_one_process_owner(tmp_path):
    first = TaskStore(tmp_path)
    try:
        with pytest.raises(PlatformError, match="store_already_owned"): TaskStore(tmp_path)
    finally:
        first.close()


def test_http_auth_async_acceptance_and_disconnect_do_not_reexecute(environment):
    service, store, _, calls = environment
    token = "t" * 40
    server = PlatformHttpServer(("127.0.0.1", 0), service, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(HTTPError) as error: urlopen(base + "/api/platform/status")
        assert error.value.code == 401
        client = JsonClient(base, token)
        code, first = client.request("POST", "/api/platform/tasks", task())
        assert code == 202
        assert calls == []  # Submission is durable; not executed on HTTP thread.
        service.run_task("t-1")
        code, replay = client.request("POST", "/api/platform/tasks", task())
        assert code == 200 and replay["idempotent_replay"]
        assert calls == ["takeoff", "hold_position", "land"]
        assert client.request("GET", "/api/platform/tasks/t-1")[1]["task"]["status"] == "succeeded"
        assert client.request("GET", "/api/platform/events?store_id=wrong")[0] == 409
        assert client.request("POST", "/api/actions/takeoff", {})[0] == 404
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


@pytest.mark.parametrize("url", ["https://127.0.0.1:8766", "http://localhost:8766", "http://192.168.1.1:8766", "http://user:secret@127.0.0.1:8766"])
def test_candidate_and_gateway_require_explicit_loopback(url):
    with pytest.raises(PlatformError): JsonClient(url)


def test_fixture_is_accepted_and_matches_status_projection(environment):
    from pathlib import Path
    from uav_runtime.platform.contract import timestamp
    service, _, clock, _ = environment
    fixture = json.loads((Path(__file__).resolve().parents[2] / "docs/fixtures/platform_autonomy_v1.json").read_text())
    clock[0] = timestamp(fixture["fixture_clock"])
    service.heartbeat()
    service.submit(fixture["task_request"])
    status = service.status()
    for key, value in fixture["status_response_projection"].items():
        assert status[key] == value
    assert all(key in status for key in fixture["dynamic_status_fields"])


@pytest.mark.parametrize("stale", [True, False])
def test_local_observation_freshness_is_independent_of_ground_link(environment, stale):
    service, store, _, calls = environment
    service.observe = lambda: {"source": "fake", "sample_timestamp": stamp(1000 if stale else 900),
                              "stale": stale, "local_position": {}}
    service.submit(task()); service.run_task("t-1")
    assert calls == []
    assert store.task("t-1")["failure_reason"] == "local_observation_stale"


def test_store_cannot_promote_fake_results_to_sitl(environment):
    service, store, _, _ = environment
    with pytest.raises(PlatformError, match="store_deployment_mismatch"):
        PlatformService(store, mode="sitl", execute=service.execute, observe=service.observe)


def test_ground_gateway_relays_tasks_events_and_link_through_same_application_leg(environment, monkeypatch):
    from uav_runtime.http import routes
    from uav_runtime.platform.gateway import PlatformGateway
    service, _, _, calls = environment
    token = "x" * 40
    server = PlatformHttpServer(("127.0.0.1", 0), service, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    gateway = PlatformGateway(f"http://127.0.0.1:{server.server_port}", token)
    monkeypatch.setattr(routes, "PLATFORM_GATEWAY", gateway)
    try:
        code, accepted = routes.dispatch("POST", "/api/platform/tasks", body=task())
        assert code == 202 and accepted["task"]["node_id"] == "UAV-02"
        assert routes.dispatch("GET", "/api/platform/status")[0] == 200
        assert calls == []
        monkeypatch.setattr(gateway.client, "request", lambda *a, **k: (_ for _ in ()).throw(ConnectionError()))
        code, response = routes.dispatch("GET", "/api/platform/status")
        assert code == 503 and response["observation_status"] == "unknown"
        assert service.store.task("t-1")["status"] == "accepted"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_sse_cursor_replays_persistent_events_without_heartbeat_refresh(environment):
    service, store, clock, _ = environment
    service.submit(task()); service.run_task("t-1")
    clock[0] += 4
    token = "s" * 40
    server = PlatformHttpServer(("127.0.0.1", 0), service, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    after = store.events()["checkpoint_seq"] - 1
    request = Request(f"http://127.0.0.1:{server.server_port}/api/platform/events/stream?after_seq={after}",
                      headers={"Authorization": "Bearer " + token})
    try:
        with urlopen(request, timeout=2) as response:
            assert response.headers["Content-Type"] == "text/event-stream"
            assert response.readline().decode().strip() == f"id: {after + 1}"
            assert response.readline().strip() == b"event: platform_event"
            event = json.loads(response.readline().decode().removeprefix("data: "))
            assert event["seq"] == after + 1 and event["task_id"] == "t-1"
            assert service.link()["state"] == "lost"
    finally:
        service.stop.set()
        with store.changed: store.changed.notify_all()
        server.shutdown(); server.server_close(); thread.join(timeout=2)


@pytest.mark.parametrize("failure", [BrokenPipeError, ConnectionResetError, ConnectionAbortedError])
@pytest.mark.parametrize("stage", ["headers", "body"])
def test_legacy_http_disconnect_does_not_write_second_response(failure, stage):
    from types import SimpleNamespace
    from uav_runtime.http.server import RuntimeHttpBridgeHandler
    calls = []
    def broken(*a):
        calls.append("broken")
        raise failure()
    handler = SimpleNamespace(send_response=lambda *a: calls.append("response"), send_header=lambda *a: None,
                              _send_cors_headers=lambda: None, end_headers=broken if stage == "headers" else lambda: None,
                              wfile=SimpleNamespace(write=broken))
    RuntimeHttpBridgeHandler._send_json(handler, 200, {"value": "ok"})
    assert calls == ["response", "broken"]


def test_transport_lease_excludes_other_stores_and_releases_on_close():
    import socket
    from uav_runtime.platform.ownership import TransportLease
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]
    endpoint = f"udpin:127.0.0.1:{port}"
    first = TransportLease(endpoint)
    try:
        with pytest.raises(PlatformError, match="mavlink_transport_already_owned"):
            TransportLease(endpoint)
    finally:
        first.close()
    second = TransportLease(endpoint); second.close()


def test_v1_companion_refuses_other_real_nodes_without_opening_any_port():
    from uav_runtime.platform.deployment import SitlActions
    with pytest.raises(PlatformError, match="companion_profile_requires_uav02"):
        SitlActions("UAV-01", "not-read.json", "not-written.jsonl")


def test_ground_platform_facade_rejects_cross_origin_simple_post(monkeypatch):
    from uav_runtime.http import routes
    from uav_runtime.http.server import create_server
    class Gateway:
        def relay(self, *_a):
            calls.append(True)
            return 202, {"accepted": True}
    calls = []
    monkeypatch.setattr(routes, "PLATFORM_GATEWAY", Gateway())
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}/api/platform/tasks"
        for origin, content_type, expected in [("https://untrusted.example", "text/plain", 403),
                                               ("http://127.0.0.1:5178", "text/plain", 415),
                                               (None, "application/json", 202)]:
            headers = {"Content-Type": content_type}
            if origin: headers["Origin"] = origin
            request = Request(base, data=b"{}", headers=headers)
            try:
                with urlopen(request, timeout=2) as response: status = response.status
            except HTTPError as error:
                status = error.code
            assert status == expected
        assert calls == [True]
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_large_event_pages_are_bounded_and_all_sequences_replay(environment):
    from uav_runtime.platform.contract import canonical
    service, store, _, _ = environment
    service.submit(task())
    for index in range(10):
        store.update("t-1", stamp(1000), "test_diagnostic", data={"message": "x" * 18000, "index": index})
    store.update("t-1", stamp(1000), "test_oversized", data={"message": "x" * 70000})
    cursor, seen = 0, []
    while True:
        page = store.events(cursor)
        assert len(canonical(page).encode()) < 65536
        seen.extend(page["events"])
        cursor = page["next_seq"]
        if not page["has_more"]: break
    assert [e["seq"] for e in seen] == list(range(1, cursor + 1))
    assert seen[-1]["data"]["payload_omitted"] is True


def test_sitl_adapter_uses_bounded_stable_identifiers_and_existing_policy_route():
    from types import SimpleNamespace
    from uav_runtime.platform.deployment import SitlActions
    adapter = object.__new__(SitlActions)
    adapter.node_id = "UAV-02"
    seen = []
    def dispatch(method, path, *, body):
        seen.append((method, path, body))
        return 200, {"status": "succeeded", "result": "pass"}
    adapter.routes = SimpleNamespace(dispatch=dispatch)
    body = {**task(), "execution_id": "x" * 36}
    step = {"step_id": "s" * 100, "action": "hold_position", "params": {"hold_s": 3}}
    adapter.execute(body, step); adapter.execute(body, step)
    assert seen[0] == seen[1]
    assert seen[0][1] == "/api/actions/hold-position"
    assert seen[0][2]["command_source"] == "agent"
    assert len(seen[0][2]["request_id"]) < 128
