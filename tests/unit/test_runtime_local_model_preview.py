from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from uav_runtime.http import local_model_preview as model
from uav_runtime.http import routes, server
from uav_runtime.http.model_preview_config import MODEL_ALIAS, ModelPreviewConfig


OBJECTIVE = "巡检西北区域。"
ORIGIN = "http://127.0.0.1:5178"


@contextmanager
def serving(httpd):
    with httpd:
        thread = Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        try:
            yield httpd.server_port
        finally:
            httpd.shutdown()
            thread.join(timeout=2)


def post(port, path, payload=None, **headers):
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(
            "POST", path, json.dumps(payload).encode() if payload is not None else None,
            {"Content-Type": "application/json", **headers},
        )
        with connection.getresponse() as response:
            return response.status, json.load(response)
    finally:
        connection.close()


@pytest.fixture
def stub_model():
    state = {"calls": [], "status": 200, "finish": "stop", "alias": MODEL_ALIAS, "candidate": None, "scripted": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            user_message = json.loads(data["messages"][1]["content"])
            state["calls"].append((self.path, data, user_message))
            attempt = {**state, **(state["scripted"].pop(0) if state["scripted"] else {})}
            index = next(e["编号"] for e in user_message["目录"] if e["名称"] == "西北区域")
            candidate = attempt["candidate"]
            if candidate is None:
                candidate = {"t": [index], "r": [], "x": [], "only": False}
            body = json.dumps({"model": attempt["alias"], "choices": [{
                "finish_reason": attempt["finish"],
                "message": {"content": attempt.get("raw_text", json.dumps(candidate)),
                            "reasoning_content": "hidden chain is never sent"},
            }]}).encode()
            self.send_response(attempt["status"])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Handler)) as port:
        state["port"] = port
        state["selector"] = model.LocalPreviewModel(ModelPreviewConfig(port=port))
        yield state


def test_existing_http_route_adopts_a_valid_candidate(stub_model):
    with serving(server.create_server(port=0, preview_model=stub_model["selector"])) as port:
        status, body = post(port, model.PREVIEW_PATH, {"objective": OBJECTIVE}, Origin=ORIGIN)
    assert status == 200
    assert body["intent_source"] == "local_model"
    assert body["plan_source"] == "template"
    assert body["fallback_reason"] is None
    assert body["execution_authorized"] is False
    resolution = body["intent_resolution"]
    assert resolution["reason_code"] == "LOCAL_MODEL_SELECTED_INTENT"
    assert resolution["bindings"]["preview_only_targets"] == [{"entity_id": "demo-area-001", "evidence": "西北区域"}]
    assert body["plan"]["preview_binding"]["steps_are_outline"] is True
    [(path, wire, message)] = stub_model["calls"]
    assert path == "/v1/chat/completions" and wire["model"] == MODEL_ALIAS and wire["stream"] is False
    assert set(message) == {"原话", "目录"} and message["原话"] == OBJECTIVE
    assert "demo-area-001" not in wire["messages"][1]["content"]
    diagnostic = body["model_diagnostics"]
    assert diagnostic["adopted"] is True and diagnostic["not_adopted_reason"] is None
    assert json.loads(diagnostic["attempts"][0]["raw_text"])["t"] == [5]
    assert "hidden chain" not in json.dumps(diagnostic)
    assert "model_diagnostics" not in routes.RUNTIME_STATE_STORE.agent_status()["latest_plan"]


def test_valid_model_decision_can_replace_rule_target_roles_and_scope(stub_model):
    stub_model["candidate"] = {"t": [2], "r": [3], "x": [3], "only": True}
    rules_only = routes.plan_mission({"objective": OBJECTIVE})["intent_resolution"]["bindings"]
    with serving(server.create_server(port=0, preview_model=stub_model["selector"])) as port:
        status, body = post(port, model.PREVIEW_PATH, {"objective": OBJECTIVE})
    assert status == 200 and body["intent_source"] == "local_model"
    assert body["fallback_reason"] is None and body["execution_authorized"] is False
    binding = body["plan"]["preview_binding"]["bindings"]
    assert rules_only["preview_only_targets"] == [{"entity_id": "demo-area-001", "evidence": "西北区域"}]
    assert binding["targets"] == [{"entity_id": "target-001", "evidence": ""}]
    assert not binding["preview_only_targets"]
    assert binding["reference_only"] == binding["excluded_targets"] == [{"entity_id": "demo-anchor-001", "evidence": ""}]
    assert binding["only_listed_targets"] is True and len(stub_model["calls"]) == 1


