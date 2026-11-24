"""Frozen held-out preview evaluation; does not install a model producer in Runtime."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import statistics
import subprocess
from threading import Thread
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import ProxyHandler, Request, build_opener

from jsonschema import Draft202012Validator

from uav_runtime.agent.planner import TemplateAgentPlanner
from uav_runtime.http import intent_resolution as wire, routes
from uav_runtime.http.state_store import RuntimeStateStore
from uav_runtime.runtime.vehicle_registry import VehicleRegistry
from uavswarm_llm_lab import intent_recognizer as rules
from uavswarm_llm_lab.contracts import ContractError, parse_json
from uavswarm_llm_lab.local_model_client import LocalModelClient, ModelError


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CASES = HERE / "cases.json"
PATH = "/api/planner/plan-mission"
ROLES = ("targets", "reference_only", "excluded_targets")
RESOLUTIONS = {"bound": "resolved", "clarify": "needs_clarification", "unknown": "unsupported"}
METRICS = ("complete", "order", "false_bind", "abstain")
PROMPT = (
    "只做原话到目录实体的语义绑定，不执行、不生成动作。仅使用当前目录。"
    "目标全部明确时 status=bound；并列、同名、缺可信指代或选中互斥对象时用 clarify；"
    "明确要求的对象不在目录时用 unknown。clarify 与 unknown 的 targets 必须为空，"
    "不得任选或提交部分目标。目录的 preview_only_entity_ids 仍可作为预览对象，"
    "reference_only_entity_ids 不可作为核对目标。保留原话中仅定位的 reference_only 和不核对的 excluded_targets；"
    "仅定位且不核对的对象同时保留两项。only_listed_targets 仅在原话明确限制『只』核对时为 true。"
    "多个目标有先后指令时按要求顺序输出，标 explicit_sequence；无先后词按提及顺序，标 mention_order。"
    "零或一个目标的 target_order_basis 为 null。每个 evidence 须逐字取自原话。只返回约定 JSON。"
)
ITEM = {"type": "object", "additionalProperties": False, "required": ["entity_id", "evidence"],
        "properties": {"entity_id": {"type": "string"}, "evidence": {"type": "string"}}}
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["status", *ROLES, "only_listed_targets", "target_order_basis"],
    "properties": {
        "status": {"enum": list(RESOLUTIONS)},
        **{role: {"type": "array", "items": ITEM, "maxItems": 7} for role in ROLES},
        "only_listed_targets": {"type": "boolean"},
        "target_order_basis": {"enum": ["explicit_sequence", "mention_order", None]},
    },
}
VALIDATOR = Draft202012Validator(SCHEMA)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(value, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write("\n")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def lf(data):
    return data.replace(b"\r\n", b"\n")


def file_hash(path):
    digest = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(2**20), b""):
            digest.update(block)
    return digest.hexdigest()


def assert_frozen(path, freeze):
    git_path = path.resolve().relative_to(ROOT).as_posix()
    assert lf(git("show", f"{freeze}:{git_path}")) == lf(path.read_bytes()), f"Non-frozen file: {git_path}"


def forbid(*_args, **_kwargs):
    raise AssertionError("execution, vehicle startup, and adapters are disabled in this benchmark")


@contextmanager
def open_preview():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            if self.path != PATH:
                requests.append({"path": self.path, "denied": True})
                self.send_error(403)
                return
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size < 4096:
                self.send_error(400)
                return
            body = json.loads(self.rfile.read(size))
            if set(body) != {"objective", "dry_run"} or body["dry_run"] is not True:
                self.send_error(400)
                return
            code, resp = routes.dispatch("POST", PATH, body=body)
            requests.append({"path": PATH, "http_status": code, "source": resp.get("intent_source"),
                             "execution_authorized": resp.get("execution_authorized")})
            payload = json.dumps(resp, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    with ExitStack() as guard, ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        for owner, method in ((routes, "plans_execute"), (routes, "_execute_flight_action"),
                              (VehicleRegistry, "start_vehicle")):
            guard.enter_context(patch.object(owner, method, forbid))
        planner = TemplateAgentPlanner(audit=SimpleNamespace(append=lambda _: None))
        guard.enter_context(patch.object(routes, "TemplateAgentPlanner", lambda: planner))
        guard.enter_context(patch.object(routes, "RUNTIME_STATE_STORE", RuntimeStateStore(
            vehicle_registry=routes.VEHICLE_REGISTRY,
        )))
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        endpoint = f"http://127.0.0.1:{server.server_port}{PATH}"

        def preview(objective):
            req = Request(endpoint, canonical({"objective": objective, "dry_run": True}),
                          {"Content-Type": "application/json"}, method="POST")
            with build_opener(ProxyHandler({})).open(req, timeout=15) as response:
                reply = json.load(response)
            assert reply["execution_authorized"] is False
            assert reply["plan"] is None or reply["plan"]["preview_binding"]["steps_are_outline"] is True
            return reply

        try:
            yield preview, requests
        finally:
            server.shutdown()
            worker.join(timeout=2)


def ids(output, role):
    return [b["entity_id"] for b in output[role]]


def has_raw_binding(candidate):
    # Count a structured attempt even when the candidate is inconsistent or rejected.
    return isinstance(candidate, dict) and isinstance(candidate.get("targets"), list) and bool(candidate["targets"])


def validate(candidate, objective, catalog):
    errors = sorted(err.message for err in VALIDATOR.iter_errors(candidate))
    if errors:
        return errors
    entries = {row["entity_id"]: row for row in catalog["entries"]}
    for role in ROLES:
        selected = ids(candidate, role)
        if len(set(selected)) != len(selected) or not set(selected) <= entries.keys():
            errors.append(f"{role}:duplicate_or_unknown_id")
        if any(not b["evidence"].strip() or b["evidence"] not in objective for b in candidate[role]):
            errors.append(f"{role}:evidence_not_verbatim")
    target = ids(candidate, "targets")
    others = set(ids(candidate, "reference_only") + ids(candidate, "excluded_targets"))
    if bool(target) != (candidate["status"] == "bound"):
        errors.append("status_target_inconsistent")
    if set(target) & (others | set(catalog["reference_only_entity_ids"])):
        errors.append("prohibited_target_role")
    groups = [entries[t]["exclusive_group"] for t in target if t in entries and entries[t]["exclusive_group"]]
    if len(groups) != len(set(groups)):
        errors.append("conflicting_exclusive_group")
    if (candidate["target_order_basis"] is not None) != (len(target) > 1):
        errors.append("target_order_basis_inconsistent")
    return errors


class ModelResolution(wire.PreviewIntentResolution):
    @property
    def intent_source(self):
        return "local_model"


def model_into_preview(candidate, errors, objective, preview):
    def convert(received_objective, *, scene_id, scene):
        assert received_objective == objective
        if errors:
            return wire.PreviewIntentResolution("unsupported", "EVAL_CANDIDATE_INVALID")
        catalog = wire._catalog_from_scene(scene_id, scene)
        params = rules.IntentParameters(
            **{role: tuple(rules.Binding(**b) for b in candidate[role]) for role in ROLES},
            only_listed_targets=candidate["only_listed_targets"],
            target_order_basis=candidate["target_order_basis"],
        )
        return ModelResolution(
            RESOLUTIONS[candidate["status"]], "EVAL_LOCAL_MODEL_CANDIDATE",
            mission_type="inspection_snapshot" if candidate["status"] == "bound" else None,
            parameters=params, catalog=catalog,
        )
    with patch.object(routes, "resolve_preview_intent", convert):
        return preview(objective)


def adjudicate(case, original, errors, response):
    gold = case["expected"]
    intent = response["intent_resolution"]
    if errors:
        assert response["plan"] is None
        prediction = None
    else:
        assert intent["status"] == RESOLUTIONS[original["status"]]
        projection = intent["bindings"]
        # Mixed role lists can be split in HTTP. Never reconstruct order by
        # concatenating the physical and preview-only arrays.
        assert sorted(ids(original, "targets")) == sorted(ids(projection, "targets") + ids(projection, "preview_only_targets"))
        for role in ROLES[1:]:
            assert ids(original, role) == ids(projection, role)
        assert original["only_listed_targets"] == projection["only_listed_targets"]
        prediction = original
    differences = [f"gate:{e}" for e in errors]
    if prediction:
        if prediction["status"] != gold["status"]:
            differences.append(f"status:{prediction['status']} instead of {gold['status']}")
        for role in ROLES:
            if sorted(ids(prediction, role)) != sorted(gold[role]):
                differences.append(f"{role}:expected={gold[role]},actual={ids(prediction, role)}")
        if prediction["only_listed_targets"] != gold["only_listed_targets"]:
            differences.append("only_listed_targets:mismatch")
    answerable = gold["status"] == "bound"
    complete = answerable and prediction is not None and not differences
    ordered = answerable and len(gold["targets"]) > 1
    order_correct = (ordered and complete and ids(prediction, "targets") == gold["targets"]
                     and prediction["target_order_basis"] == gold["target_order_basis"])
    if ordered and complete and not order_correct:
        differences.append("requested_order_or_basis:mismatch")
    abstain = answerable and prediction is not None and prediction["status"] in {"clarify", "unknown"}
    false = gold["status"] == "clarify" and has_raw_binding(original)
    if false:
        differences.append("positive_binding_when_clarification_required")
    return {
        "prediction": prediction, "differences": differences,
        "metrics": {"complete": complete if answerable else None, "order": order_correct if ordered else None,
                    "false_bind": false if gold["status"] == "clarify" else None, "abstain": abstain if answerable else None},
        "invalid": prediction is None, "answerable_other_failure": answerable and not complete and not abstain,
        "admitted_false_binding": gold["status"] == "clarify" and bool(
            intent["bindings"]["targets"] or intent["bindings"]["preview_only_targets"]),
    }


def spread(values):
    return [min(values), statistics.median(values), max(values)]


def summarize(rows):
    totals = {}
    for name in METRICS:
        values = [r["grading"]["metrics"][name] for r in rows if r["grading"]["metrics"][name] is not None]
        totals[name] = [sum(values), len(values)]
    return {"counts": totals, "latency_ms_min_median_max": spread([r["elapsed_ms"] for r in rows]),
            "invalid": sum(r["grading"]["invalid"] for r in rows),
            "answerable_other_failure": sum(r["grading"]["answerable_other_failure"] for r in rows),
            "admitted_false_binding": sum(r["grading"]["admitted_false_binding"] for r in rows),
            "status_distribution": dict(Counter(
                r["grading"]["prediction"]["status"] if r["grading"]["prediction"] is not None else "invalid" for r in rows
            ))}


def start(args):
    assert git("rev-parse", "HEAD").decode().strip() == args.freeze_commit
    for item in (CASES, Path(__file__), Path(rules.__file__), ROOT / "scenarios/simple_recon_v0_1/scene.json"):
        assert_frozen(item, args.freeze_commit)
    deck = json.loads(CASES.read_bytes())
    catalog = routes.VEHICLE_REGISTRY.scene["intent_catalog"]
    assert len(catalog["entries"]) == 7 and sha256(canonical(catalog)).hexdigest() == deck["catalog_sha256"]
    assert [item["target_id"] for item in routes.VEHICLE_REGISTRY.scene["targets"]] == ["target-001"]
    assert sha256(lf(Path(rules.__file__).read_bytes())).hexdigest() == deck["rules_sha256_lf"]
    assert Counter(c["category"] for c in deck["cases"]) == dict.fromkeys(
        ["literal", "paraphrase", "clarification", "negation"], 5)
    assert len({c["objective"] for c in deck["cases"]}) == 20
    launch = json.loads(args.launch_record.read_text(encoding="utf-8-sig"))
    profile = deck["model"]
    assert launch["model_alias"] == profile["id"] and launch["model_profile"] == profile["profile"]
    assert launch["offline_flag"] is True and launch["startup_status"] == "ready"
    assert file_hash(launch["model"]) == profile["weights_sha256"]
    assert "llama-b10964" in launch["executable"] and "--reasoning" in launch["arguments"]
    command = launch["arguments"]
    assert command[command.index("--ctx-size") + 1] == str(profile["context_tokens"])
    assert command[command.index("--reasoning") + 1] == "off" and "--offline" in command
    client = LocalModelClient(f"http://127.0.0.1:{launch['port']}/v1", profile["id"], timeout_s=45,
                              sampling_temperature=profile["temperature"])
    return deck, catalog, client


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--freeze-commit", required=True)
    cli.add_argument("--launch-record", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    deck, catalog, client = start(args)
    args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    traces = {}

    class RecordedRules(rules.RuleIntentRecognizer):
        def recognize(self, objective, **kwargs):
            result = super().recognize(objective, **kwargs)
            params = result.parameters
            traces[objective] = {
                "status": result.status,
                **{role: [asdict(b) for b in getattr(params, role)] for role in ROLES},
                "only_listed_targets": params.only_listed_targets,
                "target_order_basis": params.target_order_basis,
            }
            return result

    with ((args.output / "responses.jsonl").open("x", encoding="utf-8", newline="\n") as output,
          open_preview() as (preview, requests),
          patch.object(wire, "RuleIntentRecognizer", RecordedRules),
          patch.object(wire, "CatalogEntry", rules.CatalogEntry),
          patch.object(wire, "IntentParameters", rules.IntentParameters)):
        def record(case, arm, seed, original, errors, http, ms, raw=None, inference_ms=None):
            grade = adjudicate(case, original, errors, http)
            row = {**case, "arm": arm, "seed": seed, "original_candidate": original, "model_reply": raw,
                   "http_preview": http, "grading": grade, "elapsed_ms": ms, "inference_ms": inference_ms}
            rows.append(row)
            output.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            output.flush()
            print(f'{arm} {seed if seed is not None else "-"} {case["id"]} '
                  f'{grade["prediction"]["status"] if grade["prediction"] else "invalid"} {ms:.0f}ms', flush=True)

        for case in deck["cases"]:
            objective = case["objective"]
            t = perf_counter()
            response = preview(objective)
            raw_rule = traces[objective]
            # We keep the actual rule response. In these held-out cases there
            # must not be an intrinsically invalid rule output.
            errors = validate(raw_rule, objective, catalog)
            record(case, "rules", None, raw_rule, errors, response, (perf_counter() - t) * 1000)
        for seed in deck["model"]["seeds"]:
            for case in deck["cases"]:
                objective = case["objective"]
                messages = [{"role": "system", "content": PROMPT},
                            {"role": "user", "content": canonical({"objective": objective, "catalog": catalog}).decode()}]
                t = perf_counter()
                raw, original = None, None
                try:
                    raw = client.complete(messages, SCHEMA, seed=seed, max_tokens=deck["model"]["max_tokens"], constrained=True)
                    original = parse_json(raw["content"])
                    errors = validate(original, objective, catalog)
                except (ModelError, ContractError) as error:
                    raw = raw if raw is not None else getattr(error, "response_evidence", None)
                    errors = [str(error)]
                infer_ms = (perf_counter() - t) * 1000
                response = model_into_preview(original, errors, objective, preview)
                record(case, "model", seed, original, errors, response, (perf_counter() - t) * 1000,
                       raw=raw, inference_ms=infer_ms)
    base = summarize([r for r in rows if r["arm"] == "rules"])
    model = [r for r in rows if r["arm"] == "model"]
    seeds = deck["model"]["seeds"]
    by_seed = {str(s): summarize([r for r in model if r["seed"] == s]) for s in seeds}
    distribution = {name: spread([m["counts"][name][0] for m in by_seed.values()]) for name in METRICS}
    safe = distribution["false_bind"][2] <= base["counts"]["false_bind"][0]
    improvements = [name for name in ("complete", "order") if distribution[name][1] > base["counts"][name][0]]
    if distribution["false_bind"][1] < base["counts"]["false_bind"][0]:
        improvements.append("false_bind")
    if (distribution["abstain"][1] < base["counts"]["abstain"][0]
            and statistics.median(m["answerable_other_failure"] for m in by_seed.values()) <= base["answerable_other_failure"]):
        improvements.append("abstain")
    assert len(requests) == len(rows) == 20 * (1 + len(seeds))
    assert all(r["path"] == PATH and r["execution_authorized"] is False for r in requests)
    write_json(args.output / "report.json", {
        "freeze_commit": args.freeze_commit, "corpus_sha256_lf": sha256(lf(CASES.read_bytes())).hexdigest(),
        "benchmark_id": deck["benchmark_id"], "catalog_sha256": deck["catalog_sha256"],
        "rules_sha256_lf": deck["rules_sha256_lf"], "model": deck["model"],
        "model_samples_per_case": len(seeds), "model_requests": len(model), "rules_samples_per_case": 1,
        "runtime_preview_requests": len(requests), "execution_authorized": False, "model_adapter_experiment_only": True,
        "rules": base, "model_pooled": summarize(model), "model_by_seed": by_seed,
        "model_per_seed_count_min_median_max": distribution,
        "model_inference_ms_min_median_max": spread([r["inference_ms"] for r in model]),
        "model_per_case": {c["id"]: summarize([r for r in model if r["id"] == c["id"]]) for c in deck["cases"]},
        "improvements_before_safety_gate": improvements, "no_increase_in_false_bind_for_any_seed": safe,
        "net_gain": bool(improvements and safe),
    })
    print("REPORT", args.output / "report.json", flush=True)


if __name__ == "__main__":
    main()
