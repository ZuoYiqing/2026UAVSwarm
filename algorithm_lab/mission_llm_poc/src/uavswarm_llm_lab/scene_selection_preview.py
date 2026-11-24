"""Read-only selection in a pinned subset of the lab's exported building catalog."""
from __future__ import annotations

import hashlib
import json
import re

from .bounded_catalog_choice import choose
from .contracts import ContractError, digest
from .scene_binding import _check_affordances


SOURCE_REF = "docs/fixtures/simple_recon_v0_1_scene_affordances.json"
SCENE_ID = "simple_recon_v0_1"
MAP_VERSION = "simple_recon_v0_1-map-1"
MAX_OBJECTIVE_CHARS = 160
_OBJECTIVE = re.compile(
    r"请?[ \t]*(?:登记|标记)[ \t]*(?:已导出目录里[，,][ \t]*)?"
    r"北侧首排东半幅[ \t]*[，,]?[ \t]*"
    r"(?P<phrase>比[ \t]*[2２][0０][ \t]*米[ \t]*高[ \t]*"
    r"(?P<above>[0-9０-９]{1,3})[ \t]*米[ \t]*的那栋楼)[。.]?"
)


def parse_preview_objective(objective: str) -> tuple[str, int]:
    """Accept the whole supported sentence; never ignore trailing instructions."""
    if not isinstance(objective, str) or not 1 <= len(objective) <= MAX_OBJECTIVE_CHARS:
        raise ContractError("INVALID_PREVIEW_OBJECTIVE")
    match = _OBJECTIVE.fullmatch(objective.strip(" \t"))
    if not match:
        raise ContractError("UNSUPPORTED_PREVIEW_OBJECTIVE")
    return match["phrase"], 20 + int(match["above"])


def scoped_buildings(catalog: dict) -> list[dict]:
    _, obstacles = _check_affordances(catalog)
    identity = catalog["scene_identity"]
    if (identity["scene_id"], identity["map_version"]) != (SCENE_ID, MAP_VERSION):
        raise ContractError("SCENE_PREVIEW_VERSION_MISMATCH")
    north_rows = [row["center_north_m"] for row in obstacles if row["center_north_m"] > 0]
    if not north_rows:
        raise ContractError("UNRESOLVED_SCENE_PREVIEW_SCOPE")
    first_north = min(north_rows)
    peers = sorted((row for row in obstacles if row["center_north_m"] == first_north and row["center_east_m"] > 0),
                   key=lambda row: row["object_id"])
    if not 1 <= len(peers) <= 3:
        raise ContractError("UNRESOLVED_SCENE_PREVIEW_SCOPE")
    return peers


def check_choice(peers: list[dict], target_height_m: int, picked: str) -> tuple[list[dict], str, bool, str]:
    """Use catalog facts, independently of the model's selected candidate."""
    matches = [row for row in peers if row["height_m"] == target_height_m]
    expected = "unknown" if not matches else matches[0]["object_id"] if len(matches) == 1 else "clarify"
    verified = picked == expected
    status = "bound" if verified and len(matches) == 1 else "unknown" if verified and not matches else "clarify"
    return matches, expected, verified, status


def record_bytes(record: dict) -> bytes:
    return (json.dumps(record, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")


def evaluate_scene_preview(
    objective: str, catalog: dict, client, *, model_alias: str,
    evidence_name: str = "live-evidence.raw.json", case: str = "local-preview",
) -> tuple[dict, dict]:
    """Return the existing preview shape and matching evidence; never return execution data."""
    phrase, target_height_m = parse_preview_objective(objective)
    peers = scoped_buildings(catalog)
    catalog_hash = digest(catalog)
    choices = [{"entity_id": row["object_id"], "labels": [f'{row["height_m"]:g} 米高的建筑'],
                "description": f'建筑的已导出高度为 {row["height_m"]:g} 米。'} for row in peers]
    trace: dict = {}
    picked = choose(phrase, choices, client, trace)
    if trace.get("model_reported") != model_alias:
        raise ContractError("MODEL_REPORT_IDENTITY_MISMATCH")
    matches, expected, verified, status = check_choice(peers, target_height_m, picked)
    raw = {"case": case, "objective": objective, "model": model_alias, "model_trace": trace,
           "rows": [{"entity_id": r["object_id"], "height_m": r["height_m"],
                     "center_east_m": r["center_east_m"], "center_north_m": r["center_north_m"]} for r in peers],
           "expected": expected, "model_choice": picked, "verified": verified, "status": status,
           "catalog_content_sha256": catalog_hash, "execution_authorized": False}
    reasons = {"bound": "MODEL_CHOICE_EVIDENCE_MATCH", "unknown": "NO_MATCH_IN_EXPORTED_SCOPE",
               "clarify": "AMBIGUOUS_EXPORTED_MATCH" if verified else "MODEL_CHOICE_REQUIRES_REVIEW"}
    preview = {
        "kind": "uavswarm-semantic-preview", "schema_version": "0.1", "execution_authorized": False,
        "source": {"kind": "local_model_scene_selection", "model_executed": True,
                   "evidence_file": evidence_name, "evidence_sha256": hashlib.sha256(record_bytes(raw)).hexdigest(),
                   "catalog_file": SOURCE_REF, "catalog_content_sha256": catalog_hash,
                   "catalog_review_status": catalog["status"]},
        "scene_id": SCENE_ID, "map_version": MAP_VERSION, "objective": objective, "status": status,
        "reason_code": reasons[status],
        "bindings": ([{"entity_id": matches[0]["object_id"], "entity_kind": "building",
                       "evidence": phrase, "source_reference": matches[0]["source"]}] if status == "bound" else []),
        "candidates": ([{"entity_id": r["object_id"], "entity_kind": "building", "height_m": r["height_m"],
                         "source_reference": r["source"]} for r in (matches if verified else peers)]
                       if status == "clarify" else []),
        "clarification_question": (
            ("有多个楼栋符合高度；请提供楼栋 ID。" if verified else "模型选择未核实；请对照导出目录明确楼栋 ID。")
            if status == "clarify" else None
        ),
        "scope": {"model_alias": model_alias, "model_response": trace["model_raw_response"],
                  "verified": verified, "target_height_m": target_height_m,
                  "reference": "only the exported northeastern first-row buildings"},
        "limitations": ["目录为部分物理导出，不能断言全地图不存在其它楼栋。",
                        "仅识别建筑，不生成或派发轨迹、航点和动作。"],
    }
    return preview, raw
