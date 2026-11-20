from __future__ import annotations

import unittest

from uavswarm_llm_lab import board_coordination_eval as board
from uavswarm_llm_lab import coordination_bench as bench
from uavswarm_llm_lab import platform_coordination_eval as mission
from uavswarm_llm_lab.contracts import canonical_json, parse_json


class MissionCoordinationTests(unittest.TestCase):
    def test_rule_baseline_beats_fixed_assignment_on_backup_case(self):
        rules = bench.evaluate("mission", "rules")
        fixed = bench.evaluate("mission", "fixed")
        self.assertEqual(rules["metrics"]["strict_correct"], 8)
        self.assertEqual(fixed["metrics"]["strict_correct"], 7)
        row = next(r for r in rules["cases"] if r["case_id"] == "handover-to-backup-uav")
        self.assertIn({"task_id": "roof-b", "node_id": "UAV-A"}, row["proposal"]["assignments"])
        self.assertEqual(row["retained_verified"], ["roof-a"])
        self.assertEqual(rules["metrics"]["valid_proposals"], 8)
        self.assertFalse(rules["execution_authorized"])

    def test_capture_and_wrong_asset_cannot_unlock_ground_handoff(self):
        fixture, _ = bench.dataset("mission")
        for case in fixture["cases"][2:4]:
            with self.subTest(case=case["case_id"]):
                state = mission.snapshot(fixture, case)
                proposal = {"assignments": [{"task_id": "ground-b", "node_id": "UGV-C"}], "deferred": []}
                checked = mission.assess(state, proposal, case["expected"])
                self.assertFalse(checked["valid_proposal"])
                self.assertIn("PREMATURE_GROUND_HANDOFF", checked["violations"])
                self.assertFalse(checked["strict_correct"])

    def test_completed_reassignment_and_wrong_platform_are_rejected(self):
        fixture, _ = bench.dataset("mission")
        case = fixture["cases"][4]
        proposal = {"assignments": [{"task_id": "roof-a", "node_id": "UAV-A"},
                                    {"task_id": "meter", "node_id": "UAV-A"}], "deferred": []}
        verdict = mission.assess(mission.snapshot(fixture, case), proposal, case["expected"])
        self.assertEqual(set(verdict["violations"]), {"ALREADY_VERIFIED_REPEATED", "DOUBLE_BOOKED_TASK_OR_NODE",
                                                    "INELIGIBLE_PLATFORM"})

    def test_feedback_loop_completes_only_after_retry_then_aerial_to_ground_handoff(self):
        run = bench.evaluate("mission", "rules")["episode"]
        first, second, third = run["transitions"]
        self.assertFalse(bench.evaluate("mission", "fixed")["episode"]["simulated_completion"])
        self.assertTrue(run["simulated_completion"])
        self.assertEqual(first["feedback"][-1]["record"]["task_id"], "meter")
        self.assertIn({"kind": "TASK_RESULT_MISSING", "task_id": "roof-b", "node_id": "UAV-B"}, first["feedback"])
        self.assertEqual(second["proposal"]["assignments"], [{"task_id": "roof-b", "node_id": "UAV-A"}])
        self.assertEqual(third["proposal"]["assignments"], [{"task_id": "ground-b", "node_id": "UGV-C"}])
        self.assertEqual({row["task_id"] for row in third["input"]["observations"]}, {"roof-a", "roof-b", "meter"})
        self.assertEqual(run["final_task_states"]["ground-b"], "COMPLETE")

    def test_invalid_proposal_cannot_change_simulated_task_state(self):
        fixture, _ = bench.dataset("mission")
        invalid = {"assignments": [{"task_id": "ground-b", "node_id": "UGV-C"},
                                   {"task_id": "meter", "node_id": "UGV-M"}], "deferred": []}
        result = mission.run_episode(fixture, lambda state: (invalid, None))
        self.assertFalse(result["simulated_completion"])
        self.assertTrue(all(not turn["input"]["observations"] for turn in result["transitions"]))
        self.assertTrue(all(any(event["kind"] == "PROPOSAL_REJECTED" for event in turn["feedback"])
                            for turn in result["transitions"]))

    def test_mission_ablation_changes_only_preferred_field_in_public_input(self):
        class Client:
            model = "stub-only"

            def complete(self, *args, **kwargs):
                return {"model": self.model, "content": '{"assignments":[],"deferred":[]}'}

        direct, ablated = [bench.evaluate("mission", method, Client())["cases"][0]["model_trace"]
                           for method in ("model", "model-no-preference")]
        self.assertEqual(direct["messages"][0], ablated["messages"][0])
        self.assertEqual(direct["response_schema"], ablated["response_schema"])
        public = parse_json(direct["messages"][1]["content"])
        for task in public["tasks"]:
            self.assertIsNotNone(task.pop("preferred"))
        self.assertEqual(public, parse_json(ablated["messages"][1]["content"]))


