"""Ground a bounded natural-language objective to supplied region/waypoint IDs.

This is an auditable baseline, not free-form navigation or a geometry planner.
"""
from __future__ import annotations

from copy import deepcopy
import re
from time import perf_counter

from jsonschema import Draft202012Validator

from .contracts import ContractError, canonical_json, digest, parse_json, schema
from .mission_planner import reference_proposal
from .semantic_validator import context_errors


FLIGHT_ACTIONS = ["TAKEOFF", "GOTO", "LAND"]
RECON_ACTIONS = ["TAKEOFF", "GOTO", "OBSERVE", "RETURN_HOME", "LAND"]
EXCLUSION_PREFIXES = ("不要去", "不去", "别去", "避开", "不要前往", "禁止前往")
NON_TARGET_ROLES = ("背景地标", "背景", "参照物", "参照", "参考点", "参考")
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


def _excluded_region_ids(request: dict) -> list[str]:
    """Do not silently turn an explicitly excluded region into a positive task."""
    objective = request["objective"]
    excluded = []
    for region in request["regions"]:
        if any(re.search(re.escape(prefix) + r"\s*" + re.escape(label), objective,
                         flags=re.IGNORECASE)
               for prefix in EXCLUSION_PREFIXES for label in region["labels"]):
            excluded.append(region["region_id"])
    return sorted(excluded)


def _non_target_region_ids(request: dict) -> list[str]:
    """Recognize explicit background roles; reject unfamiliar role wording.

    This is intentionally bounded. A label's mere occurrence is not proof that it
    is a destination, and an unparsed role cue must not be silently ignored.
    """
    objective = request["objective"]
    ignored = []
    recognized_spans = []
    for region in request["regions"]:
        for label in region["labels"]:
            match = re.search(re.escape(label) + r"\s*(?:只是|仅是|仅作为|只作为|只是作为)\s*(?:背景地标|背景|参照物|参照|参考点|参考)",
                              objective, flags=re.IGNORECASE)
            if match:
                if re.search(r"(?:前往|到|去|巡检|搜索)\s*" + re.escape(label),
                             objective, flags=re.IGNORECASE):
                    raise ContractError("OBJECTIVE_REGION_ROLE_CONTRADICTION:" + region["region_id"])
                ignored.append(region["region_id"])
                recognized_spans.append(match.span())
                break
    cue_pattern = "|".join(re.escape(cue) for cue in NON_TARGET_ROLES)
    if any(not any(start <= cue.start() < end for start, end in recognized_spans)
           for cue in re.finditer(cue_pattern, objective)):
        raise ContractError("OBJECTIVE_REGION_ROLE_AMBIGUOUS: clarify background references")
    return sorted(ignored)


