"""CLI deliberately has no Runtime address, execute flag or flight command."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .benchmark import run_model_benchmark, run_scaffold
from .contracts import ContractError, canonical_json, digest, parse_json
from .local_model_client import LocalModelClient, ModelError
from .intent_grounder import derive_proposal, ground_with_client
from .scene_binding import bind_scene_reference
from .mission_planner import evaluate_raw, plan_with_client, reference_proposal


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Structured-input reference baseline; no LLM")
    demo.add_argument("context", type=Path)
    ground = sub.add_parser("ground", help="Derive tasks from an explicit objective and supplied affordances")
    ground.add_argument("context", type=Path)
    ground_model = sub.add_parser("ground-model", help="Candidate objective bindings from a local text model")
    ground_model.add_argument("context", type=Path)
    bind_scene = sub.add_parser("bind-scene", help="Bind an objective to physical scene entities; no waypoints")
    bind_scene.add_argument("affordances", type=Path)
    bind_scene.add_argument("objective")
    check = sub.add_parser("validate", help="Validate supplied raw model text")
    check.add_argument("context", type=Path)
    check.add_argument("response", type=Path)
    bench = sub.add_parser("benchmark", help="Scaffold checks by default")
    bench.add_argument("--local-model", action="store_true")
    infer = sub.add_parser("infer", help="Explicitly call a local text model")
    infer.add_argument("context", type=Path)
    for command in (bench, infer, ground_model):
        command.add_argument("--base-url")
        command.add_argument("--model")
        command.add_argument("--seed", type=int, default=0)
        command.add_argument("--max-tokens", type=int, default=2048)
        command.add_argument("--timeout-s", type=float, default=90)
    for command in (bench, infer):
        command.add_argument("--unconstrained", action="store_true",
                             help="Explicit raw-output comparison; never auto-fallback")
    for command in (demo, ground, ground_model, bind_scene, check, bench, infer):
        command.add_argument("--output", type=Path, help="New JSON result file; refuses overwrite")
    args = parser.parse_args(argv)
    try:
        if args.output and args.output.exists():
            raise ContractError("Output already exists; choose a new result path")
        if args.command in {"demo", "ground", "ground-model", "validate", "infer"}:
            context = parse_json(args.context.read_text(encoding="utf-8-sig"))
        if args.command == "demo":
            proposal = reference_proposal(context)
            result = {"mode": "reference_baseline", "model_executed": False,
                      "input_hash": digest(context),
                      **evaluate_raw(context, canonical_json(proposal))}
        elif args.command == "ground":
            derived = derive_proposal(context)
            result = {"mode": "objective_grounding_baseline", "model_executed": False,
                      "input_hash": digest(context), **derived,
                      "accepted": derived.get("accepted", derived["proposal"] is not None)}
        elif args.command == "ground-model":
            if not args.base_url or not args.model:
                raise ContractError("Explicit --base-url and --model are required")
            client = LocalModelClient(args.base_url, args.model, args.timeout_s)
            result = ground_with_client(context, client, seed=args.seed,
                                        max_tokens=args.max_tokens)
        elif args.command == "bind-scene":
            affordances = parse_json(args.affordances.read_text(encoding="utf-8-sig"))
            result = {"mode": "scene_reference_binding", "model_executed": False,
                      **bind_scene_reference(args.objective, affordances)}
        elif args.command == "validate":
            result = evaluate_raw(context, args.response.read_text(encoding="utf-8-sig"))
        elif args.command == "benchmark" and not args.local_model:
            result = run_scaffold()
        else:
            if not args.base_url or not args.model:
                raise ContractError("Explicit --base-url and --model are required")
            client = LocalModelClient(args.base_url, args.model, args.timeout_s)
            settings = dict(seed=args.seed, max_tokens=args.max_tokens,
                            constrained=not args.unconstrained)
            result = (run_model_benchmark(client, **settings) if args.command == "benchmark"
                      else plan_with_client(context, client, **settings))
        rendered = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(rendered + "\n")
            print(json.dumps({"output": str(args.output.resolve()),
                              "report_type": result.get("report_type", result.get("mode")),
                              "total": result.get("total"), "passed": result.get("passed")},
                             ensure_ascii=False))
        else:
            print(rendered)
        if result.get("report_type") == "scaffold_validation":
            return 0 if result["passed"] == result["total"] else 1
        if result.get("report_type") == "local_model_benchmark":
            return 0 if result["expected_status_rate"] == 1 else 1
        return 0 if result.get("accepted") else 1
    except (ContractError, ModelError, OSError, ValueError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