def test_model_can_change_order_but_cannot_forge_utterance_order_or_evidence(stub_model):
    objective = "先核对西北区，再核对东北绿色圆盘。"
    rule = routes.resolve_preview_intent(objective, scene_id=routes.VEHICLE_REGISTRY.scene_id,
                                        scene=routes.VEHICLE_REGISTRY.scene)
    assert rule.parameters.target_order_basis == "explicit_sequence"
    stub_model["candidate"] = {"t": [2, 5], "r": [], "x": [], "only": False}
    outcome = stub_model["selector"].select(objective, rule)
    assert outcome.resolution is not None
    decided = outcome.resolution.parameters
    assert [(b.entity_id, b.evidence) for b in decided.targets] == [
        ("target-001", "东北绿色圆盘"), ("demo-area-001", "西北区"),
    ]
    assert decided.target_order_basis is None


@pytest.mark.parametrize(("overrides", "reason", "detail", "count"), [
    ({"status": 503}, "model_unavailable", "MODEL_UNAVAILABLE", 1),
    ({"finish": "length"}, "model_invalid_output", "MODEL_RESPONSE_INCOMPLETE", 2),
    ({"alias": "unexpected"}, "model_invalid_output", "MODEL_ID_MISMATCH", 2),
    ({"raw_text": "not valid JSON"}, "model_invalid_output", "MODEL_JSON_INVALID", 2),
    ({"raw_text": '{"t":[5],"t":[2],"r":[],"x":[],"only":false}'},
     "model_invalid_output", "MODEL_JSON_INVALID", 2),
    ({"candidate": {"t": [999], "r": [], "x": [], "only": False}},
     "model_invalid_output", "MODEL_INDEX_INVALID", 2),
    ({"candidate": {"t": [True], "r": [], "x": [], "only": False}},
     "model_invalid_output", "MODEL_INDEX_INVALID", 2),
    ({"candidate": {"t": [5], "r": [], "x": [], "only": 1}},
     "model_invalid_output", "MODEL_FIELDS_INVALID", 2),
    ({"candidate": {"t": [1], "r": [], "x": [], "only": False}},
     "model_invalid_output", "TARGET_REFERENCE_ONLY", 2),
    ({"candidate": {"t": [5, 5], "r": [], "x": [], "only": False}},
     "model_invalid_output", "MODEL_DUPLICATE_SELECTION", 2),
    ({"candidate": {"t": [6, 7], "r": [], "x": [], "only": False}},
     "model_invalid_output", "CONFLICTING_TARGETS", 2),
    ({"candidate": {"t": [5], "r": [], "x": [5], "only": False}},
     "model_invalid_output", "MODEL_ROLE_CONFLICT", 2),
    ({"candidate": {"t": [], "r": [], "x": [], "only": True}},
     "model_abstained", "MODEL_ABSTAINED", 1),
])
def test_model_failures_retain_rules_and_diagnose_rejected_text(stub_model, overrides, reason, detail, count):
    stub_model.update(overrides)
    approved = routes.plan_mission({"objective": OBJECTIVE})
    body = routes.plan_mission({"objective": OBJECTIVE}, preview_model=stub_model["selector"])
    assert body["intent_source"] == "rules" and body["fallback_reason"] == reason
    assert body["execution_authorized"] is False
    assert body["intent_resolution"] == approved["intent_resolution"]
    assert len(stub_model["calls"]) == count
    diagnostic = body["model_diagnostics"]
    assert diagnostic["adopted"] is False and diagnostic["not_adopted_reason"] == detail
    assert len(diagnostic["attempts"]) == count
    for attempt in diagnostic["attempts"]:
        assert attempt["not_adopted_reason"] == detail and attempt["adopted"] is False
        if "raw_text" in overrides:
            assert attempt["raw_text"] == overrides["raw_text"]
        elif "candidate" in overrides:
            assert json.loads(attempt["raw_text"]) == overrides["candidate"]


