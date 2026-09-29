"""Ground a bounded natural-language objective to supplied region/waypoint IDs.

This is an auditable baseline, not free-form navigation or a geometry planner.
"""
from __future__ import annotations

from copy import deepcopy
from time import perf_counter

from jsonschema import Draft202012Validator

from .contracts import ContractError, canonical_json, digest, parse_json, schema
from .mission_planner import reference_proposal
from .semantic_validator import context_errors


FLIGHT_ACTIONS = ["TAKEOFF", "GOTO", "LAND"]
RECON_ACTIONS = ["TAKEOFF", "GOTO", "OBSERVE", "RETURN_HOME", "LAND"]
GROUNDING_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["intent_type", "bindings", "explanation"],
    "properties": {
        "intent_type": {"enum": ["flight_validation", "reconnaissance"]},
        "bindings": {"type": "array", "minItems": 1, "maxItems": 100,
                     "items": {"type": "object", "additionalProperties": False,
                               "required": ["region_id", "matched_text"],
                               "properties": {
                                   "region_id": {"type": "string", "minLength": 1},
                                   "matched_text": {"type": "string", "minLength": 1},
                               }}},
        "explanation": {"type": "string", "minLength": 1, "maxLength": 2048},
    },
}


def request_schema() -> dict:
    """Keep the existing context fields, replacing authoritative tasks with affordances."""
    result = deepcopy(schema("context"))
    result["required"] = [key for key in result["required"] if key != "tasks"] + ["regions"]
    del result["properties"]["tasks"]
    result["properties"]["regions"] = {
        "type": "array", "minItems": 1, "maxItems": 100,
        "items": {
            "type": "object", "additionalProperties": False,
            "required": ["region_id", "labels", "waypoint_ids", "source_reference"],
            "properties": {
                "region_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$"},
                "labels": {"type": "array", "minItems": 1, "maxItems": 20,
                           "uniqueItems": True,
                           "items": {"type": "string", "minLength": 1, "maxLength": 256}},
                "waypoint_ids": {"type": "array", "minItems": 1, "maxItems": 100,
                                 "uniqueItems": True,
                                 "items": {"type": "string", "minLength": 1}},
                "source_reference": {"type": "string", "minLength": 1, "maxLength": 512},
            },
        },
    }
    return result


def request_errors(request: dict) -> list[str]:
    if not isinstance(request, dict):
        return ["INTENT_REQUEST_NOT_OBJECT"]
    if "tasks" in request:
        return ["EXTERNAL_TASKS_FORBIDDEN: objective is authoritative; clarify conflicts"]
    shape = sorted(f"{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message}"
                   for e in Draft202012Validator(request_schema()).iter_errors(request))
    if shape:
        return ["INTENT_REQUEST_SCHEMA: " + item for item in shape]
    region_ids = [r["region_id"] for r in request["regions"]]
    if len(region_ids) != len(set(region_ids)):
        return ["DUPLICATE_REGION_ID"]
    known_waypoints = {w["waypoint_id"] for w in request["waypoints"]}
    for region in request["regions"]:
        for waypoint_id in region["waypoint_ids"]:
            if waypoint_id not in known_waypoints:
                return ["UNKNOWN_REGION_WAYPOINT:" + region["region_id"] + ":" + waypoint_id]
    # Reuse all existing geometry-frame, TTL, fleet and waypoint checks.
    provisional = {key: deepcopy(value) for key, value in request.items() if key != "regions"}
    provisional["tasks"] = [{"task_id": f"CHECK-{index + 1}",
                             "region_id": region["region_id"],
                             "required_actions": ["GOTO"],
                             "waypoint_ids": region["waypoint_ids"]}
                            for index, region in enumerate(request["regions"])]
    return context_errors(provisional)


