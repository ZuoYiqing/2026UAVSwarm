"""Pure tests: fake responses exercise scoring, never run a model or flight."""
import json
import unittest

from uavswarm_llm_lab.contracts import ContractError, digest, parse_json, resource_text
from uavswarm_llm_lab.grounding_eval import (
    run_grounding_eval, run_rule_grounding_baseline, validate_corpus,
)
from uavswarm_llm_lab.intent_grounder import derive_proposal, ground_with_client
from uavswarm_llm_lab.local_model_client import ModelError


class ScriptedClient:
    model = "scripted-test-only"

    def complete(self, messages, output_schema, *, seed, max_tokens, constrained):
        objective = json.loads(messages[1]["content"])["objective"]
        if "C区" in objective:
            bindings = [{"region_id": "route-a", "matched_text": "C区"}]
        elif "东部试验区" in objective:
            bindings = [{"region_id": "route-a", "matched_text": "东部试验区"}]
        else:
            bindings = [{"region_id": "route-a" if label == "A区" else "route-b",
                         "matched_text": label}
                        for _, label in sorted((objective.index(label), label)
                                               for label in ("A区", "B区") if label in objective)]
        candidate = {
            "intent_type": "reconnaissance" if "巡检" in objective else "flight_validation",
            "bindings": bindings, "explanation": "Scripted fixture, not a model result."
        }
        return {"content": json.dumps(candidate, ensure_ascii=False),
                "model": self.model, "usage": {"prompt_tokens": 0, "completion_tokens": 0}}


