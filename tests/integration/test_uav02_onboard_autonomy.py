"""Offline cross-boundary checks for the UAV-02 companion task contract.

These tests use the Runtime owner's fake execution seam. They never open a
MAVLink receiver or treat a fake completion as flight evidence.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from http.client import HTTPConnection, HTTPException
import json
import threading
import time

import pytest

from algorithm_lab.platform_candidate_lab.candidate import decide
from simulation.px4_gazebo.app_link_proxy import ApplicationLinkProxy, set_state
from uav_runtime.platform.contract import PlatformError, stamp
from uav_runtime.platform.service import PlatformService
from uav_runtime.platform.server import PlatformHttpServer
from uav_runtime.platform.store import TaskStore


def _task(now: float, *, task_id: str = "uav02-acceptance-001") -> dict:
    return {
        "contract_version": "1.0",
        "node_id": "UAV-02",
        "task_id": task_id,
        "task_version": 1,
        "request_id": f"request-{task_id}",
        "trace_id": f"trace-{task_id}",
        "authorization": {
            "operator_id": "operator-01",
            "expires_at": stamp(now + 600),
            "offline_policy": "continue_authorized",
            "max_altitude_m": 3,
            "max_hold_s": 10,
        },
        "steps": [
            {"step_id": "takeoff-1", "action": "takeoff", "params": {"altitude_m": 2}},
            {"step_id": "hold-1", "action": "hold_position", "params": {"hold_s": 2}},
            {"step_id": "land-1", "action": "land", "params": {}},
        ],
    }


def _fake_result() -> dict:
    return {"status": "succeeded", "result": "pass", "execution_mode": "fake",
            "flight_command_sent": False}


def test_repeated_request_reuses_task_and_conflicting_content_is_rejected(tmp_path):
    now = 1_800_000_000.0
    calls = []
    store = TaskStore(tmp_path / "platform")
    service = PlatformService(store, clock=lambda: now, monotonic=lambda: now,
                              execute=lambda task, step: calls.append(step["action"]) or _fake_result())
    try:
        service.heartbeat()
        body = _task(now)
        first, created = service.submit(body)
        replay, created_again = service.submit(deepcopy(body))
        assert created is True and created_again is False
        assert replay["execution_id"] == first["execution_id"]

        changed = deepcopy(body)
        changed["steps"][0]["params"]["altitude_m"] = 3
        with pytest.raises(PlatformError) as exc:
            service.submit(changed)
        assert exc.value.code == "idempotency_conflict"

        service.run_task(body["task_id"])
        assert calls == ["takeoff", "hold_position", "land"]
        assert store.task(body["task_id"])["status"] == "succeeded"
        assert service.submit(body)[1] is False
        assert calls == ["takeoff", "hold_position", "land"]
    finally:
        store.close()


def test_ground_link_loss_after_takeoff_continues_only_authorized_steps(tmp_path):
    now = 1_800_000_000.0
    monotonic = [100.0]
    calls = []
    store = TaskStore(tmp_path / "platform")

    def execute(task, step):
        calls.append((task["node_id"], step["action"]))
        if step["action"] == "takeoff":
            monotonic[0] += 4.0  # Ground heartbeat expires; local fake adapter remains available.
        return _fake_result()

    service = PlatformService(store, clock=lambda: now, monotonic=lambda: monotonic[0],
                              execute=execute)
    try:
        service.heartbeat()
        body = _task(now)
        service.submit(body)
        service.run_task(body["task_id"])
        assert service.link()["state"] == "lost"
        assert calls == [("UAV-02", "takeoff"), ("UAV-02", "hold_position"),
                         ("UAV-02", "land")]
        assert store.task(body["task_id"])["status"] == "succeeded"
        assert all(not outcome["result"]["flight_command_sent"]
                   for outcome in store.task(body["task_id"])["step_outcomes"])
    finally:
        store.close()


def test_link_loss_before_takeoff_never_calls_adapter(tmp_path):
    now = 1_800_000_000.0
    monotonic = [100.0]
    calls = []
    store = TaskStore(tmp_path / "platform")
    service = PlatformService(store, clock=lambda: now, monotonic=lambda: monotonic[0],
                              execute=lambda task, step: calls.append(step["action"]) or _fake_result())
    try:
        service.heartbeat()
        body = _task(now)
        service.submit(body)
        monotonic[0] += 4.0
        service.run_task(body["task_id"])
        assert calls == []
        assert store.task(body["task_id"])["status"] == "failed"
        assert "takeoff_requires_ground_link" in store.task(body["task_id"])["failure_reason"]
        with pytest.raises(PlatformError) as exc:
            service.submit(_task(now, task_id="uav02-new-after-loss"))
        assert exc.value.code == "ground_link_unavailable"
    finally:
        store.close()


def test_restart_retains_event_cursor_and_requires_reconciliation(tmp_path):
    now = 1_800_000_000.0
    directory = tmp_path / "platform"
    store = TaskStore(directory)
    service = PlatformService(store, clock=lambda: now, monotonic=lambda: now)
    service.heartbeat()
    body = _task(now)
    accepted, _ = service.submit(body)
    store.update(body["task_id"], stamp(now), "task_execution_started", status="executing")
    store.update(body["task_id"], stamp(now), "step_started", current_step="takeoff-1")
    before = store.events()
    store_id, boot_id = store.store_id, service.boot_id
    store.close()

    calls = []
    restored = TaskStore(directory)
    observation = {"source": "fake", "sample_timestamp": stamp(now + 1), "stale": True,
                   "armed": True, "landed_state": 2, "landed_fresh": False}
    restarted = PlatformService(restored, clock=lambda: now + 1, monotonic=lambda: now + 1,
                                observe=lambda: observation,
                                execute=lambda task, step: calls.append(step["action"]) or _fake_result())
    try:
        task = restored.task(body["task_id"])
        assert task["execution_id"] == accepted["execution_id"]
        assert task["status"] == "recovery_required"
        assert task["current_step"] == "takeoff-1"
        assert restored.store_id == store_id and restarted.boot_id != boot_id
        assert calls == []
        assert restarted.status()["safe_to_stop"] is False
        with pytest.raises(PlatformError) as exc:
            restarted.reconcile(body["task_id"], "operator-01", task["execution_id"])
        assert exc.value.code == "fresh_ground_reconciliation_required"
        assert restored.task(body["task_id"])["status"] == "recovery_required"
        observation.update(stale=False, armed=False, landed_state=1, landed_fresh=True)
        with pytest.raises(PlatformError) as exc:
            restarted.reconcile(body["task_id"], "operator-01", "wrong-execution-id")
        assert exc.value.code == "fresh_ground_reconciliation_required"
        reconciled = restarted.reconcile(body["task_id"], "operator-01", task["execution_id"])
        assert reconciled["status"] == "failed"
        assert reconciled["failure_reason"] == "operator_reconciled_after_uncertain_execution"
        assert restarted.status()["safe_to_stop"] is True
        assert calls == []
        after = restored.events(after=before["checkpoint_seq"])
        assert [event["event_type"] for event in after["events"]] == [
            "task_recovery_required", "task_reconciled"
        ]
        assert after["events"][0]["seq"] > before["checkpoint_seq"]
        assert restored.events(after=after["next_seq"])["events"] == []
    finally:
        restored.close()


def test_wrong_node_expired_authorization_and_oversized_hold_send_nothing(tmp_path):
    now = 1_800_000_000.0
    calls = []
    store = TaskStore(tmp_path / "platform")
    service = PlatformService(store, clock=lambda: now, monotonic=lambda: now,
                              execute=lambda task, step: calls.append(step["action"]) or _fake_result())
    try:
        service.heartbeat()
        wrong_node = _task(now)
        wrong_node["node_id"] = "UAV-01"
        expired = _task(now)
        expired["authorization"]["expires_at"] = stamp(now - 1)
        excessive_hold = _task(now)
        excessive_hold["steps"][1]["params"]["hold_s"] = 20
        for body, expected in ((wrong_node, "node_mismatch"),
                               (expired, "authorization_expired_or_too_long"),
                               (excessive_hold, "parameter_out_of_bounds")):
            with pytest.raises(PlatformError) as exc:
                service.submit(body)
            assert exc.value.code == expected
        assert store.active() is None
        assert calls == []
    finally:
        store.close()


def test_invalid_model_choice_cannot_expand_authorized_action_sequence(tmp_path):
    now = 1_800_000_000.0
    calls = []
    store = TaskStore(tmp_path / "platform")

    def candidate(_request):
        return 200, {"contract_version": "1.0", "status": "candidate",
                     "decision": "unapproved_goto", "execution_authorized": True,
                     "evidence": {}}

    service = PlatformService(store, clock=lambda: now, monotonic=lambda: now,
                              candidate=candidate,
                              execute=lambda task, step: calls.append(step["action"]) or _fake_result())
    try:
        service.heartbeat()
        body = _task(now)
        service.submit(body)
        service.run_task(body["task_id"])
        assert calls == ["takeoff", "hold_position", "land"]
        assert store.task(body["task_id"])["status"] == "succeeded"
        events = store.events()["events"]
        assert [event["event_type"] for event in events].count("model_unavailable") == 3
        assert all(event["data"]["fallback"] == "authorized_sequence"
                   for event in events if event["event_type"] == "model_unavailable")
    finally:
        store.close()


def test_runtime_candidate_request_matches_algorithm_wire_contract(tmp_path):
    now = 1_800_000_000.0
    calls = []
    store = TaskStore(tmp_path / "platform")

    class FixedLocalModel:
        model = "offline-test-model"

        @staticmethod
        def complete(_messages, _schema, *, timeout_s):
            assert timeout_s == 2
            return {"content": '{"option_id":"execute_authorized_step"}'}

    def candidate(request):
        reply = decide(request, FixedLocalModel(),
                       now=datetime.fromtimestamp(now, timezone.utc), allow_fake=True)
        return 200, reply

    service = PlatformService(store, clock=lambda: now, monotonic=time.monotonic,
                              candidate=candidate,
                              execute=lambda task, step: calls.append(step["action"]) or _fake_result())
    try:
        service.heartbeat()
        body = _task(now)
        service.submit(body)
        service.run_task(body["task_id"])
        assert calls == ["takeoff", "hold_position", "land"]
        assert store.task(body["task_id"])["status"] == "succeeded"
        events = store.events()["events"]
        candidates = [event for event in events if event["event_type"] == "model_candidate"]
        assert len(candidates) == 3
        assert all(event["data"]["response"]["execution_authorized"] is False
                   for event in candidates)
        assert not any(event["event_type"] == "model_unavailable" for event in events)
    finally:
        store.close()


def test_model_timeout_does_not_block_the_bounded_fallback(tmp_path):
    now = 1_800_000_000.0
    release = threading.Event()
    entered = threading.Event()
    calls = []
    store = TaskStore(tmp_path / "platform")

    def hanging_candidate(_request):
        entered.set()
        release.wait(timeout=10)
        return 200, {"status": "candidate", "decision": "abort_to_land"}

    service = PlatformService(store, clock=lambda: now, monotonic=time.monotonic,
                              candidate=hanging_candidate,
                              execute=lambda task, step: calls.append(step["action"]) or _fake_result())
    try:
        service.heartbeat()
        body = _task(now)
        service.submit(body)
        started = time.monotonic()
        service.run_task(body["task_id"])
        assert entered.is_set()
        assert time.monotonic() - started < 5
        assert calls == ["takeoff", "hold_position", "land"]
        assert store.task(body["task_id"])["status"] == "succeeded"
        unavailable = [event for event in store.events()["events"]
                       if event["event_type"] == "model_unavailable"]
        assert len(unavailable) == 3
        assert "model_deadline_exceeded" in unavailable[0]["data"]["reason"]
        assert all(event["data"]["fallback"] == "authorized_sequence"
                   for event in unavailable)
    finally:
        release.set()
        store.close()


def test_http_submit_is_durable_after_client_disconnect_and_requires_token(tmp_path):
    now = 1_800_000_000.0
    calls = []
    store = TaskStore(tmp_path / "platform")
    service = PlatformService(store, clock=lambda: now, monotonic=lambda: now,
                              execute=lambda task, step: calls.append(step["action"]) or _fake_result())
    token = "integration-token-" + "x" * 32
    server = PlatformHttpServer(("127.0.0.1", 0), service, token)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    def request(method, path, body=None, bearer=token):
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        headers = {"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"}
        connection.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                           headers=headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    try:
        body = _task(now)
        status, denial = request("POST", "/api/platform/tasks", body, bearer="invalid")
        assert status == 401 and denial["error"] == "authentication_required"
        assert store.active() is None
        assert request("POST", "/api/platform/link/heartbeat", {})[0] == 200
        status, accepted = request("POST", "/api/platform/tasks", body)
        assert status == 202 and accepted["task"]["task_id"] == body["task_id"]
        assert accepted["idempotent_replay"] is False
        assert request("POST", "/api/platform/tasks", body)[1]["idempotent_replay"] is True
        assert calls == []  # HTTP request completion is independent of execution.

        service.start()  # Client connections above have already closed.
        deadline = time.monotonic() + 2
        while store.task(body["task_id"])["status"] not in {"succeeded", "failed"}:
            assert time.monotonic() < deadline
            with store.changed:
                store.changed.wait(timeout=0.02)
        assert store.task(body["task_id"])["status"] == "succeeded"
        assert calls == ["takeoff", "hold_position", "land"]

        status, page = request("GET", "/api/platform/events?after_seq=0")
        assert status == 200 and page["events"]
        assert [event["seq"] for event in page["events"]] == sorted(
            {event["seq"] for event in page["events"]}
        )
        status, empty = request("GET", f"/api/platform/events?after_seq={page['next_seq']}")
        assert status == 200 and empty["events"] == []
        status, changed = request("GET", "/api/platform/events?after_seq=0&store_id=other-store")
        assert status == 409 and changed["error"] == "event_store_changed"
        status, ahead = request(
            "GET", f"/api/platform/events?after_seq={page['checkpoint_seq'] + 1}&store_id={store.store_id}"
        )
        assert status == 409 and ahead["error"] == "event_cursor_ahead"
    finally:
        service.stop.set()
        with store.changed:
            store.changed.notify_all()
        if service.worker:
            service.worker.join(timeout=2)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
        store.close()


def test_simulation_application_link_cut_preserves_onboard_task(tmp_path):
    now = 1_800_000_000.0
    monotonic = [100.0]
    calls = []
    takeoff_entered = threading.Event()
    release_takeoff = threading.Event()
    store = TaskStore(tmp_path / "platform")

    def execute(_task_body, step):
        calls.append(step["action"])
        if step["action"] == "takeoff":
            takeoff_entered.set()
            assert release_takeoff.wait(timeout=3)
        return _fake_result()

    service = PlatformService(store, clock=lambda: now, monotonic=lambda: monotonic[0],
                              execute=execute)
    token = "integration-token-" + "y" * 32
    server = PlatformHttpServer(("127.0.0.1", 0), service, token)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    def request(port, method, path, body=None):
        connection = HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request(method, path,
                               body=json.dumps(body).encode() if body is not None else None,
                               headers={"Authorization": f"Bearer {token}",
                                        "Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    async def scenario():
        state_path = tmp_path / "ground-link.json"
        set_state(state_path, run_id="offline-integration", mode="up")
        proxy = ApplicationLinkProxy(state_path=state_path, run_id="offline-integration",
                                     listen_port=0, target_port=server.server_port)
        await proxy.start()
        assert proxy.server is not None
        proxy_port = proxy.server.sockets[0].getsockname()[1]
        try:
            assert (await asyncio.to_thread(request, proxy_port, "POST",
                                            "/api/platform/link/heartbeat", {}))[0] == 200
            body = _task(now)
            status, accepted = await asyncio.to_thread(request, proxy_port, "POST",
                                                        "/api/platform/tasks", body)
            assert status == 202 and accepted["task"]["task_id"] == body["task_id"]
            service.start()
            assert await asyncio.to_thread(takeoff_entered.wait, 2)

            set_state(state_path, run_id="offline-integration", mode="down")
            monotonic[0] += 4.0
            release_takeoff.set()
            deadline = time.monotonic() + 2
            while store.task(body["task_id"])["status"] not in {"succeeded", "failed"}:
                assert time.monotonic() < deadline
                await asyncio.sleep(0.01)
            with pytest.raises((OSError, HTTPException)):
                await asyncio.to_thread(request, proxy_port, "GET", "/api/platform/status")
            direct_status, direct = await asyncio.to_thread(request, server.server_port,
                                                              "GET", "/api/platform/status")
            assert direct_status == 200 and direct["ground_link"]["state"] == "lost"
            assert calls == ["takeoff", "hold_position", "land"]
            assert store.task(body["task_id"])["status"] == "succeeded"

            set_state(state_path, run_id="offline-integration", mode="up")
            status, replay = await asyncio.to_thread(request, proxy_port, "POST",
                                                     "/api/platform/tasks", body)
            assert status == 200 and replay["idempotent_replay"] is True
            assert calls == ["takeoff", "hold_position", "land"]
            status, events = await asyncio.to_thread(request, proxy_port, "GET",
                f"/api/platform/events?after_seq=0&store_id={store.store_id}")
            assert status == 200 and events["events"]
        finally:
            release_takeoff.set()
            await proxy.close()

    try:
        asyncio.run(scenario())
    finally:
        service.stop.set()
        with store.changed:
            store.changed.notify_all()
        if service.worker:
            service.worker.join(timeout=2)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
        store.close()
