from __future__ import annotations

import hashlib
import http.client
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from uavswarm_llm_lab.contracts import parse_json
from uavswarm_llm_lab.local_model_client import ModelError
from uavswarm_llm_lab.preview_server import HEALTH_PATH, PREVIEW_PATH, make_preview_server
from uavswarm_llm_lab.scene_selection_preview import SOURCE_REF


ORIGIN = "http://127.0.0.1:5178"
CATALOG = parse_json((Path(__file__).resolve().parents[3] / SOURCE_REF).read_text(encoding="utf-8-sig"))
OBJECTIVE = "请登记已导出目录里，北侧首排东半幅比20米高2米的那栋楼。"


class FixtureModel:
    def __init__(self):
        self.calls = 0
        self.mode = "reply"
        self.started = threading.Event()
        self.release = threading.Event()

    def complete(self, *args, **kwargs):
        self.calls += 1
        if self.mode == "offline":
            raise ModelError("local inference failed") from ConnectionRefusedError("test engine")
        if self.mode == "timeout":
            raise ModelError("local inference failed") from TimeoutError("test engine")
        if self.mode == "invalid":
            return {"content": '{"choice":"1","execution_authorized":true}', "model": "test-only"}
        if self.mode == "hold":
            self.started.set()
            if not self.release.wait(4):
                raise TimeoutError("test did not release model")
        return {"content": '{"choice":"1"}', "model": "test-only"}


class SemanticPreviewServerTests(unittest.TestCase):
    def setUp(self):
        self.model = FixtureModel()
        self.server = make_preview_server(CATALOG, self.model, model_alias="test-only", port=0)
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.model.release.set)

    def request(self, method, path, body=None, **headers):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            conn.request(method, path, body, headers)
            response = conn.getresponse()
            content = response.read()
            return response.status, response.headers, json.loads(content) if content else None
        finally:
            conn.close()

    def post(self, request, path=PREVIEW_PATH, **headers):
        return self.request("POST", path, json.dumps(request).encode("utf-8"),
                            **{"Content-Type": "application/json", **headers})

    def test_console_preflight_and_health_do_not_run_inference(self):
        status, headers, _ = self.request("OPTIONS", PREVIEW_PATH,
                                          **{"Origin": ORIGIN, "Access-Control-Request-Method": "POST"})
        self.assertEqual(status, 204)
        self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertEqual(headers["Access-Control-Allow-Methods"], "POST")
        status, headers, health = self.request("GET", HEALTH_PATH, Origin=ORIGIN)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(health["model_status"], "not_checked")
        self.assertFalse(health["execution_authorized"])
        self.assertEqual(self.model.calls, 0)

    def test_submit_returns_live_wrapper_and_exact_non_executable_evidence(self):
        status, headers, result = self.post({"objective": OBJECTIVE}, Origin=ORIGIN)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertEqual(self.model.calls, 1)
        self.assertEqual(result["mode"], "live")
        self.assertIs(type(result["elapsed_ms"]), int)
        self.assertFalse(result["execution_authorized"])
        preview = result["preview"]
        self.assertEqual(preview["status"], "clarify")
        self.assertEqual(preview["bindings"], [])
        self.assertEqual(preview["reason_code"], "MODEL_CHOICE_REQUIRES_REVIEW")
        self.assertFalse(preview["execution_authorized"])
        raw_bytes = result["evidence_json"].encode("utf-8")
        self.assertEqual(preview["source"]["evidence_sha256"], hashlib.sha256(raw_bytes).hexdigest())
        self.assertEqual(json.loads(raw_bytes)["model_trace"]["model_raw_response"], '{"choice":"1"}')

    def test_only_console_origins_expected_host_route_and_schema_are_accepted(self):
        for status, headers, response in [
            self.post({"objective": OBJECTIVE}, Origin="http://untrusted.invalid"),
            self.post({"objective": OBJECTIVE}, Host="untrusted.invalid"),
        ]:
            self.assertEqual(status, 403)
            self.assertNotIn("Access-Control-Allow-Origin", headers)
            self.assertFalse(response["execution_authorized"])
        self.assertEqual(self.post({"objective": OBJECTIVE}, path="/api/plans/execute")[0], 404)
        self.assertEqual(self.post({"objective": OBJECTIVE, "scene_id": "made-up"})[0], 400)
        self.assertEqual(self.post({"objective": OBJECTIVE + " 再来一条"})[0], 422)
        self.assertEqual(self.post({"objective": "a" * 4096})[0], 413)
        self.assertEqual(self.model.calls, 0)

    def test_model_failure_is_not_replaced_by_recorded_data(self):
        for mode, expected, code in [
            ("offline", 503, "MODEL_UNAVAILABLE"), ("timeout", 504, "MODEL_TIMEOUT"),
            ("invalid", 502, "MODEL_RESPONSE_REJECTED"),
        ]:
            with self.subTest(mode=mode):
                self.model.mode = mode
                status, _, body = self.post({"objective": OBJECTIVE})
                self.assertEqual(status, expected)
                self.assertEqual(body["error"]["reason_code"], code)
                self.assertFalse(body["execution_authorized"])
                self.assertNotIn("preview", body)
                self.assertNotIn("evidence_json", body)

    def test_single_in_flight_inference_returns_busy_without_extra_model_calls(self):
        self.model.mode = "hold"
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.post, {"objective": OBJECTIVE})
            try:
                self.assertTrue(self.model.started.wait(2))
                status, _, result = self.post({"objective": OBJECTIVE})
                self.assertEqual((status, result["error"]["reason_code"]), (429, "PREVIEW_BUSY"))
                self.assertEqual(self.model.calls, 1)
            finally:
                self.model.release.set()
            self.assertEqual(first.result(timeout=5)[0], 200)