class GroundingEvalTest(unittest.TestCase):
    def setUp(self):
        self.corpus = parse_json(resource_text("benchmarks/grounding_cases_v0_1.json"))

    def test_corpus_is_labelled_and_synthetic(self):
        validate_corpus(self.corpus)
        self.assertEqual(len(self.corpus["cases"]), 9)
        self.assertEqual(self.corpus["base_request"]["source"], "synthetic_benchmark")

    def test_prospective_challenge_is_frozen(self):
        challenge = parse_json(resource_text("benchmarks/grounding_challenge_v0_1.json"))
        validate_corpus(challenge)
        self.assertEqual(len(challenge["cases"]), 18)
        self.assertEqual(digest(challenge),
                         "a75fb3e4143cf52586270bb53256bb2d74fa5398d9a0839c18ac53e2ccc565ba")
        orders = [case["expected_region_ids"] for case in challenge["cases"]
                  if case["case_id"].startswith("order_")]
        self.assertEqual(len({tuple(order) for order in orders}), 6)
        self.assertTrue(all(set(order) == {"r-north", "r-south", "r-east"}
                            for order in orders))

    def test_background_landmark_is_not_a_destination(self):
        # The previous baseline accepted an extra destination on this case.
        challenge = parse_json(resource_text("benchmarks/grounding_challenge_v0_1.json"))
        report = run_rule_grounding_baseline(challenge)
        self.assertEqual(report["acceptance_match_rate"], 1.0)
        self.assertEqual(report["false_accept_count"], 0)
        row = next(row for row in report["results"]
                   if row["case_id"] == "background_n_target_s")
        self.assertTrue(row["accepted"])
        self.assertFalse(row["false_accept"])
        self.assertTrue(row["candidate_semantic_match"])

    def test_background_role_is_enforced_on_rule_and_model_candidates(self):
        challenge = parse_json(resource_text("benchmarks/grounding_challenge_v0_1.json"))
        request = challenge["base_request"].copy()
        request["objective"] = "飞行验证：北仓仅作为参照物；起飞、前往南库、降落。"
        derived = derive_proposal(request)
        self.assertEqual([item["region_id"] for item in derived["grounding"]["bindings"]],
                         ["r-south"])
        self.assertIsNotNone(derived["proposal"])

        class WrongModel:
            model = "scripted-test-only"
            def complete(self, messages, output_schema, **kwargs):
                return {"content": json.dumps({
                    "intent_type": "flight_validation",
                    "bindings": [{"region_id": "r-north", "matched_text": "北仓"},
                                 {"region_id": "r-south", "matched_text": "南库"}],
                    "explanation": "fixture"}, ensure_ascii=False),
                    "model": self.model, "usage": {}}

        checked = ground_with_client(request, WrongModel())
        self.assertFalse(checked["accepted"])
        self.assertIsNone(checked["proposal"])
        self.assertIn("NON_TARGET_REGION_SELECTED:r-north", checked["errors"])

    def test_unclear_or_contradictory_background_role_fails_closed(self):
        challenge = parse_json(resource_text("benchmarks/grounding_challenge_v0_1.json"))
        request = challenge["base_request"].copy()
        request["objective"] = "飞行验证：北仓在背景；起飞、前往南库、降落。"
        with self.assertRaisesRegex(ContractError, "OBJECTIVE_REGION_ROLE_AMBIGUOUS"):
            derive_proposal(request)
        request["objective"] = "飞行验证：北仓只是背景地标；起飞、前往北仓、降落。"
        with self.assertRaisesRegex(ContractError, "OBJECTIVE_REGION_ROLE_CONTRADICTION"):
            derive_proposal(request)
        request["objective"] = "飞行验证：北仓只是背景地标；东塔在背景；起飞、前往南库、降落。"
        with self.assertRaisesRegex(ContractError, "OBJECTIVE_REGION_ROLE_AMBIGUOUS"):
            derive_proposal(request)

    def test_scoring_separates_semantics_from_acceptance(self):
        report = run_grounding_eval(self.corpus, ScriptedClient())
        rows = {row["case_id"]: row for row in report["results"]}
        self.assertEqual(report["attempted"], 9)
        self.assertTrue(rows["exact_a"]["candidate_semantic_match"])
        self.assertTrue(rows["exact_a"]["accepted"])
        self.assertFalse(rows["unknown_c"]["accepted"])
        self.assertFalse(rows["recon_a"]["accepted"])
        self.assertTrue(rows["east_alias"]["candidate_semantic_match"])
        self.assertFalse(rows["east_alias"]["accepted"])
        self.assertEqual(rows["recon_a"]["result"]["reason_code"],
                         "PERCEPTION_EXECUTION_UNAVAILABLE")
        self.assertFalse(rows["negated_b"]["accepted"])
        self.assertIn("OBJECTIVE_EXCLUSION_UNREPRESENTABLE:route-b",
                      rows["negated_b"]["result"]["errors"])
        self.assertEqual(report["false_accept_count"], 0)

    def test_rejects_non_synthetic_corpus(self):
        self.corpus["base_request"]["source"] = "runtime_snapshot"
        with self.assertRaisesRegex(ContractError, "MUST_BE_SYNTHETIC"):
            validate_corpus(self.corpus)

    def test_rule_baseline_has_separate_non_model_report(self):
        report = run_rule_grounding_baseline(self.corpus)
        self.assertFalse(report["model_executed"])
        self.assertEqual(report["total"], 9)
        self.assertEqual(report["false_accept_count"], 0)

    def test_explicit_prompt_ablation_preserves_schema_and_evidence(self):
        class RecordingClient(ScriptedClient):
            def complete(self, messages, output_schema, **kwargs):
                self.messages = messages
                self.schema = output_schema
                return super().complete(messages, output_schema, **kwargs)
        client = RecordingClient()
        report = run_grounding_eval(self.corpus, client, prompt_version='selective_v2')
        self.assertEqual(report['prompt_version'], 'selective_v2')
        self.assertIn('候选字典', client.messages[0]['content'])
        self.assertEqual(client.schema['properties']['bindings']['minItems'], 1)
        self.assertTrue(all(row['result']['raw_output'] for row in report['results']))
        self.assertTrue(all(row['result']['settings']['repair_attempts'] == 0
                            for row in report['results']))
        self.assertEqual(report['false_accept_count'], 0)

    def test_unconstrained_format_ablation_still_validates_candidates(self):
        class RecordingClient(ScriptedClient):
            def __init__(self):
                self.modes = []
            def complete(self, messages, output_schema, **kwargs):
                self.modes.append(kwargs['constrained'])
                return super().complete(messages, output_schema, **kwargs)
        client = RecordingClient()
        report = run_grounding_eval(self.corpus, client, constrained=False)
        self.assertFalse(report['constrained'])
        self.assertEqual(client.modes, [False] * 9)
        rows = {row['case_id']: row for row in report['results']}
        self.assertTrue(rows['exact_a']['accepted'])
        self.assertFalse(rows['unknown_c']['accepted'])
        self.assertFalse(rows['recon_a']['accepted'])
        self.assertFalse(rows['negated_b']['accepted'])
        self.assertTrue(all(row['result']['settings']['constrained'] is False
                            for row in report['results']))

    def test_unknown_prompt_is_rejected_before_model_call(self):
        request = self.corpus['base_request'].copy()
        request['objective'] = self.corpus['cases'][0]['objective']
        with self.assertRaisesRegex(ContractError, 'UNKNOWN_GROUNDING_PROMPT_VERSION'):
            ground_with_client(request, None, prompt_version='unreviewed')

    def test_incomplete_evidence_is_not_a_successful_candidate(self):
        class IncompleteClient:
            model = 'incomplete-fixture'
            def complete(self, *args, **kwargs):
                raise ModelError('MODEL_RESPONSE_INCOMPLETE',
                                 response_evidence={'choices': [{'finish_reason': 'length'}]})
        report = run_grounding_eval(self.corpus, IncompleteClient())
        self.assertEqual(report['completed_model_calls'], 0)
        self.assertEqual(report['candidate_semantic_match_rate'], 0)
        self.assertEqual(report['false_accept_count'], 0)
        self.assertTrue(all(row['result']['response_evidence'] for row in report['results']))


if __name__ == "__main__":
    unittest.main()
