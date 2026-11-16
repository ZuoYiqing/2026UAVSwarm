import copy
import json
import unittest
from pathlib import Path

from landing_assessment_lab import ContractError, assess


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class LandingEvidenceTests(unittest.TestCase):
    def test_rooftop_contact_is_not_scene_ground(self):
        result = assess(fixture("roof_contact.json"))
        self.assertEqual(result["status"], "criteria_not_met")
        self.assertEqual(result["reason_codes"], ["GROUND_HEIGHT_MISMATCH"])
        self.assertIsNone(result["confidence"])
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["task_completed"])

    def test_known_scene_ground_is_criteria_only(self):
        result = assess(fixture("ground_contact.json"))
        self.assertEqual(result["status"], "criteria_met")
        self.assertEqual(result["surface_safety"], "unknown")
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["task_completed"])

    def test_missing_calibration_is_unknown(self):
        result = assess(fixture("missing_calibration.json"))
        self.assertEqual((result["status"], result["reason_codes"]),
                         ("unknown", ["CALIBRATION_UNAVAILABLE"]))

    def test_stale_samples_are_unknown(self):
        result = assess(fixture("stale_samples.json"))
        self.assertEqual((result["status"], result["reason_codes"]),
                         ("unknown", ["SAMPLE_STALE_OR_FUTURE"]))

    def test_unknown_surface_stays_unknown_with_short_range(self):
        result = assess(fixture("unknown_surface.json"))
        self.assertEqual((result["status"], result["reason_codes"]),
                         ("unknown", ["SURFACE_SUPPORT_UNOBSERVED"]))
        self.assertIsNone(result["confidence"])

    def test_scene_mismatch_and_missing_position_do_not_become_success(self):
        request = fixture("ground_contact.json")
        request["observation"]["calibration"]["map_version"] = "old-map"
        self.assertEqual(assess(request)["reason_codes"], ["SCENE_BINDING_MISMATCH"])
        request["observation"]["calibration"]["map_version"] = request["goal"]["map_version"]
        request["observation"]["samples"][1]["position_scene_ned_m"] = None
        self.assertEqual(assess(request)["reason_codes"], ["SCENE_POSITION_UNAVAILABLE"])

    def test_incomplete_window_and_clock_errors_are_unknown(self):
        request = fixture("ground_contact.json")
        request["observation"]["samples"] = request["observation"]["samples"][:2]
        self.assertEqual(assess(request)["reason_codes"], ["STABLE_WINDOW_INSUFFICIENT"])
        request = fixture("ground_contact.json")
        request["observation"]["samples"][2]["t_s"] = 10.3
        self.assertEqual(assess(request)["reason_codes"], ["SAMPLE_TIME_NOT_INCREASING"])
        request["observation"]["samples"][2]["t_s"] = 11.0
        self.assertEqual(assess(request)["reason_codes"], ["SAMPLE_STALE_OR_FUTURE"])

    def test_contract_rejects_ambiguous_or_invalid_values(self):
        base = fixture("ground_contact.json")
        cases = [
            ("extra", lambda r: r.update(extra="hidden")),
            ("bool_position", lambda r: r["observation"]["samples"][0]["position_scene_ned_m"].update(down_m=True)),
            ("nan", lambda r: r["goal"].update(vertical_tolerance_m=float("nan"))),
            ("duplicate", lambda r: r["observation"]["samples"][1].update(sample_id="s1")),
            ("wrong_frame", lambda r: r["observation"]["calibration"].update(frame="vehicle_local_ned")),
            ("unsupported_kind", lambda r: r["goal"].update(kind="designated_pad")),
        ]
        for name, change in cases:
            with self.subTest(name=name):
                request = copy.deepcopy(base)
                change(request)
                with self.assertRaises(ContractError):
                    assess(request)

    def test_deterministic_and_correlation_preserved(self):
        request = fixture("ground_contact.json")
        first = assess(request)
        reordered = dict(reversed(list(request.items())))
        self.assertEqual(first, assess(reordered))
        self.assertEqual(first["correlation"], request["correlation"])
        self.assertEqual(len(first["input_sha256"]), 64)

    def test_versioned_schemas_and_fixtures_parse(self):
        for path in SCHEMAS.glob("*.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertFalse(schema["additionalProperties"])
        for path in FIXTURES.glob("*.json"):
            self.assertEqual(assess(fixture(path.name))["contract_version"],
                             "landing_assessment_proposal_v0.1")

    def test_versioned_roof_output_matches_baseline(self):
        expected = json.loads((EXAMPLES / "roof_assessment_result.json").read_text(encoding="utf-8"))
        self.assertEqual(assess(fixture("roof_contact.json")), expected)
