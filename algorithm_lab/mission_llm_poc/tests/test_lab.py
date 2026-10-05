"""No network or model weights required; server responses are test fixtures."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from jsonschema import Draft202012Validator
from uavswarm_llm_lab.benchmark import cases, case_context, run_model_benchmark, run_scaffold
from uavswarm_llm_lab.contracts import (ContractError, canonical_json, digest,
                                        parse_json, schema, schema_errors)
from uavswarm_llm_lab.local_model_client import LocalModelClient, ModelError, _NoRedirect
from uavswarm_llm_lab.intent_grounder import (derive_context, derive_proposal,
                                               ground_with_client, request_errors)
from uavswarm_llm_lab.mission_planner import evaluate_raw, plan_with_client, reference_proposal
from uavswarm_llm_lab.semantic_validator import context_errors, validate_proposal


def context():
    return case_context(cases()[0])


class LabTest(unittest.TestCase):
    def test_objective_generates_tasks_without_input_tasks(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "simple_recon_flight_intent.json"
        request = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn("tasks", request)
        self.assertFalse(request_errors(request))
        result = derive_proposal(request)
        task = result["context"]["tasks"][0]
        self.assertEqual(task["region_id"], "verified-flight-route-001")
        self.assertEqual(task["required_actions"], ["TAKEOFF", "GOTO", "LAND"])
        self.assertEqual(task["waypoint_ids"], ["WP-VERIFIED-60-12-20"])
        self.assertEqual(result["grounding"]["bindings"][0]["matched_text"],
                         "verified-flight-route-001")
        self.assertFalse(validate_proposal(result["context"], result["proposal"]))

    def test_simple_recon_handoff_matches_reproducible_generation(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        request = json.loads((examples / "simple_recon_flight_intent.json").read_text(encoding="utf-8"))
        handoff = json.loads((examples / "simple_recon_flight_handoff.json").read_text(encoding="utf-8"))
        generated = derive_proposal(request)
        self.assertEqual(handoff["input_hash"], digest(request))
        for key in ("context", "grounding", "proposal", "execution_ready"):
            self.assertEqual(handoff[key], generated[key])
        self.assertFalse(handoff["execution_ready"])

    def test_external_tasks_and_ungrounded_references_are_rejected(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "simple_recon_flight_intent.json"
        request = json.loads(path.read_text(encoding="utf-8"))
        request["tasks"] = []
        self.assertIn("EXTERNAL_TASKS_FORBIDDEN", request_errors(request)[0])
        conflict = derive_proposal(request)
        self.assertEqual(conflict["reason_code"], "EXTERNAL_TASKS_FORBIDDEN")
        self.assertEqual(conflict["clarification_request"]["audience"], "originating_operator")
        self.assertIsNone(conflict["proposal"])
        del request["tasks"]
        request["objective"] = "对未知区域做飞行验证：起飞、前往航点、降落"
        with self.assertRaisesRegex(ContractError, "REGION_REFERENCE_UNRESOLVED"):
            derive_context(request)
        request["objective"] = "对 verified-flight-route-001 做飞行验证，起飞后前往航点，不要降落"
        with self.assertRaisesRegex(ContractError, "FLIGHT_ACTION_CONTRADICTION"):
            derive_context(request)

    def test_objective_binding_order_and_unsupported_recon_are_explicit(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "simple_recon_flight_intent.json"
        request = json.loads(path.read_text(encoding="utf-8"))
        request["waypoints"].append({"waypoint_id": "WP-SECOND", "position_m":
                                      {"north_m": 61, "east_m": 12, "down_m": -20}})
        request["regions"].append({"region_id": "second-route", "labels": ["second-route"],
                                    "waypoint_ids": ["WP-SECOND"],
                                    "source_reference": "test fixture"})
        request["objective"] = "飞行验证：起飞后先前往 second-route，再前往 verified-flight-route-001，最后降落"
        derived, report = derive_context(request)
        self.assertEqual([task["region_id"] for task in derived["tasks"]],
                         ["second-route", "verified-flight-route-001"])
        self.assertEqual([row["matched_text"] for row in report["bindings"]],
                         ["second-route", "verified-flight-route-001"])
        request["objective"] = "对 verified-flight-route-001 做巡检"
        derived, report = derive_context(request)
        self.assertEqual(report["intent_type"], "reconnaissance")
        self.assertIn("OBSERVE", derived["tasks"][0]["required_actions"])
        self.assertIn("RETURN_HOME", derived["tasks"][0]["required_actions"])
        blocked = derive_proposal(request)
        self.assertEqual(blocked["grounding"]["intent_type"], "reconnaissance")
        self.assertEqual(blocked["reason_code"], "PERCEPTION_EXECUTION_UNAVAILABLE")
        self.assertIsNone(blocked["proposal"])
        self.assertFalse(blocked["accepted"])

    def test_local_model_grounding_keeps_raw_evidence_and_rejects_invented_ids(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "simple_recon_flight_intent.json"
        request = json.loads(path.read_text(encoding="utf-8"))
        client = MagicMock(model="fixture")
        candidate = {"intent_type": "flight_validation", "bindings": [
            {"region_id": "verified-flight-route-001",
             "matched_text": "verified-flight-route-001"}],
            "explanation": "The explicit route ID names the supplied flight route."}
        client.complete.return_value = {"content": canonical_json(candidate),
                                        "model": "fixture", "usage": None}
        with patch("uavswarm_llm_lab.intent_grounder.perf_counter", side_effect=[0, 0.1]):
            result = ground_with_client(request, client)
        self.assertTrue(result["accepted"])
        self.assertFalse(result["execution_ready"])
        self.assertEqual(result["raw_output"], canonical_json(candidate))
        self.assertFalse(result["grounding"]["requires_human_semantic_review"])
        self.assertFalse(validate_proposal(result["context"], result["proposal"]))
        self.assertTrue(client.complete.call_args.kwargs["constrained"])

        candidate["bindings"][0]["region_id"] = "invented-route"
        client.complete.return_value["content"] = canonical_json(candidate)
        with patch("uavswarm_llm_lab.intent_grounder.perf_counter", side_effect=[0, 0.1]):
            rejected = ground_with_client(request, client)
        self.assertFalse(rejected["accepted"])
        self.assertIsNone(rejected["proposal"])
        self.assertIn("UNKNOWN_REGION_ID:invented-route", rejected["errors"])

    def test_local_model_grounding_nonexact_reference_needs_review(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "simple_recon_flight_intent.json"
        request = json.loads(path.read_text(encoding="utf-8"))
        request["objective"] = "对北侧路线做飞行验证：起飞、前往航点、降落"
        candidate = {"intent_type": "flight_validation", "bindings": [
            {"region_id": "verified-flight-route-001", "matched_text": "北侧路线"}],
            "explanation": "Candidate semantic mapping."}
        client = MagicMock(model="fixture")
        client.complete.return_value = {"content": canonical_json(candidate),
                                        "model": "fixture", "usage": None}
        with patch("uavswarm_llm_lab.intent_grounder.perf_counter", side_effect=[0, 0.1]):
            result = ground_with_client(request, client)
        self.assertFalse(result["accepted"])
        self.assertTrue(result["grounding"]["requires_human_semantic_review"])
        self.assertFalse(result["execution_ready"])
        self.assertIsNone(result["proposal"])
        self.assertIn("SEMANTIC_BINDING_REVIEW_REQUIRED", result["errors"])

    def test_flight_validation_fixture_is_separate_from_inspection(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "flight_validation_only.json"
        flight = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(context_errors(flight))
        self.assertIn("不包含观察或巡检完成判定", flight["objective"])
        self.assertEqual({action for task in flight["tasks"]
                          for action in task["required_actions"]},
                         {"TAKEOFF", "GOTO", "LAND"})
        proposal = reference_proposal(flight)
        self.assertEqual(proposal["status"], "proposed")
        self.assertEqual(len({item["node_id"] for item in proposal["assignments"]}), 3)
        self.assertFalse(proposal["execution_authorized"])

    def test_schema_definitions(self):
        for kind in ("context", "proposal"):
            Draft202012Validator.check_schema(schema(kind))

    def test_schema_enforces_status_reason_and_assignment_scopes(self):
        c = context()
        proposed = reference_proposal(c)
        self.assertFalse(schema_errors(proposed, "proposal"))
        proposed["reason_code"] = "ASSIGNED"
        self.assertTrue(schema_errors(proposed, "proposal"))

        rejected = reference_proposal(c)
        rejected.update(status="rejected", reason_code="REQUEST_REJECTED",
                        assignments=[], unassigned_tasks=[
                            {"task_id": task["task_id"],
                             "reason_code": "REQUEST_REJECTED",
                             "explanation": "Rejected fixture."}
                            for task in c["tasks"]])
        self.assertFalse(schema_errors(rejected, "proposal"))
        rejected["unassigned_tasks"][0]["reason_code"] = "ASSIGNED"
        self.assertTrue(schema_errors(rejected, "proposal"))

    def test_prompt_forbids_unproved_geometry_and_maps_reason_codes(self):
        prompt = (Path(__file__).resolve().parents[1] / "src" /
                  "uavswarm_llm_lab" / "prompts" /
                  "mission_planner_system.txt").read_text(encoding="utf-8")
        for required in ("proposed/MISSION_PROPOSED", "ASSIGNED is only valid",
                         "Do not claim a direct/clear/safe path",
                         "overall constraint satisfaction"):
            self.assertIn(required, prompt)

    def test_unproven_route_and_energy_claims_reject_candidate(self):
        c = context()
        p = reference_proposal(c)
        p["assignments"][0]["explanation"] = "Direct path feasible within constraints."
        p["warnings"].append("Assume sufficient based on battery %.")
        evaluation = evaluate_raw(c, canonical_json(p))
        self.assertTrue(evaluation["schema_valid"])
        self.assertFalse(evaluation["accepted"])
        self.assertIsNone(evaluation["accepted_proposal"])
        self.assertIn("UNPROVEN_ROUTE_CLAIM", evaluation["errors"])
        self.assertIn("UNPROVEN_ENERGY_CLAIM", evaluation["errors"])
        p["assignments"][0]["explanation"] = "Route feasibility not verified."
        p["warnings"][-1] = "Energy sufficiency not calculated."
        self.assertFalse(validate_proposal(c, p))

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

    def test_explicit_sampling_is_sent_and_default_stays_unchanged(self):
        self.invoke(b'{"choices":[{"finish_reason":"stop","message":{"content":"{}"}}]}')
        default_payload = json.loads(self.opener.open.call_args.args[0].data)
        self.assertEqual(default_payload["temperature"], 0)
        self.assertNotIn("min_p", default_payload)
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = (
            b'{"choices":[{"finish_reason":"stop","message":{"content":"{}"}}]}')
        client = LocalModelClient("http://127.0.0.1:18080/v1", "fixture",
                                  sampling_temperature=0.7, sampling_min_p=0)
        with patch("uavswarm_llm_lab.local_model_client.build_opener", return_value=opener):
            client.complete([], schema("proposal"), seed=0, max_tokens=100, constrained=True)
        payload = json.loads(opener.open.call_args.args[0].data)
        self.assertEqual((payload["temperature"], payload["min_p"]), (0.7, 0))
        self.assertNotIn("tools", payload)
        for bad in (float("nan"), -0.1, 1.1, True):
            with self.subTest(bad=bad), self.assertRaises(ModelError):
                LocalModelClient("http://127.0.0.1:18080/v1", "fixture",
                                 sampling_min_p=bad)

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

    def test_incomplete_response_preserves_evidence_without_accepting(self):
        body = {'model': 'fixture', 'choices': [{'finish_reason': 'length',
                'message': {'content': '{"unfinished":'}}],
                'usage': {'completion_tokens': 100}}
        with self.assertRaisesRegex(ModelError, 'MODEL_RESPONSE_INCOMPLETE') as raised:
            self.invoke(json.dumps(body).encode('utf-8'))
        self.assertEqual(raised.exception.response_evidence, body)
        self.assertEqual(self.opener.open.call_count, 1)

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
