from __future__ import annotations

import ast
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from uavswarm_llm_lab.intent_recognizer import (
    CatalogEntry,
    RuleIntentRecognizer,
    TEMPLATE_KEYS,
    recognize_explicit_template,
)


TESTS = Path(__file__).resolve().parent
FIXTURE = json.loads((TESTS / "fixtures" / "intent_recognition_v0.json").read_text(encoding="utf-8"))
CATALOG = tuple(CatalogEntry(**{**item, "aliases": tuple(item.get("aliases", ()))}) for item in FIXTURE["catalog"])


class IntentRecognizerTests(unittest.TestCase):
    def setUp(self):
        self.rules = RuleIntentRecognizer(CATALOG)

    def test_golden_objectives(self):
        for case in FIXTURE["cases"]:
            with self.subTest(case=case["id"]):
                result = self.rules.recognize(case["objective"])
                self.assertEqual(result.status, case["status"])
                self.assertEqual(result.mission_type, case.get("mission_type"))
                self.assertEqual(result.reason_code, case.get("reason_code", "INTENT_BOUND"))
                for key in ("targets", "reference_only", "excluded_targets"):
                    self.assertEqual([b.entity_id for b in getattr(result.parameters, key)], case.get(key, []))
                self.assertEqual(result.parameters.status_scope, case.get("status_scope"))
                self.assertEqual(result.parameters.only_listed_targets, case.get("only_listed_targets", False))
                if "evidence" in case:
                    self.assertEqual([b.evidence for b in result.parameters.targets], case["evidence"])
                if result.status == "clarify":
                    self.assertTrue(result.clarification)
                for marker in case.get("question_includes", ()):
                    self.assertIn(marker, result.clarification)

    def test_target_resolution_depends_on_supplied_catalog_not_example_sentence(self):
        objective = "巡检东侧充电棚。"
        self.assertEqual(self.rules.recognize(objective).status, "unknown")
        another_catalog = RuleIntentRecognizer((*CATALOG, CatalogEntry("OTHER-ID", "东侧充电棚")))
        result = another_catalog.recognize(objective)
        self.assertEqual(result.status, "bound")
        self.assertEqual([b.entity_id for b in result.parameters.targets], ["OTHER-ID"])

    def test_exclusivity_must_come_from_catalog(self):
        objective = "巡检东边和西边。"
        self.assertEqual(self.rules.recognize(objective).reason_code, "CONFLICTING_TARGETS")
        open_catalog = RuleIntentRecognizer(replace(e, exclusive_group=None) for e in CATALOG)
        self.assertEqual(open_catalog.recognize(objective).status, "bound")
        # A bare motion phrase still does not submit or select a movement template.
        self.assertEqual(open_catalog.recognize("去东边也去西边。").reason_code, "TASK_TYPE_REQUIRED")

    def test_all_five_explicit_keys_match_runtime_while_text_cannot_route_guarded_keys(self):
        planner = TESTS.parents[2] / "src" / "uav_runtime" / "agent" / "planner.py"
        tree = ast.parse(planner.read_text(encoding="utf-8"))
        assignment = next(node for node in tree.body if isinstance(node, ast.AnnAssign)
                          and isinstance(node.target, ast.Name) and node.target.id == "MISSION_TEMPLATES")
        self.assertEqual(TEMPLATE_KEYS, {ast.literal_eval(key) for key in assignment.value.keys})
        for key in TEMPLATE_KEYS:
            with self.subTest(template=key):
                result = recognize_explicit_template(key)
                self.assertEqual((result.status, result.mission_type), ("bound", key))
        self.assertEqual(recognize_explicit_template("not_a_template").status, "unknown")
        for objective in ("safe_stop", "fallback_hold", "查在线状态，顺便悬停", "给我停一下"):
            with self.subTest(objective=objective):
                self.assertIsNone(self.rules.recognize(objective).mission_type)

    def test_repeatability_and_no_implicit_io(self):
        # Construction and use require no model, file lookup, or network.
        with patch("socket.socket", side_effect=AssertionError("no transport")), \
                patch("pathlib.Path.open", side_effect=AssertionError("no implicit catalog I/O")), \
                patch("builtins.open", side_effect=AssertionError("no implicit model I/O")):
            reversed_catalog = RuleIntentRecognizer(reversed(CATALOG))
            for objective in ("巡检西侧光伏区。", "巡检热泵机房。", "把水表点列为目标。"):
                self.assertEqual(self.rules.recognize(objective), self.rules.recognize(objective))
                self.assertEqual(self.rules.recognize(objective), reversed_catalog.recognize(objective))
            self.assertNotEqual(self.rules.recognize("巡检西侧光伏区。").parameters,
                                self.rules.recognize("巡检热泵机房。").parameters)

    def test_unknown_suffix_or_unresolved_constraint_never_emits_partial_targets(self):
        for objective in (
            "巡检热泵机房，不要飞。",
            "巡检热泵机房。核对不明点",
            "巡检热泵机房，北仓只用来定位。 不用核对。",
            "巡检热泵机房，不用核对不明点。",
            "巡检热泵机房，不用核对北仓和不明点。",
        ):
            with self.subTest(objective=objective):
                result = self.rules.recognize(objective)
                self.assertNotEqual(result.status, "bound")
                self.assertIsNone(result.mission_type)
                self.assertFalse(result.parameters.targets)
