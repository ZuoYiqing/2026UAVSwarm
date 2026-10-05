"""Score actual local-model grounding separately from deterministic guardrails.

All regions and positions in this corpus are synthetic. No result authorizes flight.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from .contracts import ContractError, digest
from .intent_grounder import derive_proposal, ground_with_client, request_errors
from .local_model_client import ModelError


def validate_corpus(corpus: dict) -> None:
    if not isinstance(corpus, dict) or corpus.get("corpus_version") != "0.1":
        raise ContractError("GROUNDING_CORPUS_VERSION_UNSUPPORTED")
    base = corpus.get("base_request")
    cases = corpus.get("cases")
    if not isinstance(base, dict) or not isinstance(cases, list) or not cases:
        raise ContractError("GROUNDING_CORPUS_INVALID")
    if base.get("source") != "synthetic_benchmark":
        raise ContractError("GROUNDING_CORPUS_MUST_BE_SYNTHETIC")
    known = {r["region_id"] for r in base.get("regions", []) if isinstance(r, dict)
             and isinstance(r.get("region_id"), str)}
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {
            "case_id", "objective", "expected_intent", "expected_region_ids", "expected_accept"
        }:
            raise ContractError("GROUNDING_CASE_SHAPE_INVALID")
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise ContractError("GROUNDING_CASE_ID_INVALID")
        ids.add(case_id)
        if not isinstance(case["objective"], str) or not case["objective"].strip():
            raise ContractError("GROUNDING_OBJECTIVE_INVALID:" + case_id)
        if case["expected_intent"] not in {"flight_validation", "reconnaissance"}:
            raise ContractError("GROUNDING_EXPECTED_INTENT_INVALID:" + case_id)
        regions = case["expected_region_ids"]
        if (not isinstance(regions, list) or
                not all(isinstance(r, str) and r in known for r in regions) or
                len(regions) != len(set(regions))):
            raise ContractError("GROUNDING_EXPECTED_REGIONS_INVALID:" + case_id)
        if type(case["expected_accept"]) is not bool:
            raise ContractError("GROUNDING_EXPECTED_ACCEPT_INVALID:" + case_id)
        request = deepcopy(base)
        request["mission_id"] = "grounding-eval-" + case_id
        request["objective"] = case["objective"]
        errors = request_errors(request)
        if errors:
            raise ContractError("GROUNDING_CASE_REQUEST_INVALID:" + case_id + ":" + ";".join(errors))


def run_grounding_eval(corpus: dict, client, *, seed: int = 0,
                       max_tokens: int = 1024, prompt_version: str = 'v1',
                       constrained: bool = True) -> dict:
    """One constrained model request per labelled case; preserve raw output."""
    validate_corpus(corpus)
    rows = []
    for case in corpus["cases"]:
        request = deepcopy(corpus["base_request"])
        request["mission_id"] = "grounding-eval-" + case["case_id"]
        request["objective"] = case["objective"]
        try:
            result = ground_with_client(request, client, seed=seed, max_tokens=max_tokens,
                                        prompt_version=prompt_version,
                                        constrained=constrained)
        except ModelError as exc:
            result = {"accepted": False, "candidate_grounding": None,
                      "proposal": None, "errors": [str(exc)], "model_executed": False,
                      "response_evidence": exc.response_evidence}
        candidate = result.get("candidate_grounding")
        candidate_shape_ok = isinstance(candidate, dict) and isinstance(candidate.get("bindings"), list)
        predicted_ids = ([binding.get("region_id") for binding in candidate["bindings"]]
                         if candidate_shape_ok and all(isinstance(binding, dict)
                                                       for binding in candidate["bindings"])
                         else None)
        intent_match = bool(candidate_shape_ok and
                            candidate.get("intent_type") == case["expected_intent"])
        regions_match = predicted_ids == case["expected_region_ids"]
        accepted = result.get("accepted") is True
        # An accepted proposal with incorrect semantic targets is a false success,
        # even when the expected result for that case was otherwise "accept".
        false_accept = accepted and (not case["expected_accept"] or
                                     not intent_match or not regions_match)
        rows.append({
            "case_id": case["case_id"], "objective": case["objective"],
            "expected_intent": case["expected_intent"],
            "expected_region_ids": case["expected_region_ids"],
            "expected_accept": case["expected_accept"],
            "semantic_scorable": bool(case["expected_region_ids"]),
            "candidate_intent_match": intent_match,
            "candidate_regions_match": regions_match,
            "candidate_semantic_match": intent_match and regions_match,
            "accepted": accepted,
            "acceptance_match": accepted == case["expected_accept"],
            "false_accept": false_accept,
            "result": result,
        })
    total = len(rows)
    semantic_rows = [r for r in rows if r["semantic_scorable"]]
    completed_model_calls = sum(r["result"].get("model_executed") is True for r in rows)
    return {
        "report_type": "local_grounding_benchmark",
        "model_executed": completed_model_calls > 0,
        "model_requested": client.model, "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus_hash": digest(corpus), "seed": seed,
        "sampling": getattr(client, "sampling", {"temperature": 0}),
        "prompt_version": prompt_version,
        "constrained": constrained,
        "attempted": total, "completed_model_calls": completed_model_calls,
        "semantic_scorable_cases": len(semantic_rows),
        "candidate_semantic_match_rate": (
            sum(r["candidate_semantic_match"] for r in semantic_rows) / len(semantic_rows)),
        "acceptance_match_rate": sum(r["acceptance_match"] for r in rows) / total,
        "false_accept_count": sum(r["false_accept"] for r in rows),
        "notes": ["Synthetic semantic cases; not live telemetry, route proof or flight authorization.",
                  "Candidate accuracy and validator acceptance are measured separately.",
                  "No automatic repair, fallback or retries."],
        "results": rows,
    }


def run_rule_grounding_baseline(corpus: dict) -> dict:
    """Score the exact-label rule on the same cases, without claiming model work."""
    validate_corpus(corpus)
    rows = []
    for case in corpus["cases"]:
        request = deepcopy(corpus["base_request"])
        request["mission_id"] = "grounding-eval-" + case["case_id"]
        request["objective"] = case["objective"]
        try:
            result = derive_proposal(request)
        except ContractError as exc:
            result = {"proposal": None, "grounding": None, "errors": [str(exc)]}
        grounding = result.get("grounding")
        predicted_ids = ([binding["region_id"] for binding in grounding["bindings"]]
                         if grounding else None)
        semantic_match = bool(grounding and
                              grounding["intent_type"] == case["expected_intent"] and
                              predicted_ids == case["expected_region_ids"])
        accepted = result.get("proposal") is not None and result.get("accepted", True)
        rows.append({"case_id": case["case_id"],
                     "semantic_scorable": bool(case["expected_region_ids"]),
                     "candidate_semantic_match": semantic_match,
                     "accepted": accepted,
                     "acceptance_match": accepted == case["expected_accept"],
                     "false_accept": accepted and
                     (not case["expected_accept"] or not semantic_match),
                     "reason_code": result.get("reason_code"),
                     "errors": result.get("errors", [])})
    total = len(rows)
    semantic_rows = [r for r in rows if r["semantic_scorable"]]
    return {"report_type": "rule_grounding_baseline", "model_executed": False,
            "corpus_hash": digest(corpus), "total": total,
            "semantic_scorable_cases": len(semantic_rows),
            "candidate_semantic_match_rate": (
                sum(r["candidate_semantic_match"] for r in semantic_rows) / len(semantic_rows)),
            "acceptance_match_rate": sum(r["acceptance_match"] for r in rows) / total,
            "false_accept_count": sum(r["false_accept"] for r in rows),
            "results": rows}