def test_invalid_reply_retries_once_with_new_sampling_and_can_adopt(stub_model):
    first, second = '{"t":[999],"r":[],"x":[],"only":false}', '{"t":[2],"r":[],"x":[],"only":false}'
    stub_model["scripted"] = [{"raw_text": first}, {"raw_text": second}]
    body = routes.plan_mission({"objective": OBJECTIVE}, preview_model=stub_model["selector"])
    assert body["intent_source"] == "local_model" and body["fallback_reason"] is None
    assert body["intent_resolution"]["bindings"]["targets"][0]["entity_id"] == "target-001"
    assert [(wire["seed"], wire["temperature"]) for _, wire, _ in stub_model["calls"]] == [(11, 0), (29, 0.2)]
    attempts = body["model_diagnostics"]["attempts"]
    assert [(a["raw_text"], a["adopted"], a["not_adopted_reason"]) for a in attempts] == [
        (first, False, "MODEL_INDEX_INVALID"), (second, True, None),
    ]


def test_model_cannot_turn_an_explicit_exclusion_into_a_target(stub_model):
    stub_model["candidate"] = {"t": [2], "r": [], "x": [], "only": False}
    body = routes.plan_mission({"objective": "别核对东北视觉标记；巡检西北区域。"},
                               preview_model=stub_model["selector"])
    assert body["intent_source"] == "rules" and body["fallback_reason"] == "model_invalid_output"
    assert body["model_diagnostics"]["not_adopted_reason"] == "MODEL_ROLE_CONFLICT"


@pytest.mark.parametrize("raw", [
    model._PROMPT, r"C:\Private Files\model.gguf", "/home/hidden/model.gguf",
    "a synthetic authorization header: Bearer DEMO_TOKEN",
    "a synthetic service credential: " + "s" * 32,
])
def test_diagnostic_redacts_sensitive_model_content(stub_model, raw):
    stub_model["raw_text"] = raw
    configured = model.LocalPreviewModel(ModelPreviewConfig(port=stub_model["port"], token="s" * 32))
    body = routes.plan_mission({"objective": OBJECTIVE}, preview_model=configured)
    assert body["fallback_reason"] == "model_invalid_output"
    for attempt in body["model_diagnostics"]["attempts"]:
        assert attempt["raw_text"] == "[redacted]" and attempt["redacted"] is True
    assert raw not in json.dumps(body["model_diagnostics"], ensure_ascii=False)


def test_nonsecret_model_diagnostic_is_length_bounded(stub_model):
    stub_model["raw_text"] = "@" * (model.MAX_DIAGNOSTIC_CHARS + 10)
    body = routes.plan_mission({"objective": OBJECTIVE}, preview_model=stub_model["selector"])
    for attempt in body["model_diagnostics"]["attempts"]:
        assert attempt["raw_text"] == "@" * model.MAX_DIAGNOSTIC_CHARS
        assert attempt["truncated"] is True and attempt["redacted"] is False


@pytest.mark.parametrize(("objective", "reason"), [
    ("把参考点列为目标。", "TARGET_AMBIGUOUS"),
    ("巡检西南和东南。", "CONFLICTING_TARGETS"),
    ("巡检西北区域和中央建筑。", "TARGET_REFERENCE_ONLY"),
    ("巡检东侧充电棚。", "TARGET_NOT_IN_CATALOG"),
    ("紧急停止！", "GUARDED_TEMPLATE"),
    ("只查状态。", "INTENT_BOUND"),
    ("预览起降验证。", "INTENT_BOUND"),
])
def test_rule_safety_veto_never_calls_model(stub_model, objective, reason):
    original = routes.plan_mission({"objective": objective})
    body = routes.plan_mission({"objective": objective}, preview_model=stub_model["selector"])
    assert body["intent_resolution"]["reason_code"] == reason
    assert body["intent_source"] == "rules" and body["fallback_reason"] is None
    assert body["plan_source"] == original["plan_source"] and body["execution_authorized"] is False
    assert "model_diagnostics" not in body and stub_model["calls"] == []


def test_default_and_explicit_template_do_not_call_model(stub_model):
    with serving(server.create_server(port=0)) as port:
        _, body = post(port, model.PREVIEW_PATH, {"objective": OBJECTIVE})
        assert body["intent_source"] == "rules" and body["fallback_reason"] is None
        assert "model_diagnostics" not in body
    body = routes.plan_mission({"objective": OBJECTIVE, "mission_type": "inspection_snapshot"},
                               preview_model=stub_model["selector"])
    assert body["intent_source"] == "explicit" and body["fallback_reason"] is None
    assert stub_model["calls"] == []


