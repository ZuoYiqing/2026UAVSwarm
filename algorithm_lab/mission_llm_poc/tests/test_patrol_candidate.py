from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from uavswarm_llm_lab import patrol_candidate as candidate
from uavswarm_llm_lab.contracts import resource_text
from uavswarm_llm_lab.semantic_validator import validate_proposal


LAB = Path(__file__).resolve().parents[1]
REQUESTS = json.loads((LAB / "examples/patrol_candidate_requests_v0_1.json").read_text(encoding="utf-8"))


class PatrolCandidateTests(unittest.TestCase):
    def test_same_input_repeats_and_another_objective_changes_the_assignments(self):
        with patch("socket.socket") as transport:
            first = candidate.build_candidate(REQUESTS[0])
            second = candidate.build_candidate(REQUESTS[1])
            self.assertEqual(first, candidate.build_candidate(REQUESTS[0]))
        transport.assert_not_called()
        self.assertNotEqual(first["candidate_id"], second["candidate_id"])
        self.assertEqual([row["node_id"] for row in first["proposal"]["assignments"]], ["UAV-01", "UAV-02"])
        self.assertEqual([row["node_id"] for row in second["proposal"]["assignments"]], ["UAV-02"])
        self.assertEqual([row["waypoint_id"] for row in second["context"]["waypoints"]],
                         ["FX-METER-ENTRY", "FX-METER-SAMPLE"])
        for result in (first, second):
            self.assertEqual(result["status"], "candidate")
            self.assertEqual(validate_proposal(result["context"], result["proposal"]), [])
            self.assertEqual(result["context"]["coordinate_frame"], "scene_ned")
            self.assertFalse(result["execution_authorized"])
            self.assertFalse(result["runtime_submission_allowed"])
            self.assertFalse(result["proposal"]["execution_authorized"])
            self.assertNotIn("steps", result["proposal"])
            self.assertFalse(result["completion_expectation"]["inspection_completed"])
            self.assertIsNone(result["completion_expectation"]["observation_evidence"])

    def test_uncertain_and_missing_evidence_have_no_partial_proposal(self):
        for request, reason, status in (
            (REQUESTS[2], "TARGET_AMBIGUOUS", "clarify"),
            (REQUESTS[3], "FIXTURE_EVIDENCE_REQUIRED", "rejected"),
            ({**REQUESTS[0], "objective": "请巡检模拟冷却泵和未登记设备。"}, "TARGET_NOT_IN_FIXTURE", "clarify"),
            ({**REQUESTS[0], "map_version": "other"}, "SCENE_IDENTITY_MISMATCH", "rejected"),
            ({**REQUESTS[0], "execution_authorized": True}, "REQUEST_SHAPE_UNSUPPORTED", "rejected"),
        ):
            with self.subTest(reason=reason):
                result = candidate.build_candidate(request)
                self.assertEqual((result["status"], result["reason_code"]), (status, reason))
                self.assertIsNone(result["context"])
                self.assertIsNone(result["proposal"])
                self.assertFalse(result["execution_authorized"])

    def test_changed_fixture_identity_cannot_produce_a_candidate(self):
        edited = resource_text(candidate.FIXTURE_FILE).replace('"north_m":8', '"north_m":9', 1)
        with patch.object(candidate, "resource_text", return_value=edited):
            result = candidate.build_candidate(REQUESTS[0])
        self.assertEqual(result["reason_code"], "FIXTURE_EVIDENCE_INVALID")
        self.assertIsNone(result["proposal"])

    def test_no_pretense_of_success_with_insufficient_eligible_fixture_nodes(self):
        fixture = candidate._load_fixture()
        fixture["fleet"][0]["connected"] = False
        with patch.object(candidate, "_load_fixture", return_value=fixture):
            result = candidate.build_candidate(REQUESTS[0])
        self.assertEqual(result["reason_code"], "NO_ELIGIBLE_FIXTURE_ASSIGNMENT")
        self.assertIsNone(result["proposal"])

    def test_motion_sample_uses_uav02_and_the_scene_marker_without_claiming_observation(self):
        scene = json.loads((LAB.parents[1] / "scenarios/simple_recon_v0_1/scene.json").read_text(encoding="utf-8"))
        target = next(row for row in scene["targets"] if row["target_id"] == "target-001")
        result = candidate.build_candidate(REQUESTS[-1])
        self.assertEqual(result["purpose"], "fake_motion_only")
        self.assertEqual(result["context"]["scene_id"], scene["scene_id"])
        self.assertEqual(result["context"]["map_version"], scene["map_version"])
        self.assertEqual(result["context"]["tasks"][0]["region_id"], target["target_id"])
        self.assertEqual(result["proposal"]["assignments"][0]["actions"], ["GOTO"])
        self.assertEqual(result["proposal"]["assignments"][0]["node_id"], "UAV-02")
        self.assertEqual(result["context"]["waypoints"][-1]["position_m"], {
            "north_m": target["position"]["x_m"], "east_m": target["position"]["y_m"], "down_m": -6,
        })
        self.assertEqual(result["completion_expectation"]["mode"], "synthetic_arrival_only")
        self.assertFalse(result["completion_expectation"]["inspection_completed"])
        self.assertFalse(result["fixture_evidence"]["actual_scene_geometry_certified"])
        self.assertEqual(validate_proposal(result["context"], result["proposal"]), [])


if __name__ == "__main__":
    unittest.main()
