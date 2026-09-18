"""Reference baseline and a separately labelled optional local-model pipeline."""
from __future__ import annotations

from time import perf_counter

from .contracts import ContractError, canonical_json, digest, parse_json, resource_text, schema, schema_errors
from .semantic_validator import context_errors, eligibility_reasons, validate_proposal

LIMITATIONS = [
    "PROPOSAL_ONLY: no execution authorization",
    "GEOMETRY_NOT_VALIDATED: obstacles, no-fly zones and separation require a route planner",
    "SCHEDULING_NOT_VALIDATED: shared-node tasks require Runtime scheduling",
]


def reference_proposal(context: dict) -> dict:
    """Greedy structured-input baseline; does not understand natural language."""
    errors = context_errors(context)
    if errors:
        raise ContractError("; ".join(errors))
    result = {key: context[key] for key in
              ("schema_version", "mission_id", "snapshot_id", "scene_id",
               "map_version", "coordinate_frame")}
    result.update(execution_authorized=False, status="proposed",
                  reason_code="MISSION_PROPOSED",
                  explanation="Reference greedy allocation from structured tasks; objective text not interpreted.",
                  assignments=[], unassigned_tasks=[], warnings=list(LIMITATIONS))
    loads = {node["node_id"]: 0 for node in context["fleet"]}
    for task in sorted(context["tasks"], key=lambda t: t["task_id"]):
        eligible = [n for n in context["fleet"]
                    if not eligibility_reasons(context, n, task)]
        if eligible:
            node = min(eligible, key=lambda n: (loads[n["node_id"]], n["node_id"]))
            loads[node["node_id"]] += 1
            result["assignments"].append({
                "task_id": task["task_id"], "node_id": node["node_id"],
                "actions": list(task["required_actions"]),
                "waypoint_ids": list(task["waypoint_ids"]),
                "reason_code": "ASSIGNED",
                "explanation": "Eligible node; lowest assigned task count, then node_id.",
            })
        else:
            reasons = sorted({r for n in context["fleet"]
                              for r in eligibility_reasons(context, n, task)})
            result["unassigned_tasks"].append({
                "task_id": task["task_id"], "reason_code": "NO_ELIGIBLE_VEHICLE",
                "explanation": "No eligible node: " + (", ".join(reasons) or "empty fleet"),
            })
    too_few = sum(value > 0 for value in loads.values()) < context["constraints"]["min_vehicles"]
    if too_few or (result["unassigned_tasks"] and not context["constraints"]["allow_partial"]):
        reason = "INSUFFICIENT_FLEET" if too_few else "REQUEST_REJECTED"
        result.update(status="rejected", reason_code=reason,
                      explanation="Structured requirements cannot be satisfied by this reference allocation.",
                      assignments=[],
                      unassigned_tasks=[{"task_id": t["task_id"], "reason_code": reason,
                                         "explanation": "Mission rejected; no execution proposed."}
                                        for t in sorted(context["tasks"], key=lambda t: t["task_id"])])
    elif result["unassigned_tasks"]:
        result.update(status="degraded", reason_code="PARTIAL_MISSION",
                      explanation="Only explicitly allowed partial task allocation is proposed.")
    errors = validate_proposal(context, result)
    if errors:
        raise ContractError("Reference baseline invalid: " + "; ".join(errors))
    return result


def evaluate_raw(context: dict, raw: str, elapsed_ms: float = 0) -> dict:
    try:
        proposal = parse_json(raw)
    except ContractError as exc:
        return {"schema_valid": False, "accepted": False,
                "errors": ["INVALID_JSON: " + str(exc)],
                "candidate": None, "accepted_proposal": None, "output_hash": None}
    shape = schema_errors(proposal, "proposal")
    errors = validate_proposal(context, proposal, elapsed_ms)
    return {"schema_valid": not shape, "accepted": not errors, "errors": errors,
            "candidate": proposal, "accepted_proposal": proposal if not errors else None,
            "output_hash": digest(proposal)}


def plan_with_client(context: dict, client, *, seed: int = 0,
                     max_tokens: int = 2048, constrained: bool = True) -> dict:
    errors = context_errors(context)
    if errors:
        raise ContractError("; ".join(errors))
    system = resource_text("prompts/mission_planner_system.txt")
    output_schema = schema("proposal")
    messages = [
        {"role": "system", "content": system + "\nOutput schema:\n" + canonical_json(output_schema)},
        {"role": "user", "content": canonical_json(context)},
    ]
    started = perf_counter()
    response = client.complete(messages, output_schema, seed=seed,
                               max_tokens=max_tokens, constrained=constrained)
    elapsed_ms = (perf_counter() - started) * 1000
    result = evaluate_raw(context, response["content"], elapsed_ms)
    result.update(mode="local_model", model_requested=client.model,
                  model_reported=response["model"], usage=response["usage"],
                  raw_output=response["content"], latency_ms=elapsed_ms,
                  input_hash=digest(context), prompt_hash=digest(messages),
                  settings={"seed": seed, "temperature": 0, "max_tokens": max_tokens,
                            "constrained": constrained, "repair_attempts": 0},
                  limitations=list(LIMITATIONS), vram_peak_mib=None)
    return result