def _intent_type(objective: str) -> str:
    lowered = objective.casefold()
    flight = any(term in lowered for term in ("飞行验证", "flight validation"))
    recon = any(term in lowered for term in ("巡检", "侦察", "reconnaissance", "inspection"))
    if flight == recon:
        raise ContractError("OBJECTIVE_INTENT_AMBIGUOUS: specify flight validation or reconnaissance")
    if flight:
        profiles = (("起飞", "前往", "降落"), ("takeoff", "goto", "land"))
        if not any(all(term in lowered for term in profile) and
                   [lowered.index(term) for term in profile] ==
                   sorted(lowered.index(term) for term in profile)
                   for profile in profiles):
            raise ContractError("FLIGHT_ACTION_SEQUENCE_UNCLEAR: require explicit takeoff, goto, land order")
        if any(negation in lowered for negation in
               ("不降落", "不要降落", "禁止降落", "不前往", "不要前往", "不要起飞", "禁止起飞")):
            raise ContractError("FLIGHT_ACTION_CONTRADICTION: explicit negative action")
    return "flight_validation" if flight else "reconnaissance"


def derive_context(request: dict) -> tuple[dict, dict]:
    """Match explicit supplied labels only; reject absent or ambiguous references."""
    errors = request_errors(request)
    if errors:
        raise ContractError("; ".join(errors))
    intent_type = _intent_type(request["objective"])
    objective = request["objective"].casefold()
    matches = []
    for region in request["regions"]:
        phrases = [label for label in region["labels"] if label.casefold() in objective]
        if phrases:
            earliest = min(objective.index(label.casefold()) for label in phrases)
            matches.append((earliest, region, sorted(phrases, key=lambda s: (-len(s), s))[0]))
    if not matches:
        raise ContractError("REGION_REFERENCE_UNRESOLVED: no supplied label occurs in objective")
    positions = [row[0] for row in matches]
    if len(positions) != len(set(positions)):
        raise ContractError("REGION_REFERENCE_AMBIGUOUS: overlapping labels need clarification")
    matches.sort(key=lambda row: (row[0], row[1]["region_id"]))
    return _compile_context(request, matches, intent_type)


def _compile_context(request: dict, matches: list[tuple], intent_type: str) -> tuple[dict, dict]:
    actions = FLIGHT_ACTIONS if intent_type == "flight_validation" else RECON_ACTIONS
    context = {key: deepcopy(value) for key, value in request.items() if key != "regions"}
    context["tasks"] = [{"task_id": f"TASK-{index + 1}",
                         "region_id": region["region_id"],
                         "required_actions": list(actions),
                         "waypoint_ids": list(region["waypoint_ids"])}
                        for index, (_, region, _) in enumerate(matches)]
    errors = context_errors(context)
    if errors:
        raise ContractError("; ".join(errors))
    report = {
        "authority": "objective", "intent_type": intent_type,
        "bindings": [{"task_id": f"TASK-{index + 1}", "region_id": region["region_id"],
                      "matched_text": phrase, "waypoint_ids": list(region["waypoint_ids"]),
                      "source_reference": region["source_reference"]}
                     for index, (_, region, phrase) in enumerate(matches)],
        "limitations": ["Labels and waypoint candidates were supplied; no unseen place names are inferred.",
                        "No geometry, payload, timing or real-time execution readiness is proven."],
    }
    return context, report


def derive_proposal(request: dict) -> dict:
    context, grounding = derive_context(request)
    proposal = reference_proposal(context)
    proposal["explanation"] = ("Tasks derived from objective by exact supplied-label grounding; "
                               "node allocation used the reference greedy baseline.")
    proposal["warnings"].append(
        "INTENT_GROUNDING_LIMITED: only supplied labels and waypoint candidates were used")
    if request["source"] == "synthetic_benchmark":
        proposal["warnings"].append(
            "SYNTHETIC_SNAPSHOT: fleet fields are test assumptions, not live telemetry")
    return {"context": context, "grounding": grounding,
            "proposal": proposal, "execution_ready": False}


