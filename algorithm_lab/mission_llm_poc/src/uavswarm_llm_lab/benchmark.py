"""Scaffold checks and real-model measurements have separate reports."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from .contracts import canonical_json, digest, parse_json, resource_text
from .local_model_client import ModelError
from .mission_planner import evaluate_raw, plan_with_client, reference_proposal
from .semantic_validator import context_errors


def cases() -> list[dict]:
    return [parse_json(line) for line in resource_text(
        "benchmarks/uav_mission_cases_v0_1.jsonl").splitlines() if line.strip()]


def apply_changes(value: dict, changes: list) -> dict:
    """Data-only fixture patches, never executable expressions."""
    value = deepcopy(value)
    for change in changes:
        path = change["path"]
        parent = value
        for key in path[:-1]:
            parent = parent[key]
        key = path[-1]
        if change["op"] == "set":
            parent[key] = deepcopy(change["value"])
        elif change["op"] == "remove":
            del parent[key]
        else:
            raise ValueError("Unsupported fixture operation")
    return value


def case_context(case: dict) -> dict:
    return apply_changes(parse_json(resource_text("benchmarks/base_context.json")),
                         case["context_changes"])


def run_scaffold() -> dict:
    results = []
    corpus = cases()
    for case in corpus:
        context = case_context(case)
        errors = context_errors(context)
        if case["kind"] == "invalid_input":
            passed = any(e.startswith(case["expected_error"]) for e in errors)
            row = {"case_id": case["case_id"], "kind": case["kind"],
                   "passed": passed, "errors": errors}
        else:
            candidate = reference_proposal(context)
            raw = case.get("raw_response", canonical_json(apply_changes(
                candidate, case.get("proposal_changes", []))))
            evaluation = evaluate_raw(context, raw)
            if case["kind"] == "mission":
                passed = (evaluation["accepted"] and
                          evaluation["candidate"]["status"] == case["expected_status"])
            else:
                passed = (not evaluation["accepted"] and any(
                    e.startswith(case["expected_error"]) for e in evaluation["errors"]))
            row = {"case_id": case["case_id"], "kind": case["kind"],
                   "passed": passed, **evaluation}
        results.append(row)
    return {"report_type": "scaffold_validation", "model_executed": False,
            "model_quality_metrics": None, "created_at": datetime.now(timezone.utc).isoformat(),
            "corpus_hash": digest(corpus),
            "total": len(results), "passed": sum(r["passed"] for r in results),
            "results": results}


def run_model_benchmark(client, *, seed: int = 0, max_tokens: int = 2048,
                        constrained: bool = True) -> dict:
    """Mission cases only; validator mutations are never counted as model runs."""
    results = []
    corpus = cases()
    for case in corpus:
        if case["kind"] != "mission":
            continue
        context = case_context(case)
        try:
            result = plan_with_client(context, client, seed=seed,
                                      max_tokens=max_tokens, constrained=constrained)
        except ModelError as exc:
            result = {"accepted": False, "schema_valid": False,
                      "errors": [str(exc)], "candidate": None,
                      "accepted_proposal": None}
        candidate = result["candidate"]
        correct_status = bool(result["accepted"] and candidate
                              and candidate["status"] == case["expected_status"])
        results.append({"case_id": case["case_id"],
                        "expected_status": case["expected_status"],
                        "status_match": correct_status, **result})
    count = len(results)
    return {"report_type": "local_model_benchmark", "model_executed": True,
            "model_requested": client.model, "corpus_hash": digest(corpus),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "attempted": count,
            "schema_valid_rate": sum(r["schema_valid"] for r in results) / count,
            "semantic_acceptance_rate": sum(r["accepted"] for r in results) / count,
            "expected_status_rate": sum(r["status_match"] for r in results) / count,
            "natural_language_intent_accuracy": None, "vram_peak_mib": None,
            "note": "Structured task constraints only. Human review of objective interpretation remains required. No repair attempts.",
            "results": results}
