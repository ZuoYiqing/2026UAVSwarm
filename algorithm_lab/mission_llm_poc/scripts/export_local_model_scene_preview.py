"""Run a read-only, paired object selection check on the project scene export."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from uavswarm_llm_lab.bounded_catalog_choice import choose
from uavswarm_llm_lab.contracts import ContractError, digest, parse_json
from uavswarm_llm_lab.local_model_client import LocalModelClient
from uavswarm_llm_lab.scene_binding import _check_affordances


CASES = (("higher-12", 12), ("higher-2", 2), ("higher-27", 27))
SOURCE_REF = "docs/fixtures/simple_recon_v0_1_scene_affordances.json"


def scoped_buildings(catalog: dict) -> list[dict]:
    _, obstacles = _check_affordances(catalog)
    identity = catalog["scene_identity"]
    if (identity["scene_id"], identity["map_version"]) != ("simple_recon_v0_1", "simple_recon_v0_1-map-1"):
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
    """An explicit numeric requirement is independently verifiable, never a guess."""
    matches = [row for row in peers if row["height_m"] == target_height_m]
    expected = "unknown" if not matches else matches[0]["object_id"] if len(matches) == 1 else "clarify"
    verified = picked == expected
    status = "bound" if verified and len(matches) == 1 else "unknown" if verified and not matches else "clarify"
    return matches, expected, verified, status


def write(path, value):
    body = (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
    with path.open("xb") as handle:
        handle.write(body)
    return hashlib.sha256(body).hexdigest()


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("catalog", type=Path)
    cli.add_argument("output_dir", type=Path)
    cli.add_argument("--local-model-url", required=True)
    cli.add_argument("--model-alias", required=True)
    args = cli.parse_args()
    if not args.output_dir.is_dir():
        cli.error("Output directory must already exist")
    for tag, _ in CASES:
        if any((args.output_dir / f"{tag}.{suffix}.json").exists() for suffix in ("raw", "preview")):
            cli.error("Refuse to overwrite prior evidence")
    catalog = parse_json(args.catalog.read_text(encoding="utf-8-sig"))
    peers = scoped_buildings(catalog)
    identity = catalog["scene_identity"]
    entities = [{"entity_id": row["object_id"], "labels": [f'{row["height_m"]:g} 米高的建筑'],
                 "description": f'建筑的已导出高度为 {row["height_m"]:g} 米。'} for row in peers]
    catalog_hash = digest(catalog)
    model = LocalModelClient(args.local_model_url, args.model_alias, timeout_s=15)
    for tag, above in CASES:
        phrase = f"比20米高{above}米的那栋楼"
        objective = f"请登记已导出目录里，北侧首排东半幅{phrase}。"
        trace = {}
        picked = choose(phrase, entities, model, trace)
        if trace.get("model_reported") != args.model_alias:
            raise ContractError("MODEL_REPORT_IDENTITY_MISMATCH")
        matches, expected, verified, status = check_choice(peers, 20 + above, picked)
        raw = {"case": tag, "objective": objective, "model": args.model_alias, "model_trace": trace,
               "rows": [{"entity_id": r["object_id"], "height_m": r["height_m"],
                         "center_east_m": r["center_east_m"], "center_north_m": r["center_north_m"]} for r in peers],
               "expected": expected, "model_choice": picked, "verified": verified, "status": status,
               "catalog_content_sha256": catalog_hash, "execution_authorized": False}
        raw_name = f"{tag}.raw.json"
        raw_hash = write(args.output_dir / raw_name, raw)
        reason = {"bound": "MODEL_CHOICE_EVIDENCE_MATCH", "unknown": "NO_MATCH_IN_EXPORTED_SCOPE",
                  "clarify": "MODEL_CHOICE_REQUIRES_REVIEW"}[status]
        preview = {
            "kind": "uavswarm-semantic-preview", "schema_version": "0.1", "execution_authorized": False,
            "source": {"kind": "local_model_scene_selection", "model_executed": True,
                       "evidence_file": raw_name, "evidence_sha256": raw_hash,
                       "catalog_file": SOURCE_REF, "catalog_content_sha256": catalog_hash,
                       "catalog_review_status": catalog["status"]},
            "scene_id": identity["scene_id"], "map_version": identity["map_version"],
            "objective": objective, "status": status, "reason_code": reason,
            "bindings": ([{"entity_id": matches[0]["object_id"], "entity_kind": "building",
                           "evidence": phrase, "source_reference": matches[0]["source"]}] if status == "bound" else []),
            "candidates": ([{"entity_id": r["object_id"], "entity_kind": "building", "height_m": r["height_m"],
                             "source_reference": r["source"]} for r in peers] if status == "clarify" else []),
            "clarification_question": "模型选择未核实；请对照导出目录明确楼栋 ID。" if status == "clarify" else None,
            "scope": {"model_alias": args.model_alias, "model_response": trace.get("model_raw_response"),
                      "verified": verified, "target_height_m": 20 + above, "reference": "only the exported northeastern first-row buildings"},
            "limitations": ["目录为部分物理导出，不能断言全地图不存在其它楼栋。",
                            "仅识别建筑，不生成或派发轨迹、航点和动作。"],
        }
        write(args.output_dir / f"{tag}.preview.json", preview)
        print(json.dumps({"case": tag, "model_choice": picked, "expected": expected,
                          "verified": verified, "status": status}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
