"""Run a read-only, paired object selection check on the project scene export."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from uavswarm_llm_lab.contracts import parse_json
from uavswarm_llm_lab.local_model_client import LocalModelClient
from uavswarm_llm_lab.scene_selection_preview import evaluate_scene_preview, record_bytes


CASES = (("higher-12", 12), ("higher-2", 2), ("higher-27", 27))


def write(path, value):
    with path.open("xb") as handle:
        handle.write(record_bytes(value))


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
    model = LocalModelClient(args.local_model_url, args.model_alias, timeout_s=15)
    for tag, above in CASES:
        objective = f"请登记已导出目录里，北侧首排东半幅比20米高{above}米的那栋楼。"
        raw_name = f"{tag}.raw.json"
        preview, raw = evaluate_scene_preview(objective, catalog, model, model_alias=args.model_alias,
                                              evidence_name=raw_name, case=tag)
        write(args.output_dir / raw_name, raw)
        write(args.output_dir / f"{tag}.preview.json", preview)
        print(json.dumps({key: raw[key] for key in ("case", "model_choice", "expected", "verified", "status")},
                         ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