def ground_with_client(request: dict, client, *, seed: int = 0,
                       max_tokens: int = 512) -> dict:
    """Ask a local model for semantic bindings; reject invented IDs and stale input.

    Non-exact semantic bindings remain review candidates, never execution authority.
    """
    errors = request_errors(request)
    if errors:
        raise ContractError("; ".join(errors))
    choices = [{"region_id": r["region_id"], "labels": r["labels"]}
               for r in request["regions"]]
    messages = [
        {"role": "system", "content": (
            "Return JSON only. Identify the requested intent and ordered region IDs from "
            "the supplied choices. matched_text must be copied exactly from the objective. "
            "Do not invent region IDs, actions, coordinates, or claim route safety.")},
        {"role": "user", "content": canonical_json(
            {"objective": request["objective"], "choices": choices})},
    ]
    started = perf_counter()
    response = client.complete(messages, GROUNDING_SCHEMA, seed=seed,
                               max_tokens=max_tokens, constrained=True)
    elapsed_ms = (perf_counter() - started) * 1000
    raw = response["content"]
    base = {"mode": "local_model_intent_grounding", "model_executed": True,
            "model_requested": client.model, "model_reported": response["model"],
            "usage": response["usage"], "raw_output": raw,
            "input_hash": digest(request), "prompt_hash": digest(messages),
            "latency_ms": elapsed_ms, "execution_ready": False,
            "settings": {"seed": seed, "temperature": 0,
                         "max_tokens": max_tokens, "constrained": True,
                         "repair_attempts": 0},
            "accepted": False, "context": None, "proposal": None,
            "output_hash": None}
    try:
        candidate = parse_json(raw)
    except ContractError as exc:
        return {**base, "errors": ["INVALID_JSON: " + str(exc)], "candidate_grounding": None}
    base["candidate_grounding"] = candidate
    base["output_hash"] = digest(candidate)
    shape = sorted(f"{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message}"
                   for e in Draft202012Validator(GROUNDING_SCHEMA).iter_errors(candidate))
    if shape:
        return {**base, "errors": ["GROUNDING_SCHEMA: " + item for item in shape]}
    errors = []
    try:
        expected_intent = _intent_type(request["objective"])
    except ContractError as exc:
        errors.append(str(exc))
        expected_intent = None
    if candidate["intent_type"] != expected_intent:
        errors.append("INTENT_TYPE_MISMATCH")
    regions = {r["region_id"]: r for r in request["regions"]}
    seen = set()
    matches = []
    objective = request["objective"]
    for binding in candidate["bindings"]:
        region_id, phrase = binding["region_id"], binding["matched_text"]
        if region_id not in regions:
            errors.append("UNKNOWN_REGION_ID:" + region_id)
        if region_id in seen:
            errors.append("DUPLICATE_REGION_ID:" + region_id)
        if phrase not in objective:
            errors.append("MATCHED_TEXT_NOT_IN_OBJECTIVE:" + region_id)
        seen.add(region_id)
        if region_id in regions and phrase in objective:
            matches.append((objective.index(phrase), regions[region_id], phrase))
    if matches != sorted(matches, key=lambda row: (row[0], row[1]["region_id"])):
        errors.append("REGION_ORDER_MISMATCH")
    if errors:
        return {**base, "errors": sorted(set(errors))}
    try:
        context, grounding = _compile_context(request, matches, candidate["intent_type"])
        expiry = context_errors(context, elapsed_ms)
        if expiry:
            raise ContractError("; ".join(expiry))
        proposal = reference_proposal(context)
    except ContractError as exc:
        return {**base, "errors": [str(exc)]}
    exact = all(any(phrase.casefold() == label.casefold()
                    for label in region["labels"])
                for _, region, phrase in matches)
    grounding["method"] = "local_model_candidate"
    grounding["requires_human_semantic_review"] = not exact
    if not exact:
        return {**base, "errors": ["SEMANTIC_BINDING_REVIEW_REQUIRED"],
                "grounding": grounding, "context": context}
    proposal["explanation"] = ("Local model proposed objective-to-region bindings; "
                               "reference greedy baseline allocated nodes.")
    proposal["warnings"].append("MODEL_GROUNDING_CANDIDATE: semantic meaning requires review")
    if request["source"] == "synthetic_benchmark":
        proposal["warnings"].append("SYNTHETIC_SNAPSHOT: not live telemetry")
    return {**base, "accepted": True, "errors": [], "context": context,
            "grounding": grounding, "proposal": proposal}
