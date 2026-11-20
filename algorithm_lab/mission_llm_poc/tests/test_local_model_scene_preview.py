from __future__ import annotations

import runpy
import unittest
from pathlib import Path

from uavswarm_llm_lab.bounded_catalog_choice import choose
from uavswarm_llm_lab.contracts import ContractError, digest, parse_json

LAB = Path(__file__).resolve().parents[1]
DEMO = runpy.run_path(str(LAB / "scripts" / "export_local_model_scene_preview.py"))
CATALOG = parse_json((LAB.parents[1] / DEMO["SOURCE_REF"]).read_text(encoding="utf-8"))
EXPECTED_IDS = ["link-block-4-3-2-0", "link-block-4-3-3-0"]


class FakeClient:
    def __init__(self, response):
        self.response = response

    def complete(self, messages, schema, **kwargs):
        self.messages = messages
        self.schema = schema
        self.options = kwargs
        return {"content": self.response, "model": "test-only"}


class ScenePreviewTests(unittest.TestCase):
    def test_actual_catalog_scope_uses_fixed_geometry_not_model_ids(self):
        rows = DEMO["scoped_buildings"](CATALOG)
        self.assertEqual([(r["object_id"], r["height_m"]) for r in rows], list(zip(EXPECTED_IDS, [32.0, 22.0])))
        changed_map = {**CATALOG, "scene_identity": {**CATALOG["scene_identity"], "map_version": "not-current"}}
        with self.assertRaisesRegex(ContractError, "SCENE_PREVIEW_VERSION_MISMATCH"):
            DEMO["scoped_buildings"](changed_map)

    def test_explicit_height_and_absence_gate_match_the_recorded_cases(self):
        rows = DEMO["scoped_buildings"](CATALOG)
        check = DEMO["check_choice"]
        self.assertEqual(check(rows, 32, EXPECTED_IDS[0])[1:], (EXPECTED_IDS[0], True, "bound"))
        self.assertEqual(check(rows, 22, EXPECTED_IDS[0])[1:], (EXPECTED_IDS[1], False, "clarify"))
        self.assertEqual(check(rows, 47, EXPECTED_IDS[0])[1:], ("unknown", False, "clarify"))
        self.assertEqual(check(rows, 47, "unknown")[1:], ("unknown", True, "unknown"))
        tied = rows + [{"object_id": "another-32", "height_m": 32.0}]
        self.assertEqual(check(tied, 32, EXPECTED_IDS[0])[1:], ("clarify", False, "clarify"))

    def test_choice_request_does_not_disclose_ids_or_accept_extra_fields(self):
        items = [{"entity_id": i, "labels": [str(h)], "description": str(h)}
                 for i, h in zip(EXPECTED_IDS, (32, 22))]
        stub = FakeClient('{"choice":"1"}')
        trace: dict = {}
        self.assertEqual(choose("比20米高12米的那栋楼", items, stub, trace), EXPECTED_IDS[0])
        self.assertEqual(stub.schema["properties"]["choice"]["enum"], ["1", "2", "clarify", "unknown"])
        self.assertEqual(stub.options, {"seed": 0, "max_tokens": 32, "constrained": True})
        self.assertNotIn(EXPECTED_IDS[0], stub.messages[1]["content"])
        self.assertEqual(trace["prompt_sha256"], digest(stub.messages))
        self.assertEqual(trace["model_raw_response"], '{"choice":"1"}')
        for invalid in ('{"choice":"5"}', '{"choice":"1","extra":true}', '{"choice":1}'):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ContractError, "CHOICE_OUTSIDE_PINNED_SCHEMA"):
                choose("比20米高12米的那栋楼", items, FakeClient(invalid), {})
