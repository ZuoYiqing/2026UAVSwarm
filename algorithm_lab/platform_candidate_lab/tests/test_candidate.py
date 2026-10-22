"""No model, simulator, vehicle, or external service is used by these tests."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from platform_candidate_lab.candidate import decide
from platform_candidate_lab.contracts import ContractError, parse_json
from platform_candidate_lab.local_model import LocalInferenceClient, ModelFailure
from platform_candidate_lab.server import make_handler


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 22, 12, 0, 1, tzinfo=timezone.utc)


def request_fixture() -> dict:
    return json.loads((ROOT / "fixtures" / "uav02_hold_request.json").read_text(encoding="utf-8"))


class FakeClient:
    model = "fixture-local-model"

    def __init__(self, content: str = '{"option_id":"execute_authorized_step"}',
                 failure: str | None = None):
        self.content = content
        self.failure = failure
        self.calls = 0

    def complete(self, messages, output_schema, *, timeout_s):
        self.calls += 1
        if self.failure:
            raise ModelFailure(self.failure)
        assert timeout_s == 2
        assert output_schema["properties"]["option_id"]["enum"] == [
            "execute_authorized_step", "abort_to_land"]
        return {"content": self.content, "model": self.model}


class CandidateTests(unittest.TestCase):
    def test_valid_model_only_selects_authorized_option(self):
        request = request_fixture()
        result = decide(request, FakeClient(), now=NOW, allow_fake=True)
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(result["decision"], "execute_authorized_step")
        self.assertEqual(result["candidate"], {"option_id": "execute_authorized_step"})
        self.assertEqual(result["request_id"], request["request_id"])
        self.assertEqual(result["execution_id"], request["execution_id"])
        self.assertEqual(result["evidence"]["source_timestamp"],
                         request["observation"]["sample_timestamp"])
        self.assertEqual(len(result["evidence"]["input_sha256"]), 64)
        self.assertEqual(len(result["evidence"]["raw_output_sha256"]), 64)
        self.assertFalse(result["execution_authorized"])
        self.assertNotIn("params", result["candidate"])

    def test_model_abort_is_only_a_candidate(self):
        client = FakeClient('{"option_id":"abort_to_land"}')
        result = decide(request_fixture(), client, now=NOW, allow_fake=True)
        self.assertEqual((result["status"], result["decision"]), ("candidate", "abort_to_land"))
        self.assertFalse(result["execution_authorized"])

    def test_lost_link_prevents_new_takeoff_before_model_call(self):
        request = request_fixture()
        request["next_step"] = {"step_id": "step-hold", "action": "takeoff",
                                "params": {"altitude_m": 3.0}}
        request["allowed_options"][0] = {
            "option_id": "execute_authorized_step", "action_type": "takeoff",
            "params": {"altitude_m": 3.0}}
        client = FakeClient()
        result = decide(request, client, now=NOW, allow_fake=True)
        self.assertEqual(result["status"], "no_candidate")
        self.assertEqual(result["evidence"]["reason"], "OFFLINE_TAKEOFF_NOT_ALLOWED")
        self.assertEqual(client.calls, 0)

    def test_expired_stale_future_and_fake_are_no_candidate(self):
        cases = [
            ("expired", lambda r: r["authorization"].update(expires_at="2026-10-22T12:00:00Z")),
            ("stale", lambda r: r["observation"].update(stale=True)),
            ("old", lambda r: r["observation"].update(sample_timestamp="2026-10-22T11:59:55Z")),
            ("future", lambda r: r["observation"].update(sample_timestamp="2026-10-22T12:00:02Z")),
        ]
        for name, mutate in cases:
            with self.subTest(name=name):
                request = request_fixture()
                mutate(request)
                client = FakeClient()
                result = decide(request, client, now=NOW, allow_fake=True)
                self.assertEqual(result["status"], "no_candidate")
                self.assertEqual(result["failure_reason_code"], "INPUT_INVALID")
                self.assertEqual(client.calls, 0)
        client = FakeClient()
        result = decide(request_fixture(), client, now=NOW)
        self.assertEqual(result["evidence"]["reason"], "FAKE_SOURCE_NOT_ENABLED")
        self.assertEqual(client.calls, 0)

    def test_timeout_unavailable_and_invalid_model_output_fail_closed(self):
        cases = [
            (FakeClient(failure="MODEL_TIMEOUT"), "MODEL_TIMEOUT", None),
            (FakeClient(failure="MODEL_UNAVAILABLE"), "MODEL_UNAVAILABLE", None),
            (FakeClient('{"option_id":"takeoff"}'), "MODEL_OUTPUT_INVALID", "MODEL_REPLY_INVALID"),
            (FakeClient('{"option_id":"execute_authorized_step","params":{"altitude_m":99}}'),
             "MODEL_OUTPUT_INVALID", "MODEL_REPLY_INVALID"),
            (FakeClient('{"option_id":"abort_to_land","option_id":"execute_authorized_step"}'),
             "MODEL_OUTPUT_INVALID", "MODEL_REPLY_INVALID"),
            (FakeClient('{"option_id":"execute_authorized_step"} trailing'),
             "MODEL_OUTPUT_INVALID", "MODEL_REPLY_INVALID"),
        ]
        for client, code, detail in cases:
            with self.subTest(content=client.content, failure=client.failure):
                result = decide(request_fixture(), client, now=NOW, allow_fake=True)
                self.assertEqual(result["status"], "no_candidate")
                self.assertIsNone(result["decision"])
                self.assertIsNone(result["candidate"])
                self.assertEqual(result["failure_reason_code"], code)
                self.assertFalse(result["execution_authorized"])
                if detail:
                    self.assertEqual(result["evidence"]["reason"], detail)
                    self.assertEqual(len(result["evidence"]["raw_output_sha256"]), 64)
                else:
                    self.assertIsNone(result["evidence"]["raw_output_sha256"])

    def test_input_cannot_change_step_authorization_or_source(self):
        base = request_fixture()
        cases = [
            lambda r: r["allowed_options"][0]["params"].update(hold_s=9),
            lambda r: r["authorization"].update(max_hold_s=2),
            lambda r: r["next_step"].update(action="goto"),
            lambda r: r["observation"].update(source="gazebo_ground_truth"),
            lambda r: r["observation"].update(scene_position={"north_m": 0}),
            lambda r: r["observation"]["local_position"].update(z_m=float("nan")),
            lambda r: r.update(snapshot_id="different-request"),
            lambda r: r["allowed_options"][1].update(action_type="takeoff"),
        ]
        for mutate in cases:
            with self.subTest(mutate=mutate):
                request = copy.deepcopy(base)
                mutate(request)
                with self.assertRaises(ContractError):
                    decide(request, FakeClient(), now=NOW, allow_fake=True)

    def test_strict_json_rejects_duplicate_keys_and_nonfinite(self):
        for text in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}'):
            with self.subTest(text=text), self.assertRaises(ContractError):
                parse_json(text)

    def test_runtime_telemetry_shape_is_accepted(self):
        request = request_fixture()
        request["authorization"]["expires_at"] = "2026-10-22T12:05:00+00:00"
        request["observation"]["sample_timestamp"] = "2026-10-22T12:00:00+00:00"
        request["observation"]["local_position"] = {
            "x_m": 0.0, "y_m": 0.0, "z_down_m": -3.0, "altitude_m": 3.0,
            "vx_m_s": 0.0, "vy_m_s": 0.0, "vz_m_s": 0.0,
        }
        request["ground_link"] = {
            "state": "healthy", "last_received_at": "2026-10-22T12:00:00+00:00",
            "age_ms": 1000,
        }
        result = decide(request, FakeClient(), now=NOW, allow_fake=True)
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(result["evidence"]["source_timestamp"],
                         "2026-10-22T12:00:00+00:00")

    def test_runtime_fake_observation_shape_is_accepted_only_with_opt_in(self):
        request = request_fixture()
        request["observation"] = {
            "source": "fake", "sample_timestamp": "2026-10-22T12:00:00+00:00",
            "stale": False, "local_position": {}, "armed": False,
            "landed_state": 1, "landed_fresh": True,
        }
        client = FakeClient()
        self.assertEqual(decide(request, client, now=NOW)["status"], "no_candidate")
        self.assertEqual(client.calls, 0)
        self.assertEqual(decide(request, client, now=NOW, allow_fake=True)["status"],
                         "candidate")

    def test_non_utc_timestamps_are_rejected(self):
        request = request_fixture()
        request["observation"]["sample_timestamp"] = "2026-10-22T20:00:00+08:00"
        with self.assertRaises(ContractError):
            decide(request, FakeClient(), now=NOW, allow_fake=True)

    def test_input_hash_matches_runtime_serialization_with_unicode_identity(self):
        request = request_fixture()
        request["authorization"]["operator_id"] = "操作员-01"
        expected = hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":"),
                       allow_nan=False).encode("utf-8")).hexdigest()
        result = decide(request, FakeClient(), now=NOW, allow_fake=True)
        self.assertEqual(result["evidence"]["input_sha256"], expected)

    def test_loopback_model_endpoint_refuses_remote_and_credentials(self):
        for url in ("http://example.com:18080/v1/chat/completions",
                    "http://user:pass@127.0.0.1:18080/v1/chat/completions",
                    "http://127.0.0.1:18080/other"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                LocalInferenceClient(url, "fixture")

    def test_http_candidate_endpoint_returns_structured_result(self):
        request = request_fixture()
        current = datetime.now(timezone.utc)
        request["observation"]["sample_timestamp"] = current.isoformat().replace("+00:00", "Z")
        request["authorization"]["expires_at"] = (current + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        with HTTPServer(("127.0.0.1", 0), make_handler(FakeClient(), allow_fake=True)) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                payload = json.dumps(request).encode("utf-8")
                req = Request(f"http://127.0.0.1:{server.server_port}/candidate",
                              data=payload, headers={"Content-Type": "application/json"})
                with urlopen(req, timeout=3) as response:
                    result = json.loads(response.read())
                self.assertEqual(result["status"], "candidate")
                self.assertEqual(result["request_id"], request["request_id"])
            finally:
                server.shutdown()
                worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
