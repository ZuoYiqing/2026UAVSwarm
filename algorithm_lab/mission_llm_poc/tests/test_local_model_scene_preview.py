from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from uavswarm_llm_lab.bounded_catalog_choice import choose
from uavswarm_llm_lab.contracts import ContractError, digest, parse_json
from uavswarm_llm_lab.scene_selection_preview import (
    SOURCE_REF, check_choice, evaluate_scene_preview, parse_preview_objective, record_bytes, scoped_buildings,
)

LAB = Path(__file__).resolve().parents[1]
CATALOG = parse_json((LAB.parents[1] / SOURCE_REF).read_text(encoding="utf-8"))
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
        rows = scoped_buildings(CATALOG)
        self.assertEqual([(r["object_id"], r["height_m"]) for r in rows], list(zip(EXPECTED_IDS, [32.0, 22.0])))
        changed_map = {**CATALOG, "scene_identity": {**CATALOG["scene_identity"], "map_version": "not-current"}}
        with self.assertRaisesRegex(ContractError, "SCENE_PREVIEW_VERSION_MISMATCH"):
            scoped_buildings(changed_map)

    def test_explicit_height_and_absence_gate_match_the_recorded_cases(self):
        rows = scoped_buildings(CATALOG)
        check = check_choice
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

    def test_parse_intent_preserves_original_phrase_and_rejects_other_requests_before_inference(self):
        text = "请标记 北侧首排东半幅，比２０米 高１２米的那栋楼。"
        self.assertEqual(parse_preview_objective(text), ("比２０米 高１２米的那栋楼", 32))
        for other in ("请标记最高的那栋楼", text + " 再登记一栋", "南侧" + text, text + "\n"):
            model = FakeClient('{"choice":"1"}')
            with self.subTest(other=other), self.assertRaisesRegex(ContractError, "UNSUPPORTED_PREVIEW_OBJECTIVE"):
                evaluate_scene_preview(other, CATALOG, model, model_alias="test-only")
            self.assertFalse(hasattr(model, "messages"))

    def test_live_core_formats_evidence_compatibly_and_never_authorizes(self):
        for above, reply, status, expected in (
            (12, '{"choice":"1"}', "bound", EXPECTED_IDS[0]),
            (2, '{"choice":"1"}', "clarify", EXPECTED_IDS[1]),
            (27, '{"choice":"1"}', "clarify", "unknown"),
            (27, '{"choice":"unknown"}', "unknown", "unknown"),
        ):
            text = f"请登记已导出目录里，北侧首排东半幅比20米高{above}米的那栋楼。"
            preview, raw = evaluate_scene_preview(text, CATALOG, FakeClient(reply), model_alias="test-only")
            self.assertEqual(preview["status"], status)
            self.assertEqual(preview["objective"], text)
            self.assertEqual(preview["scope"]["model_response"], reply)
            self.assertEqual(raw["expected"], expected)
            self.assertEqual(preview["source"]["evidence_sha256"], hashlib.sha256(record_bytes(raw)).hexdigest())
            self.assertFalse(preview["execution_authorized"])
            self.assertFalse(raw["execution_authorized"])
            self.assertNotIn("steps", preview)
            self.assertEqual(len(preview["bindings"]), int(status == "bound"))

    def test_unexpected_model_identity_cannot_be_repackaged_as_verified(self):
        with self.assertRaisesRegex(ContractError, "MODEL_REPORT_IDENTITY_MISMATCH"):
            evaluate_scene_preview("请登记北侧首排东半幅比20米高12米的那栋楼。",
                                   CATALOG, FakeClient('{"choice":"1"}'), model_alias="other-model")
