"""Exercise the Runtime request parser only; never import routes or submit a plan."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from uav_runtime.http.schemas import PlanExecuteRequest, RequestValidationError


def load_fake(path: Path) -> dict:
    record = json.loads(path.read_text(encoding="utf-8-sig"))
    if record.get("scope") != "fake_adapter_only" or record.get("execution_authorized") is not False:
        raise ValueError("Expected a non-authorizing Fake Adapter proof")
    return record


def check(candidate_report: dict, mapping_report: dict) -> dict:
    if candidate_report["baseline"] != mapping_report["baseline"] or mapping_report.get("requests_sent") != 0:
        raise ValueError("The reports must have the same baseline and no network submissions")
    patrols = [row["result"] for row in candidate_report["cases"]
               if row["result"].get("purpose") == "fake_equipment_inspection"]
    if not patrols:
        raise ValueError("Missing inspection candidate")
    for patrol in patrols:
        try:
            PlanExecuteRequest.from_json({"plan": patrol["proposal"]})
        except RequestValidationError as exc:
            if exc.field != "plan.plan_id":
                raise
        else:
            raise AssertionError("A patrol proposal was accepted as a Runtime plan")

    motion = [row["fixture_shape"] for row in mapping_report["checked"]
              if row.get("converter_status") == "fake_motion_shape_only"]
    if len(motion) != 1:
        raise ValueError("Expected exactly one Fake motion shape")
    shape = motion[0]
    if (shape.get("execution_authorized") is not False or shape.get("scope") != "fake_adapter_only"
            or shape.get("mission_type") != "flight_validation"
            or len(shape.get("steps", [])) != 2
            or any(step.get("action_type") != "goto" or step.get("node_id") != "UAV-02" for step in shape["steps"])):
        raise ValueError("The motion shape must be the isolated UAV-02 example")
    # Exercise only the parser, using an explicit rejection; never send its input.
    parsed = PlanExecuteRequest.from_json({"plan": shape, "operator_id": "fixture-reviewer", "decision": "reject"})
    if parsed.decision != "reject" or parsed.plan["plan_id"] != shape["plan_id"]:
        raise AssertionError("Runtime parser did not preserve the rejection and plan identity")
    return {
        "baseline": candidate_report["baseline"], "scope": "fake_adapter_only",
        "direct_proposal_rejected_at": "plan.plan_id", "inspections_checked": len(patrols),
        "fake_motion_shape_parse_only": True, "fake_plan_id": shape["plan_id"],
        "parser_decision": parsed.decision, "runtime_actions_submitted": 0, "execution_authorized": False,
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("candidates", type=Path)
    cli.add_argument("mapping", type=Path)
    cli.add_argument("output", type=Path)
    args = cli.parse_args()
    proof = check(load_fake(args.candidates), load_fake(args.mapping))
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(proof, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(proof))


if __name__ == "__main__":
    main()
