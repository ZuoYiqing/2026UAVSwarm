"""Project the reviewed geometry catalog into the Runtime scene document."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCENARIO = Path(__file__).resolve().parent
ENTRY_FIELDS = ("entity_id", "label", "aliases", "exclusive_group")


def build_intent_catalog(scene: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    identity_fields = ("scene_id", "map_version", "origin")
    if (
        any(catalog[key] != scene[key] for key in identity_fields)
        or catalog["frame"] != scene["public_frame"]
    ):
        raise ValueError("entity catalog does not match the active scene identity")

    slots = catalog["demo_slot_ids"]
    target_ids = {row["target_id"] for row in scene["targets"]}
    obstacle_ids = {row["obstacle_id"] for row in scene["obstacles"]}
    demo_ids = set(slots["distinct_inspection_candidates"]).union(
        slots["same_name_candidates"], slots["exclusive_candidates"],
    )
    geometry = catalog["geometry_by_entity_id"]
    preview_only = {
        entity_id for entity_id in demo_ids if geometry[entity_id]["source"] == "gazebo_visual"
    }
    reference_only = {slots["reference_only_candidate"]}
    if demo_ids - (preview_only | target_ids):
        raise ValueError("each demo slot must be a scene target or a Gazebo visual")
    if preview_only & (target_ids | obstacle_ids) or reference_only & (target_ids | demo_ids):
        raise ValueError("catalog slots overlap physical target or obstacle roles")
    if not reference_only <= obstacle_ids:
        raise ValueError("the reference slot must identify a scene obstacle")

    eligible = target_ids | preview_only | reference_only
    entries = []
    seen = set()
    for row in catalog["catalog"]:
        if row["label"] is None:
            continue
        entity_id = row["entity_id"]
        if entity_id in seen or entity_id not in geometry or entity_id not in eligible:
            raise ValueError(f"duplicate or unapproved labeled entity: {entity_id}")
        if not isinstance(row["label"], str) or not row["label"].strip():
            raise ValueError(f"invalid label for {entity_id}")
        entries.append({key: row[key] for key in ENTRY_FIELDS})
        seen.add(entity_id)

    if (demo_ids | reference_only) - seen:
        raise ValueError("a declared demonstration slot lacks reviewed semantics")

    return {
        "contract_version": "1.0",
        "scene_id": scene["scene_id"],
        "map_version": scene["map_version"],
        "catalog_id": catalog["catalog_id"],
        "entries": entries,
        "preview_only_entity_ids": [row["entity_id"] for row in entries if row["entity_id"] in preview_only],
        "reference_only_entity_ids": [row["entity_id"] for row in entries if row["entity_id"] in reference_only],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the projection to scene.json")
    args = parser.parse_args()
    scene_path = SCENARIO / "scene.json"
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    catalog = json.loads((SCENARIO / "entity_catalog.json").read_text(encoding="utf-8"))
    projection = build_intent_catalog(scene, catalog)
    if scene.get("intent_catalog") == projection:
        print("Scene intent catalog is in sync")
        return 0
    if not args.write:
        print("Scene intent catalog is out of sync. Rerun with --write.")
        return 1
    scene["intent_catalog"] = projection
    scene_path.write_text(json.dumps(scene, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