def test_profile_rejects_execution_and_external_origin_before_dispatch(monkeypatch, stub_model):
    def fail(*_, **__):
        pytest.fail("read-only demo dispatched a disallowed request")

    monkeypatch.setattr(server, "dispatch", fail)
    with serving(server.create_server(port=0, preview_model=stub_model["selector"], preview_only=True)) as port:
        for path in ("/api/plans/execute", "/api/actions/takeoff", "/api/simulation/evidence"):
            code, body = post(port, path)
            assert code == 403 and body["error"] == "local_model_preview_only"
        code, _ = post(port, model.PREVIEW_PATH, Origin="http://example.invalid")
        assert code == 403
        code, body = post(port, model.PREVIEW_PATH, {"objective": OBJECTIVE, "dry_run": False})
        assert code == 400 and body["execution_authorized"] is False
    assert stub_model["calls"] == []
    with pytest.raises(ValueError, match="loopback"):
        server.create_server("0.0.0.0", 0, preview_model=stub_model["selector"])


def test_model_does_not_disable_normal_snapshot_routes(stub_model):
    with serving(server.create_server(port=0, preview_model=stub_model["selector"])) as port:
        connection = HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request("GET", "/api/vehicle-snapshot")
            with connection.getresponse() as response:
                assert response.status == 200
                assert json.load(response)["vehicles"]
        finally:
            connection.close()
        code, reply = post(port, model.PREVIEW_PATH, {"objective": OBJECTIVE}, Origin=ORIGIN)
        assert code == 200 and reply["intent_source"] == "local_model"
        assert reply["execution_authorized"] is False


def test_normal_cli_can_start_telemetry_and_the_model_together(monkeypatch):
    events = []
    monkeypatch.setenv("UAV_RUNTIME_LOCAL_MODEL_ENABLED", "1")
    monkeypatch.setenv("UAV_RUNTIME_TELEMETRY_ENABLED", "true")
    monkeypatch.setenv("UAV_RUNTIME_LOCAL_MODEL_TIMEOUT_S", "18")
    monkeypatch.delenv("UAV_RUNTIME_LOCAL_MODEL_URL", raising=False)
    monkeypatch.delenv("UAV_RUNTIME_LOCAL_MODEL_TOKEN_FILE", raising=False)
    monkeypatch.setattr(routes, "VEHICLE_REGISTRY", SimpleNamespace(
        list_vehicles=lambda: (),
        start_all=lambda: events.append("telemetry_start"),
        stop_all=lambda: events.append("telemetry_stop"),
    ))
    monkeypatch.setattr(server, "configure_demo", lambda: None)

    def create(**kwargs):
        assert kwargs["preview_only"] is False and isinstance(kwargs["preview_model"], model.LocalPreviewModel)
        return SimpleNamespace(serve_forever=lambda: events.append("serve"),
                               server_close=lambda: events.append("close"))

    monkeypatch.setattr(server, "create_server", create)
    assert server.main([]) == 0
    assert events == ["telemetry_start", "serve", "telemetry_stop", "close"]


def test_timeout_does_not_queue_a_second_live_model_request(monkeypatch):
    started, unblock = Event(), Event()

    def slow(_, config, **kwargs):
        assert config.timeout_s == 0.15
        assert 0 < kwargs["timeout_s"] <= config.timeout_s
        started.set()
        unblock.wait(2)
        raise TimeoutError

    monkeypatch.setattr(model, "_request_candidate", slow)
    selector = model.LocalPreviewModel(ModelPreviewConfig(timeout_s=0.15))
    try:
        timed_out = routes.plan_mission({"objective": OBJECTIVE}, preview_model=selector)
        assert started.wait(timeout=1) and selector._slot.locked()
        busy = routes.plan_mission({"objective": OBJECTIVE}, preview_model=selector)
        for result in (timed_out, busy):
            assert result["intent_source"] == "rules" and result["fallback_reason"] == "model_unavailable"
    finally:
        unblock.set()


def test_invalid_retry_uses_the_remaining_shared_budget(monkeypatch):
    clock = [100.0]
    calls = []

    def fake_transport(_, __, *, seed, temperature, timeout_s):
        calls.append((seed, temperature, timeout_s))
        clock[0] += 3.0
        return "not-json" if seed == 11 else '{"t":[2],"r":[],"x":[],"only":false}'

    monkeypatch.setattr(model, "monotonic", lambda: clock[0])
    monkeypatch.setattr(model, "_request_candidate", fake_transport)
    selector = model.LocalPreviewModel(ModelPreviewConfig(timeout_s=18))
    response = routes.plan_mission({"objective": OBJECTIVE}, preview_model=selector)
    assert calls == [(11, 0.0, 18.0), (29, 0.2, 15.0)]
    assert response["intent_source"] == "local_model" and response["execution_authorized"] is False
