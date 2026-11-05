"""Run a local candidate service or one reproducible, offline evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .candidate import decide
from .contracts import MAX_JSON_BYTES, parse_json, utc_time
from .local_model import LocalInferenceClient, ModelFailure
from .server import serve


def main() -> None:
    parser = argparse.ArgumentParser(prog="platform_candidate_lab")
    sub = parser.add_subparsers(dest="mode", required=True)
    validation = sub.add_parser("validate", help="deterministic fixture validation; no model")
    validation.add_argument("--input", type=Path, required=True)
    validation.add_argument("--at", required=True, help="explicit ISO8601 UTC evaluation time")
    validation.add_argument("--model-output-file", type=Path)
    validation.add_argument("--model-failure", choices=["MODEL_TIMEOUT", "MODEL_UNAVAILABLE"])
    validation.add_argument("--allow-fake", action="store_true")
    for mode in ("serve", "evaluate"):
        command = sub.add_parser(mode)
        command.add_argument("--model-url", required=True,
                             help="loopback inference endpoint ending /v1/chat/completions")
        command.add_argument("--model-id", required=True)
        command.add_argument("--allow-fake", action="store_true",
                             help="opt in to fake telemetry for offline lab tests")
        if mode == "serve":
            command.add_argument("--port", type=int, default=8872)
        else:
            command.add_argument("--input", type=Path, required=True)
            command.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "serve":
        client = LocalInferenceClient(args.model_url, args.model_id)
        serve(client, port=args.port, allow_fake=args.allow_fake)
        return
    with args.input.open("rb") as source:
        request = parse_json(source.read(MAX_JSON_BYTES + 1))
    if args.mode == "validate":
        if bool(args.model_output_file) == bool(args.model_failure):
            parser.error("set exactly one of --model-output-file or --model-failure")

        class StaticModel:
            model = "fixture-static-model"

            def complete(self, messages, output_schema, *, timeout_s):
                if args.model_failure:
                    raise ModelFailure(args.model_failure)
                with args.model_output_file.open("r", encoding="utf-8") as reply:
                    return {"content": reply.read()}

        result = decide(request, StaticModel(), now=utc_time(args.at, "EVALUATION_TIME"),
                        allow_fake=args.allow_fake)
    else:
        client = LocalInferenceClient(args.model_url, args.model_id)
        result = decide(request, client, allow_fake=args.allow_fake)
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True,
                         indent=2, allow_nan=False) + "\n"
    if args.mode == "validate" or args.output is None:
        print(encoded, end="")
    else:
        # An existing experiment record is immutable.
        with args.output.open("x", encoding="utf-8") as target:
            target.write(encoded)


if __name__ == "__main__":
    main()
