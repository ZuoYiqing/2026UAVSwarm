"""No network or model weights required; server responses are test fixtures."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from jsonschema import Draft202012Validator
from uavswarm_llm_lab.benchmark import cases, case_context, run_model_benchmark, run_scaffold
from uavswarm_llm_lab.contracts import ContractError, canonical_json, digest, parse_json, schema
from uavswarm_llm_lab.local_model_client import LocalModelClient, ModelError, _NoRedirect
from uavswarm_llm_lab.mission_planner import evaluate_raw, plan_with_client, reference_proposal
from uavswarm_llm_lab.semantic_validator import context_errors, validate_proposal


def context():
    return case_context(cases()[0])


class LabTest(unittest.TestCase):
    def test_schema_definitions(self):
        for kind in ("context", "proposal"):
            Draft202012Validator.check_schema(schema(kind))

    def test_strict_json(self):
        for raw in ('{"a":1,"a":2}', '{"n":NaN}', '{"n":1e999}',
                    chr(96) * 3 + "json {}", '"' + "x" * 1_048_577 + '"'):
            with self.subTest(raw=raw[:40]), self.assertRaises(ContractError):
                parse_json(raw)

    def test_hash_key_order(self):
        self.assertEqual(digest({"a": 1, "b": 2}), digest({"b": 2, "a": 1}))

    def test_corpus(self):
        report = run_scaffold()
        self.assertGreaterEqual(report["total"], 40)
        self.assertEqual(report["passed"], report["total"],
                         [r for r in report["results"] if not r["passed"]])
        self.assertFalse(report["model_executed"])
        self.assertIsNone(report["model_quality_metrics"])

    def test_reference_repeatability(self):
        c = context()
        reordered = deepcopy(c)
        reordered["fleet"].reverse()
        reordered["tasks"].reverse()
        self.assertEqual(reference_proposal(c), reference_proposal(reordered))
        self.assertEqual(reference_proposal(c), reference_proposal(c))

    def test_offline_reallocation_and_stale_proposal(self):
        c = context()
        original = reference_proposal(c)
        c["fleet"][1]["connected"] = False
        new = reference_proposal(c)
        self.assertEqual(new["status"], "proposed")
        self.assertEqual(len(new["assignments"]), 3)
        self.assertNotIn("UAV-02", {a["node_id"] for a in new["assignments"]})
        self.assertTrue(any(e.startswith("NODE_OFFLINE:UAV-02")
                            for e in validate_proposal(c, original)))

    def test_node_and_wildcard_denial(self):
        for node_id in ("UAV-01", "*"):
            c = context()
            original = reference_proposal(c)
            c["policy_denials"] = [{"node_id": node_id, "action": "GOTO",
                                   "reason_code": "OPERATOR_DENY"}]
            self.assertTrue(any(e.startswith("POLICY_DENIED:UAV-01")
                                for e in validate_proposal(c, original)))

    def test_snapshot_and_sample_expire_during_inference(self):
        c = context()
        p = reference_proposal(c)
        self.assertIn("SNAPSHOT_EXPIRED", validate_proposal(c, p, 120000))
        c["constraints"]["max_sample_age_ms"] = 100
        self.assertTrue(any(e.startswith("TELEMETRY_STALE")
                            for e in validate_proposal(c, p, 101)))
        self.assertIn("INVALID_ELAPSED_TIME", context_errors(c, -1))

    def test_invalid_candidate_is_not_accepted_proposal(self):
        c = context()
        p = reference_proposal(c)
        p["assignments"][0]["node_id"] = "UAV-99"
        result = evaluate_raw(c, canonical_json(p))
        self.assertTrue(result["schema_valid"])
        self.assertFalse(result["accepted"])
        self.assertIsNone(result["accepted_proposal"])

    def test_extra_fields_blocked(self):
        c = context()
        p = reference_proposal(c)
        p["transport_endpoint"] = "not-allowed"
        self.assertTrue(validate_proposal(c, p))

    def test_invalid_context_does_not_call_model(self):
        client = MagicMock()
        c = context()
        c["snapshot_age_ms"] = 120000
        with self.assertRaises(ContractError):
            plan_with_client(c, client)
        client.complete.assert_not_called()

    def test_pipeline_keeps_raw_response_and_rechecks_time(self):
        c = context()
        raw = canonical_json(reference_proposal(c))
        client = MagicMock(model="fixture")
        client.complete.return_value = {"content": raw, "model": "fixture", "usage": None}
        for duration, accepted in ((0.1, True), (121, False)):
            with patch("uavswarm_llm_lab.mission_planner.perf_counter",
                       side_effect=[0, duration]):
                result = plan_with_client(c, client)
            self.assertEqual(result["accepted"], accepted)
            self.assertEqual(result["raw_output"], raw)
            self.assertEqual(result["latency_ms"], duration * 1000)
            self.assertEqual(result["settings"]["repair_attempts"], 0)
            self.assertIsNone(result["vram_peak_mib"])

    def test_model_failures_count_as_failures(self):
        client = MagicMock(model="fixture")
        client.complete.side_effect = ModelError("unavailable")
        result = run_model_benchmark(client)
        self.assertEqual(result["expected_status_rate"], 0)
        self.assertEqual(result["schema_valid_rate"], 0)
        self.assertEqual(result["attempted"], sum(c["kind"] == "mission" for c in cases()))

    def test_no_cross_layer_imports(self):
        forbidden = {"uav_runtime", "simulation", "pymavlink", "subprocess",
                     "socket", "ctypes", "torch", "transformers"}
        root = Path(__file__).resolve().parents[1] / "src"
        for path in root.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]
                for module in modules:
                    self.assertNotIn(module.split(".")[0], forbidden, str(path))


class ClientTest(unittest.TestCase):
    def test_literal_loopback_required(self):
        for url in ("http://example.com:8000/v1", "http://localhost:8000/v1",
                    "http://127.0.0.1:8000/api", "http://127.0.0.1:8000/v1?q=x",
                    "http://user@127.0.0.1:8000/v1", "http://127.0.0.1/v1"):
            with self.subTest(url=url), self.assertRaises(ModelError):
                LocalModelClient(url, "fixture")
        LocalModelClient("http://127.0.0.1:18080/v1", "fixture")
        LocalModelClient("http://[::1]:18080/v1", "fixture")

    def invoke(self, body):
        self.opener = MagicMock()
        self.opener.open.return_value.__enter__.return_value.read.return_value = body
        with patch("uavswarm_llm_lab.local_model_client.build_opener", return_value=self.opener):
            return LocalModelClient("http://127.0.0.1:18080/v1", "fixture").complete(
                [], schema("proposal"), seed=0, max_tokens=100, constrained=True)

    def test_request_has_no_tools(self):
        self.invoke(b'{"choices":[{"finish_reason":"stop","message":{"content":"{}"}}]}')
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:18080/v1/chat/completions")
        payload = json.loads(request.data)
        self.assertNotIn("tools", payload)
        self.assertEqual(payload["response_format"]["type"], "json_schema")

    def test_bad_incomplete_and_tool_responses(self):
        responses = [b"{}", b"[]", b"not json", b"x" * 1_048_577,
                     b'{"choices":[null]}',
                     b'{"choices":[{"finish_reason":"stop","message":null}]}',
                     b'{"choices":[{"finish_reason":"length","message":{"content":"{}"}}]}',
                     b'{"choices":[{"finish_reason":"stop","message":{"content":"{}","tool_calls":[{}]}}]}']
        for body in responses:
            with self.subTest(body=body[:80]), self.assertRaises(ModelError):
                self.invoke(body)

    def test_redirect_refused(self):
        with self.assertRaises(ModelError):
            _NoRedirect().redirect_request(None, None, 302, "", {}, "http://example.com")

    def test_timeout_no_retry(self):
        opener = MagicMock()
        opener.open.side_effect = TimeoutError("fixture")
        with patch("uavswarm_llm_lab.local_model_client.build_opener", return_value=opener):
            with self.assertRaises(ModelError):
                LocalModelClient("http://127.0.0.1:18080/v1", "fixture").complete(
                    [], schema("proposal"), seed=0, max_tokens=100, constrained=True)
        self.assertEqual(opener.open.call_count, 1)


if __name__ == "__main__":
    unittest.main()
