"""Offline mission-allocation and abstract multi-agent game benches."""
from __future__ import annotations

import argparse
import hashlib
import json
from importlib.resources import files
from pathlib import Path

from . import board_coordination_eval, platform_coordination_eval
from .contracts import ContractError, canonical_json, digest, parse_json
from .local_model_client import LocalModelClient, ModelError


SUITES = {"mission": platform_coordination_eval, "board": board_coordination_eval}


def dataset(suite: str) -> tuple[dict, dict]:
    lab = SUITES.get(suite)
    if lab is None:
        raise ContractError("COORDINATION_SUITE_UNKNOWN")
    raw = files("uavswarm_llm_lab").joinpath(lab.FILES).read_bytes()
    content = parse_json(raw.decode("utf-8"))
    return content, {"version": content["benchmark_version"], "content_sha256": digest(content),
                     "file_sha256": hashlib.sha256(raw).hexdigest()}


def evaluate(suite: str, method: str, client=None) -> dict:
    data, identity = dataset(suite)
    calls = 0

    def model_call(system, public, schema, limit):
        nonlocal calls
        calls += 1
        messages = [{"role": "system", "content": system}, {"role": "user", "content": canonical_json(public)}]
        trace = {"messages": messages, "response_schema": schema, "max_tokens": limit}
        try:
            envelope = client.complete(messages, schema, seed=0, max_tokens=limit, constrained=True)
            trace.update(model_raw_response=envelope["content"], model_reported=envelope.get("model"))
            if envelope.get("model") != client.model:
                raise ContractError("MODEL_REPORT_IDENTITY_MISMATCH")
            return parse_json(envelope["content"]), trace
        except (ContractError, ModelError) as exc:
            trace["error"] = str(exc)
            trace["response_evidence"] = getattr(exc, "response_evidence", None)
            return None, trace

    lab = SUITES[suite]
    details = lab.evaluate(data, method, model_call if client is not None else None)
    return {
        "suite": suite, "dataset": identity, "method": method, "model_calls_attempted": calls,
        "model_requested": client.model if client is not None else None,
        "model_settings": {"seed": 0, "temperature": 0, "schema_constrained": True} if client is not None else None,
        "execution_authorized": False, **details,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=SUITES, required=True)
    parser.add_argument("--method", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-url")
    parser.add_argument("--model-id")
    args = parser.parse_args()
    if args.method not in SUITES[args.suite].METHODS:
        parser.error("methods for this suite: " + ", ".join(SUITES[args.suite].METHODS))
    model = args.method.startswith("model")
    if (model and not (args.model_url and args.model_id)) or (not model and (args.model_url or args.model_id)):
        parser.error("model methods require both --model-url and --model-id; other methods accept neither")
    if args.output.exists() or not args.output.parent.is_dir():
        parser.error("output must be a new file in an existing directory")
    client = LocalModelClient(args.model_url, args.model_id, timeout_s=15) if model else None
    result = evaluate(args.suite, args.method, client)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(result, output, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        output.write("\n")
    print(canonical_json({key: result[key] for key in ("suite", "dataset", "method", "metrics", "model_calls_attempted")}))


if __name__ == "__main__":
    main()
