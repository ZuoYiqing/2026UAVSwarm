"""Compare the frozen A-v0.4 draft on offline, non-authorizing preview paths."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import statistics
import subprocess
from threading import Thread
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import ProxyHandler, Request, build_opener

from jsonschema import Draft202012Validator

from uavswarm_llm_lab.contracts import ContractError, parse_json
from uavswarm_llm_lab.local_model_client import LocalModelClient, ModelError
from uav_runtime.agent._vendor_intent_recognizer_v0 import (
    Binding, CatalogEntry, IntentParameters, RuleIntentRecognizer,
)
from uav_runtime.agent.planner import TemplateAgentPlanner
from uav_runtime.http import routes
from uav_runtime.http.intent_resolution import PreviewIntentResolution, _catalog_from_scene
from uav_runtime.http.state_store import RuntimeStateStore
from uav_runtime.runtime.vehicle_registry import VehicleRegistry


LAB = Path(__file__).resolve().parents[1]
BASELINE = "46de1b79940d13c9aeb991c48897e93f7222ac9a"
DRAFT = LAB / "docs/ANCHORING_A_V04_SWARM_GAME_DRAFT.md"
CASE_LINE = re.compile(r"^\| ([SG]0[1-6]) [^|]+\| ([^|]+?) \| `(bound|clarify|unknown) \[([^\]]*)\]`", re.M)
ROLES = ("bindings", "reference_only", "excluded_targets")
TO_RUNTIME = {"bound": "resolved", "clarify": "needs_clarification", "unknown": "unsupported"}
FROM_RUNTIME = {v: k for k, v in TO_RUNTIME.items()}
PREVIEW_PATH = "/api/planner/plan-mission"
SEED, MAX_TOKENS = 0, 384


def entity(entity_id, label, aliases=(), **attributes):
    return {"entity_id": entity_id, "label": label, "aliases": list(aliases), **attributes}


# All names and descriptions come from the two published draft catalogs, not
# from candidate answers. The existing rule uses explicit strings, not score attributes.
CATALOGS = {
    "S": {
        "scene_id": "demo-campus-v1", "map_version": "a-v04-draft-semantic-v1",
        "entities": [
            entity("S-PV-W", "西侧光伏区", ["园区西面一排用于发电的太阳能板"]),
            entity("S-THERM", "热泵机房"),
            entity("S-STORE-N", "北仓"),
            entity("S-METER-A", "访客入口水表点", ["水表点"], location="访客入口"),
            entity("S-METER-B", "展厅门外水表点", ["水表点"], location="展厅门外"),
        ],
    },
    "G": {
        "scene_id": "demo-scoreboard-v1", "map_version": "a-v04-draft-semantic-v1",
        "entities": [
            entity("G-BLUE", "蓝方记分台"),
            entity("G-TRI", "三角牌", ["有三条边的牌"], sides=3),
            entity("G-CENTER", "中央计分格"),
            entity("G-BONUS-E", "东侧奖励格", ["奖励格"], direction="东", points=2),
            entity("G-BONUS-W", "西侧奖励格", ["奖励格"], direction="西", points=2),
            entity("G-GALLERY", "观众席记分页"),
        ],
    },
}
BINDING_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["entity_id", "evidence"],
    "properties": {"entity_id": {"type": "string"}, "evidence": {"type": "string"}},
}
MODEL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["status", *ROLES, "only_listed_targets"],
    "properties": {
        "status": {"enum": ["bound", "clarify", "unknown"]},
        **{r: {"type": "array", "items": BINDING_SCHEMA, "maxItems": 8} for r in ROLES},
        "only_listed_targets": {"type": "boolean"},
    },
}
INSTRUCTION = (
    "只做文本中的实体指代和范围识别，不执行、不生成动作或路线。只使用当题目录；"
    "找出原话要求核对或记录的全部实体，不绑定背景赛况、仅用于定位的参照或明确排除项。"
    "根据原话的先后要求排列 bindings，不能按名词出现顺序替代指令顺序。"
    "若全部目标唯一可辨，返回 bound；任一明确必需目标不在目录，返回 unknown；"
    "若有并列、同名或指代不足，返回 clarify。unknown 与 clarify 的 bindings 都须为空。"
    "有明确定位参照时放入 reference_only，参考且不核对的实体也放入 excluded_targets。"
    "只有明确限制只核对或只记录所列目标时，only_listed_targets 为 true。"
    "各项 entity_id 只能取目录值；evidence 必须逐字摘自 objective 的相关原话，不改写。"
    "只输出符合约束的 JSON，不复述指令。"
)


def write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")


def actual_cases(source):
    cases = [
        {"id": key, "objective": text, "expected_status": status,
         "expected_ids": [item.strip() for item in ids.split(",") if item.strip()]}
        for key, text, status, ids in CASE_LINE.findall(source)
    ]
    if [row["id"] for row in cases] != [f"{p}0{i}" for p in "SG" for i in range(1, 7)]:
        raise ValueError("The draft does not contain the expected 12 original objectives")
    return cases


def forbid(*args, **kwargs):
    raise AssertionError("execution or vehicle startup reached during preview evaluation")


@contextmanager
def preview_http():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            if self.path != PREVIEW_PATH:
                requests.append({"method": "POST", "path": self.path, "denied": True})
                self.send_error(403)
                return
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 < n <= 4096:
                self.send_error(400)
                return
            request = json.loads(self.rfile.read(n))
            if set(request) != {"objective", "dry_run"} or request["dry_run"] is not True:
                self.send_error(400)
                return
            status, body = routes.dispatch("POST", self.path, body=request)
            requests.append({"method": "POST", "path": self.path, "http_status": status,
                             "intent_source": body.get("intent_source"),
                             "execution_authorized": body.get("execution_authorized")})
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    planner = TemplateAgentPlanner(audit=SimpleNamespace(append=lambda _: None))
    with ExitStack() as guard, ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        for owner, name in ((routes, "plans_execute"), (routes, "_execute_flight_action"),
                            (VehicleRegistry, "start_vehicle")):
            guard.enter_context(patch.object(owner, name, forbid))
        guard.enter_context(patch.object(routes, "TemplateAgentPlanner", lambda: planner))
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        url = f"http://127.0.0.1:{server.server_port}{PREVIEW_PATH}"

        def preview(text):
            payload = {"objective": text, "dry_run": True}
            req = Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
            with build_opener(ProxyHandler({})).open(req, timeout=15) as response:
                body = json.load(response)
            assert body["execution_authorized"] is False
            assert body["plan"] is None or body["plan"]["preview_binding"]["steps_are_outline"] is True
            return body

        try:
            yield preview, requests
        finally:
            server.shutdown()
            worker.join(timeout=2)


def campus_registry():
    common = CATALOGS["S"]
    scene = {k: common[k] for k in ("scene_id", "map_version")}
    scene.update(targets=[], obstacles=[], intent_catalog={
        **scene, "contract_version": "1.0", "catalog_id": common["scene_id"],
        "entries": common["entities"],
        "preview_only_entity_ids": [e["entity_id"] for e in common["entities"]],
        "reference_only_entity_ids": [],
    })
    registry = VehicleRegistry(scene_id=scene["scene_id"])
    registry.scene = scene
    return registry


def from_http(body):
    intent = body["intent_resolution"]
    params = intent["bindings"]
    return {
        "status": FROM_RUNTIME[intent["status"]],
        "bindings": params["targets"] + params["preview_only_targets"],
        **{role: params[role] for role in ROLES[1:]},
        "only_listed_targets": params["only_listed_targets"],
        "reason": intent["reason_code"],
    }


def check_model(candidate, objective, catalog):
    errors = sorted(e.message for e in Draft202012Validator(MODEL_SCHEMA).iter_errors(candidate))
    if errors:
        return errors
    known = {row["entity_id"] for row in catalog["entities"]}
    for role in ROLES:
        bindings = candidate[role]
        ids = [row["entity_id"] for row in bindings]
        if len(ids) != len(set(ids)) or not set(ids) <= known:
            errors.append(f"non_unique_or_unknown_entity:{role}")
        if any(not row["evidence"].strip() or row["evidence"] not in objective for row in bindings):
            errors.append(f"evidence_not_verbatim:{role}")
    targets = {row["entity_id"] for row in candidate["bindings"]}
    others = {row["entity_id"] for role in ROLES[1:] for row in candidate[role]}
    if targets & others:
        errors.append("target_role_conflict")
    if (candidate["status"] == "bound") != bool(targets):
        errors.append("status_binding_inconsistent")
    return errors


class ModelResolution(PreviewIntentResolution):
    """Experiment-only producer injection; never installed in the native route."""
    @property
    def intent_source(self):
        return "local_model"


def model_campus_preview(candidate, registry, preview, objective):
    def convert(objective_from_route, *, scene_id, scene):
        assert objective_from_route == objective and scene is registry.scene
        catalog = _catalog_from_scene(scene_id, scene)
        if candidate is None:
            return PreviewIntentResolution("unsupported", "EVAL_MODEL_INVALID")
        mapped = {role: tuple(Binding(**row) for row in candidate[role]) for role in ROLES}
        params = IntentParameters(
            targets=mapped["bindings"], reference_only=mapped["reference_only"],
            excluded_targets=mapped["excluded_targets"],
            only_listed_targets=candidate["only_listed_targets"],
        )
        return ModelResolution(
            TO_RUNTIME[candidate["status"]], "EVAL_LOCAL_MODEL_CANDIDATE",
            mission_type="inspection_snapshot" if candidate["status"] == "bound" else None,
            parameters=params, catalog=catalog,
        )

    with patch.object(routes, "resolve_preview_intent", convert):
        return preview(objective)


def checked_real_scene(preview):
    scene = routes.VEHICLE_REGISTRY.scene
    assert scene["scene_id"] == "simple_recon_v0_1"
    assert [t["target_id"] for t in scene["targets"]] == ["target-001"]
    inputs = ("巡检西北区域", "巡检东北视觉标记", "把参考点列为目标", "巡检西南和东南",
              "中央建筑只用来定位，不用核对；本轮只核对东北视觉标记")
    outputs = [preview(objective) for objective in inputs]
    normalized = [from_http(body) for body in outputs]
    for result, expected in zip(normalized, [
        ("bound", ["demo-area-001"], "INTENT_BOUND"), ("bound", ["target-001"], "INTENT_BOUND"),
        ("clarify", [], "TARGET_AMBIGUOUS"), ("clarify", [], "CONFLICTING_TARGETS"),
        ("bound", ["target-001"], "INTENT_BOUND"),
    ], strict=True):
        assert (result["status"], [b["entity_id"] for b in result["bindings"]], result["reason"]) == expected
    assert [b["entity_id"] for b in normalized[-1]["reference_only"]] == ["building-001"]
    assert [b["entity_id"] for b in normalized[-1]["excluded_targets"]] == ["building-001"]
    return [{"objective": text, "response": body} for text, body in zip(inputs, outputs, strict=True)]


def metrics(rows, arm):
    bound = [r for r in rows if r["expected_status"] == "bound"]
    ordered = [r for r in bound if len(r["expected_ids"]) > 1]
    ask = [r for r in rows if r["expected_status"] == "clarify"]
    unknown = [r for r in rows if r["expected_status"] == "unknown"]
    p = lambda row: row[arm]["prediction"]
    status = lambda row: p(row)["status"]
    ids = lambda row: [b["entity_id"] for b in p(row).get("bindings", [])]
    return {
        "complete_bindings": [sum(status(r) == "bound" and sorted(ids(r)) == sorted(r["expected_ids"]) for r in bound), len(bound)],
        "correct_order": [sum(status(r) == "bound" and ids(r) == r["expected_ids"] for r in ordered), len(ordered)],
        "false_binding_on_clarify": [sum(status(r) == "bound" or bool(ids(r)) for r in ask), len(ask)],
        "abstained_on_answerable": [sum(status(r) in ("clarify", "unknown") for r in bound), len(bound)],
        "correct_clarifications": [sum(status(r) == "clarify" for r in ask), len(ask)],
        "partial_or_false_binding_on_unknown": [sum(status(r) == "bound" or bool(ids(r)) for r in unknown), len(unknown)],
        "unknown_status_matches": [sum(status(r) == "unknown" for r in unknown), len(unknown)],
        "technical_failures": sum(status(r) == "invalid" for r in rows),
        "raw_false_binding_on_clarify": sum(bool(r[arm].get("raw_positive_binding")) for r in ask),
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--model-url", required=True)
    cli.add_argument("--model-id", required=True)
    cli.add_argument("--launch-record", type=Path, required=True)
    opts = cli.parse_args()
    current = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if current != BASELINE:
        cli.error(f"This evaluation fixes the preview route at {BASELINE}")
    source = DRAFT.read_text(encoding="utf-8")
    cases = actual_cases(source)
    launch = json.loads(opts.launch_record.read_text(encoding="utf-8-sig"))
    assert launch["model_alias"] == opts.model_id and launch["offline_flag"] is True
    assert opts.model_url == f"http://127.0.0.1:{launch['port']}/v1"
    opts.output.mkdir(parents=True, exist_ok=False)
    client = LocalModelClient(opts.model_url, opts.model_id, timeout_s=45)
    write_json(opts.output / "protocol.json", {
        "baseline": current, "draft": DRAFT.name, "draft_sha256_lf": sha256(source.encode()).hexdigest(),
        "started_utc": datetime.now(timezone.utc).isoformat(), "cases": cases, "catalogs": CATALOGS,
        "instruction": INSTRUCTION, "model_schema": MODEL_SCHEMA, "model_id": opts.model_id,
        "model_launch": launch, "seed": SEED, "temperature": 0, "max_tokens": MAX_TOKENS,
        "execution_authorized": False, "draft_examples_not_holdout": True,
        "campus": "live route on isolated loopback; synthetic entries are preview-only; model adapter experiment only",
        "scoreboard": "offline meaning only, outside native Runtime template grammar",
    })
    board = RuleIntentRecognizer(
        CatalogEntry(e["entity_id"], e["label"], tuple(e["aliases"])) for e in CATALOGS["G"]["entities"]
    )
    registry = campus_registry()
    rows = []
    with preview_http() as (preview, requests), (opts.output / "responses.jsonl").open("x", encoding="utf-8") as log:
        write_json(opts.output / "actual_scene_rule_smoke.json", checked_real_scene(preview))
        with patch.object(routes, "VEHICLE_REGISTRY", registry), patch.object(
            routes, "RUNTIME_STATE_STORE", RuntimeStateStore(vehicle_registry=registry),
        ):
            for case in cases:
                objective, domain = case["objective"], case["id"][0]
                catalog = CATALOGS[domain]
                start = perf_counter()
                if domain == "S":
                    rule_http = preview(objective)
                    rule = from_http(rule_http)
                else:
                    result = board.recognize(objective)
                    rule_http = None
                    rule = {"status": result.status, "bindings": [
                        {"entity_id": b.entity_id, "evidence": b.evidence} for b in result.parameters.targets
                    ], "reason": result.reason_code}
                rule_ms = (perf_counter() - start) * 1000
                messages = [{"role": "system", "content": INSTRUCTION}, {"role": "user", "content": json.dumps(
                    {"objective": objective, "catalog": catalog}, ensure_ascii=False,
                )}]
                raw, candidate, error_evidence = None, None, None
                start = perf_counter()
                try:
                    raw = client.complete(messages, MODEL_SCHEMA, seed=SEED, max_tokens=MAX_TOKENS, constrained=True)
                    candidate = parse_json(raw["content"])
                    errors = check_model(candidate, objective, catalog)
                except (ModelError, ContractError) as exc:
                    errors = [str(exc)]
                    error_evidence = getattr(exc, "response_evidence", None)
                model_ms = (perf_counter() - start) * 1000
                accepted = candidate if not errors else None
                runtime_model = model_campus_preview(accepted, registry, preview, objective) if domain == "S" else None
                model = (from_http(runtime_model) if runtime_model is not None else accepted) if accepted else {
                    "status": "invalid", "bindings": [],
                }
                row = {**case,
                       "rules": {"prediction": rule, "http": rule_http, "elapsed_ms": rule_ms},
                       "model": {"messages": messages, "response": raw, "error_evidence": error_evidence,
                                 "unvalidated_candidate": candidate, "errors": errors, "prediction": model,
                                 "http": runtime_model, "elapsed_ms": model_ms,
                                 "raw_positive_binding": isinstance(candidate, dict) and (
                                     candidate.get("status") == "bound" or bool(candidate.get("bindings")))},
                       }
                rows.append(row)
                log.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                log.flush()
                print(f'{case["id"]}: rules {rule["status"]} / model {model["status"]} ({model_ms:.0f} ms)', flush=True)
    assert len(requests) == 17 and all(
        r["path"] == PREVIEW_PATH and r["execution_authorized"] is False for r in requests
    )
    by_domain = {"all": rows, **{k: [r for r in rows if r["id"].startswith(k)] for k in CATALOGS}}
    timings = sorted(row["model"]["elapsed_ms"] for row in rows)
    write_json(opts.output / "report.json", {
        "base": current, "metrics": {k: {arm: metrics(v, arm) for arm in ("rules", "model")}
                                   for k, v in by_domain.items()},
        "model_latency_ms": {"min": timings[0], "median": statistics.median(timings), "max": timings[-1]},
        "requests": requests, "model_requests": len(rows), "execution_authorized": False,
        "model_sample_count": 1, "draft_examples_not_holdout": True,
    })


if __name__ == "__main__":
    main()