def derive_context(request: dict) -> tuple[dict, dict]:
    """Match explicit supplied labels only; reject absent or ambiguous references."""
    errors = request_errors(request)
    if errors:
        raise ContractError("; ".join(errors))
    excluded = _excluded_region_ids(request)
    if excluded:
        raise ContractError("OBJECTIVE_EXCLUSION_UNREPRESENTABLE:" + ",".join(excluded))
    non_targets = set(_non_target_region_ids(request))
    intent_type = _intent_type(request["objective"])
    objective = request["objective"].casefold()
    matches = []
    for region in request["regions"]:
        if region["region_id"] in non_targets:
            continue
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
    if isinstance(request, dict) and "tasks" in request:
        return {"context": None, "grounding": None, "proposal": None,
                "execution_ready": False, "accepted": False,
                "reason_code": "EXTERNAL_TASKS_FORBIDDEN",
                "clarification_request": {
                    "audience": "originating_operator",
                    "mission_id": request.get("mission_id"),
                    "conflicting_fields": ["objective", "tasks"],
                    "question": "请确认原始任务目标并重新提交；任务清单将由目标派生。",
                    "resolution": "resubmit_objective_without_tasks",
                }}
    context, grounding = derive_context(request)
    if grounding["intent_type"] == "reconnaissance":
        return {"context": context, "grounding": grounding, "proposal": None,
                "execution_ready": False, "accepted": False,
                "reason_code": "PERCEPTION_EXECUTION_UNAVAILABLE",
                "blocking_requirements": ["OBSERVE_ENDPOINT_NOT_IMPLEMENTED",
                                          "CAMERA_CAPABILITY_UNCONFIRMED"]}
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
                       max_tokens: int = 512, prompt_version: str = 'v1',
                       constrained: bool = True) -> dict:
    """Ask a local model for semantic bindings; reject invented IDs and stale input.

    Non-exact semantic bindings remain review candidates, never execution authority.
    """
    errors = request_errors(request)
    if errors:
        raise ContractError("; ".join(errors))
    if prompt_version not in {'v1', 'selective_v2'}:
        raise ContractError('UNKNOWN_GROUNDING_PROMPT_VERSION')
    if type(constrained) is not bool:
        raise ContractError('GROUNDING_CONSTRAINT_MODE_INVALID')
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
    if prompt_version == 'selective_v2':
        # Explicit opt-in development ablation. Never rewrite a model response.
        messages[0]['content'] = (
            '只输出JSON。choices是候选字典，不是要执行的目的地清单。'
            '只选择objective实际要求前往或巡检的区域，禁止把所有候选全部输出。'
            'bindings按objective要求的访问先后排序，每个region_id最多出现一次。'
            'matched_text只复制objective里的区域名称短语，不含前往、起飞、巡检等动词。'
            '如果区域名称恰好等于候选label，就逐字复制这个label。'
            '禁止去某区不等于要求去该区，排除该区域；未知区域不能替换成已知区域。'
            '巡检或观察用reconnaissance；仅飞行验证用flight_validation。'
            '例如候选甲区和乙区：只去乙区只输出乙区；先乙后甲按乙甲排序。'
            '不生成动作、坐标或安全结论。explanation用一句简短说明。'
        )
    started = perf_counter()
    response = client.complete(messages, GROUNDING_SCHEMA, seed=seed,
                               max_tokens=max_tokens, constrained=constrained)
    elapsed_ms = (perf_counter() - started) * 1000
    raw = response["content"]
    base = {"mode": "local_model_intent_grounding", "model_executed": True,
            "model_requested": client.model, "model_reported": response["model"],
            "usage": response["usage"], "raw_output": raw,
            "input_hash": digest(request), "prompt_hash": digest(messages),
            "latency_ms": elapsed_ms, "execution_ready": False,
            "settings": {"seed": seed, **getattr(client, "sampling", {"temperature": 0}),
                         "max_tokens": max_tokens, "constrained": constrained,
                         "prompt_version": prompt_version,
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
    excluded = _excluded_region_ids(request)
    if excluded:
        return {**base, "errors": ["OBJECTIVE_EXCLUSION_UNREPRESENTABLE:" +
                                    ",".join(excluded)]}
    try:
        non_targets = set(_non_target_region_ids(request))
    except ContractError as exc:
        return {**base, "errors": [str(exc)]}
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
        if region_id in non_targets:
            errors.append("NON_TARGET_REGION_SELECTED:" + region_id)
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
    if candidate["intent_type"] == "reconnaissance":
        return {**base, "errors": [], "reason_code": "PERCEPTION_EXECUTION_UNAVAILABLE",
                "blocking_requirements": ["OBSERVE_ENDPOINT_NOT_IMPLEMENTED",
                                          "CAMERA_CAPABILITY_UNCONFIRMED"],
                "grounding": grounding, "context": context}
    try:
        proposal = reference_proposal(context)
    except ContractError as exc:
        return {**base, "errors": [str(exc)]}
    proposal["explanation"] = ("Local model proposed objective-to-region bindings; "
                               "reference greedy baseline allocated nodes.")
    proposal["warnings"].append("MODEL_GROUNDING_CANDIDATE: semantic meaning requires review")
    if request["source"] == "synthetic_benchmark":
        proposal["warnings"].append("SYNTHETIC_SNAPSHOT: not live telemetry")
    return {**base, "accepted": True, "errors": [], "context": context,
            "grounding": grounding, "proposal": proposal}
