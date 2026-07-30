#!/usr/bin/env python3
"""Validate a shared PX4/Gazebo/runtime scene metadata JSON file."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from uav_runtime.scenario.scene_schema import SceneValidationError, load_and_validate_scene  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate uav_runtime scene metadata")
    parser.add_argument("scene_json", help="Path to scene.json")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON summary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        _, summary = load_and_validate_scene(args.scene_json)
    except (OSError, json.JSONDecodeError, SceneValidationError) as exc:
        print(json.dumps({"validation_result": "fail", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