class BoardCoordinationTests(unittest.TestCase):
    def test_referee_distinguishes_legality_duplicates_and_cross_team_contest(self):
        cards = {"A": 5, "B": 4, "C": 3, "D": 2}
        result = board.score_round(cards, ["A", "A"], ["A", "C"])
        self.assertEqual(result["legal"], [True, True])
        self.assertTrue(result["duplicate"])
        self.assertEqual((result["our_score"], result["opponent_score"], result["contested"]), (0, 3, ["A"]))
        self.assertEqual(board.score_round(cards, [None, "B"], ["A", "C"])["legal"], [False, True])

    def test_pass_does_not_imply_contributing_to_team(self):
        cards = {"A": 5, "B": 4}
        result = board.score_round(cards, ["A", "PASS"], ["A", "B"])
        self.assertEqual(result["legal"], [True, True])
        self.assertFalse(result["duplicate"])
        self.assertEqual((result["pass_choices"], result["avoidable_passes"], result["distinct_scoring_cards"]), (1, 1, 0))
        self.assertEqual(board.score_round({"A": 5}, ["A", "PASS"], ["A", "PASS"])["avoidable_passes"], 0)

    def test_coordination_and_history_effects_are_separate(self):
        a, b, c = [bench.evaluate("board", method) for method in ("independent", "shared", "history")]
        self.assertEqual([r["metrics"]["legal_choices"] for r in (a, b, c)], [24, 24, 24])
        self.assertEqual([r["metrics"]["duplicate_rounds"] for r in (a, b, c)], [12, 0, 0])
        self.assertEqual([r["metrics"]["our_score"] for r in (a, b, c)], [30, 54, 69])
        self.assertEqual(c["metrics"]["repeated_after_contest"], 0)
        self.assertEqual(c["metrics"]["previously_contested_choices"], 5)
        self.assertEqual(c["rounds"][1]["our_choices"], ["B", "D"])
        self.assertEqual(c["rounds"][5]["our_choices"], ["A", "C"])

    def test_each_model_agent_observes_one_piece_without_current_opponent_move(self):
        class Client:
            model = "stub-only"

            def __init__(self):
                self.views = []

            def complete(self, messages, schema, **params):
                view = parse_json(messages[-1]["content"])
                self.views.append(view)
                self.assert_fields(view, schema, params)
                pick = board.rule_pick(view)
                return {"model": self.model, "content": canonical_json({"choice": pick})}

            def assert_fields(self, view, schema, params):
                assert set(view) == {"your_piece", "cards", "round", "teammate_intent", "opponent_public_history"}
                assert len(view["opponent_public_history"]) == view["round"] - 1
                assert "opponent_choices" not in view
                assert schema["required"] == ["choice"]
                assert params == {"seed": 0, "max_tokens": 32, "constrained": True}

        fixture = Client()
        result = bench.evaluate("board", "model-history", fixture)
        self.assertEqual(result["model_calls_attempted"], 24)
        first, second = fixture.views[:2]
        self.assertEqual(first["your_piece"], "piece-1")
        self.assertIsNone(first["teammate_intent"])
        self.assertEqual(second["your_piece"], "piece-2")
        self.assertEqual(second["teammate_intent"], "A")
        self.assertEqual(result["metrics"]["our_score"], 69)

    def test_model_identity_mismatch_is_not_replaced_with_rule_choice(self):
        class WrongModel:
            model = "expected"

            def complete(self, *args, **kwargs):
                return {"model": "not-requested", "content": '{"choice":"A"}'}

        result = bench.evaluate("board", "model-shared", WrongModel())
        self.assertEqual(result["metrics"]["legal_choices"], 0)
        first = result["rounds"][0]["agent_decisions"][0]
        self.assertIsNone(first["choice"])
        self.assertEqual(first["model_trace"]["model_raw_response"], '{"choice":"A"}')
        self.assertEqual(first["model_trace"]["error"], "MODEL_REPORT_IDENTITY_MISMATCH")
        self.assertFalse(result["execution_authorized"])

    def test_board_nudge_does_not_mask_choices_or_change_what_referee_scores(self):
        class Client:
            model = "stub-only"

            def complete(self, *args, **kwargs):
                return {"model": self.model, "content": '{"choice":"A"}'}

        plain, explicit = (bench.evaluate("board", method, Client()) for method in ("model-shared", "model-shared-explicit"))
        a, b = ([d["model_trace"] for d in run["rounds"][0]["agent_decisions"]] for run in (plain, explicit))
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[1]["messages"][1], b[1]["messages"][1])
        self.assertIn("队友这轮已打算选 A", b[1]["messages"][0]["content"])
        self.assertEqual(a[1]["response_schema"], b[1]["response_schema"])
        self.assertEqual(explicit["metrics"]["duplicate_rounds"], 12)


if __name__ == "__main__":
    unittest.main()
