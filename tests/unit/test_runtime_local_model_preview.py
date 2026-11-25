from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Event, Thread

import pytest

from uav_runtime.http import local_model_preview as model
from uav_runtime.http import routes, server


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
def stub_model(monkeypatch):
    state = {"calls": [], "status": 200, "finish": "stop", "alias": model.MODEL_ALIAS, "candidate": None}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            user_message = json.loads(data["messages"][1]["content"])
            state["calls"].append((self.path, data, user_message))
            index = next(e["编号"] for e in user_message["目录"] if e["名称"] == "西北区域")
            candidate = state["candidate"] or {"t": [index], "r": [], "x": [], "only": False}
            body = json.dumps({"model": state["alias"], "choices": [{
                "finish_reason": state["finish"], "message": {"content": json.dumps(candidate)},
            }]}).encode()
            self.send_response(state["status"])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Handler)) as port:
        monkeypatch.setattr(model, "MODEL_PORT", port)
        yield state


def test_existing_http_route_adopts_a_valid_candidate(stub_model):
    with serving(server.create_server(port=0, preview_model=model.LocalPreviewModel())) as port:
        status, body = post(port, model.PREVIEW_PATH, {"objective": OBJECTIVE}, Origin=ORIGIN)
    assert status == 200
    assert body["intent_source"] == "local_model"
    assert body["plan_source"] == "template"
    assert body["fallback_reason"] is None
    assert body["execution_authorized"] is False
    resolution = body["intent_resolution"]
    assert resolution["reason_code"] == "LOCAL_MODEL_CONFIRMED_INTENT"
    assert resolution["bindings"]["preview_only_targets"] == [{"entity_id": "demo-area-001", "evidence": "西北区域"}]
    assert body["plan"]["preview_binding"]["steps_are_outline"] is True
    [(path, wire, message)] = stub_model["calls"]
    assert path == "/v1/chat/completions" and wire["model"] == model.MODEL_ALIAS and wire["stream"] is False
    assert set(message) == {"原话", "目录"} and message["原话"] == OBJECTIVE
    assert "demo-area-001" not in wire["messages"][1]["content"]


@pytest.mark.parametrize(("overrides", "reason"), [
    ({"status": 503}, "model_unavailable"),
    ({"finish": "length"}, "model_low_confidence"),
    ({"alias": "unexpected"}, "model_low_confidence"),
    ({"candidate": {"t": [2], "r": [], "x": [], "only": False}}, "model_low_confidence"),
    ({"candidate": {"t": [999], "r": [], "x": [], "only": False}}, "model_low_confidence"),
    ({"candidate": {"t": [True], "r": [], "x": [], "only": False}}, "model_low_confidence"),
    ({"candidate": {"t": [], "r": [], "x": [], "only": True}}, "model_low_confidence"),
])
def test_model_failures_retain_authoritative_rule_result(stub_model, overrides, reason):
    stub_model.update(overrides)
    approved = routes.plan_mission({"objective": OBJECTIVE})
    body = routes.plan_mission({"objective": OBJECTIVE}, preview_model=model.LocalPreviewModel())
    assert body["intent_source"] == "rules" and body["fallback_reason"] == reason
    assert body["execution_authorized"] is False
    assert body["intent_resolution"] == approved["intent_resolution"]
    assert len(stub_model["calls"]) == 1


@pytest.mark.parametrize(("objective", "reason"), [
    ("把参考点列为目标。", "TARGET_AMBIGUOUS"),
    ("巡检西南和东南。", "CONFLICTING_TARGETS"),
    ("巡检西北区域和中央建筑。", "TARGET_REFERENCE_ONLY"),
])
def test_rule_safety_veto_never_calls_model(stub_model, objective, reason):
    body = routes.plan_mission({"objective": objective}, preview_model=model.LocalPreviewModel())
    assert body["intent_resolution"]["reason_code"] == reason
    assert body["intent_source"] == "rules" and body["fallback_reason"] is None
    assert body["plan"] is None and body["execution_authorized"] is False
    assert stub_model["calls"] == []


def test_default_and_explicit_template_do_not_call_model(stub_model):
    with serving(server.create_server(port=0)) as port:
        _, body = post(port, model.PREVIEW_PATH, {"objective": OBJECTIVE})
        assert body["intent_source"] == "rules" and body["fallback_reason"] is None
    body = routes.plan_mission({"objective": OBJECTIVE, "mission_type": "inspection_snapshot"},
                               preview_model=model.LocalPreviewModel())
    assert body["intent_source"] == "explicit" and body["fallback_reason"] is None
    assert stub_model["calls"] == []


def test_profile_rejects_execution_and_external_origin_before_dispatch(monkeypatch, stub_model):
    def fail(*_, **__):
        pytest.fail("read-only demo dispatched a disallowed request")

    monkeypatch.setattr(server, "dispatch", fail)
    with serving(server.create_server(port=0, preview_model=model.LocalPreviewModel())) as port:
        for path in ("/api/plans/execute", "/api/actions/takeoff", "/api/simulation/evidence"):
            code, body = post(port, path)
            assert code == 403 and body["error"] == "local_model_preview_only"
        code, _ = post(port, model.PREVIEW_PATH, Origin="http://example.invalid")
        assert code == 403
        code, body = post(port, model.PREVIEW_PATH, {"objective": OBJECTIVE, "dry_run": False})
        assert code == 400 and body["execution_authorized"] is False
    assert stub_model["calls"] == []
    with pytest.raises(ValueError, match="loopback"):
        server.create_server("0.0.0.0", 0, preview_model=model.LocalPreviewModel())


def test_timeout_does_not_queue_a_second_live_model_request(monkeypatch):
    started, unblock = Event(), Event()

    def slow(_):
        started.set()
        unblock.wait(2)
        raise TimeoutError

    monkeypatch.setattr(model, "_request_candidate", slow)
    monkeypatch.setattr(model, "MODEL_TIMEOUT_SECONDS", 0.02)
    selector = model.LocalPreviewModel()
    try:
        timed_out = routes.plan_mission({"objective": OBJECTIVE}, preview_model=selector)
        assert started.wait(timeout=1) and selector._slot.locked()
        busy = routes.plan_mission({"objective": OBJECTIVE}, preview_model=selector)
        for result in (timed_out, busy):
            assert result["intent_source"] == "rules" and result["fallback_reason"] == "model_unavailable"
    finally:
        unblock.set()
