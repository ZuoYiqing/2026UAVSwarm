"""Serve the read-only algorithm lab preview against an already running local model."""
from __future__ import annotations

import argparse
from pathlib import Path

from uavswarm_llm_lab.contracts import parse_json
from uavswarm_llm_lab.local_model_client import LocalModelClient
from uavswarm_llm_lab.preview_server import make_preview_server
from uavswarm_llm_lab.scene_selection_preview import SOURCE_REF


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path(__file__).resolve().parents[3] / SOURCE_REF)
    parser.add_argument("--local-model-url", default="http://127.0.0.1:18116/v1")
    parser.add_argument("--model-alias", default="qwen3.5-0.8b-q4-lab")
    parser.add_argument("--port", type=int, default=18118)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be in 1024..65535")
    catalog = parse_json(args.catalog.read_text(encoding="utf-8-sig"))
    model = LocalModelClient(args.local_model_url, args.model_alias, timeout_s=15)
    with make_preview_server(catalog, model, model_alias=args.model_alias, port=args.port) as server:
        print(f"Read-only preview: http://127.0.0.1:{server.server_port}/lab/semantic-preview", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
