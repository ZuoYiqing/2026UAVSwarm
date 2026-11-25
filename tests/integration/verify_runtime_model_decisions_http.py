"""Opt-in measured 4B comparison on isolated Runtime HTTP listeners."""
from contextlib import closing, contextmanager
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from time import monotonic


ROOT = Path(__file__).resolve().parents[2]
PREVIEW = "/api/planner/plan-mission"
OBJECTIVES = (
    "巡检西北区域。",
    "巡检东北视觉标记。",
    "把参考点列为目标。",
    "巡检西南和东南。",
    "中央建筑只用来定位，不用核对；本轮只核对东北视觉标记。",
)
ROLES = ("targets", "preview_only_targets", "reference_only", "excluded_targets")


@contextmanager
def serving(httpd):
    with httpd:
        worker = Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        worker.start()
        try:
            yield httpd.server_port
        finally:
            httpd.shutdown()
            worker.join(timeout=2)


def request(host, port, path, *, token=None, objective=None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    payload = None if objective is None else json.dumps({"objective": objective, "dry_run": True})
    with closing(HTTPConnection(host, port, timeout=3 if payload is None else 20)) as connection:
        connection.request("GET" if payload is None else "POST", path, payload, headers)
        with connection.getresponse() as response:
            return response.status, json.load(response)


def selection(reply):
    binding = reply["intent_resolution"]["bindings"]
    return {**{role: [row["entity_id"] for row in binding[role]] for role in ROLES},
            "only_listed_targets": binding["only_listed_targets"]}


def main():
    if not __debug__:
        raise SystemExit("Run without Python optimization so verification assertions are active")
    sys.path.insert(0, str(ROOT / "src"))
    from uav_runtime.http.local_model_preview import LocalPreviewModel
    from uav_runtime.http.model_preview_config import ModelPreviewConfig

    config = ModelPreviewConfig.from_env(os.environ)
    status, health = request(config.host, config.port, "/health", token=config.token)
    assert status == 200 and health["status"] == "ok"
    status, listing = request(config.host, config.port, "/v1/models", token=config.token)
    assert status == 200 and config.alias in {row["id"] for row in listing["data"]}
    records = []
    with TemporaryDirectory(prefix="uav-runtime-model-decisions-") as scratch:
        os.environ["UAV_RUNTIME_AUDIT_PATH"] = str(Path(scratch) / "preview.audit.jsonl")
        os.environ["UAV_RUNTIME_VEHICLE_CONFIG"] = str(ROOT / "simulation/px4_gazebo/config/three_uav_sitl.json")
        from uav_runtime.http.server import create_server

        # Actual Runtime HTTP handler, without registry/telemetry startup. Unlike
        # the demo on 8765, both listeners are on temporary loopback ports.
        with serving(create_server(port=0, preview_only=True)) as baseline, serving(
            create_server(port=0, preview_model=LocalPreviewModel(config), preview_only=True)
        ) as decisions:
            for objective in OBJECTIVES:
                rules_status, rules = request("127.0.0.1", baseline, PREVIEW, objective=objective)
                started = monotonic()
                decision_status, decision = request("127.0.0.1", decisions, PREVIEW, objective=objective)
                elapsed_ms = round((monotonic() - started) * 1000)
                assert rules_status == decision_status == 200
                assert rules["execution_authorized"] is decision["execution_authorized"] is False
                diagnostic = decision.get("model_diagnostics")
                adopted = decision["intent_source"] == "local_model"
                assert adopted == bool(diagnostic and diagnostic["adopted"])
                rules_binding, decision_binding = selection(rules), selection(decision)
                records.append({
                    "objective": objective, "http_status": decision_status, "elapsed_ms": elapsed_ms,
                    "intent_source": decision["intent_source"], "fallback_reason": decision["fallback_reason"],
                    "reason_code": decision["intent_resolution"]["reason_code"], "model_diagnostics": diagnostic,
                    "adopted": adopted, "differs_from_rules": decision_binding != rules_binding,
                    "rules_binding": rules_binding, "preview_binding": decision_binding,
                    "execution_authorized": decision["execution_authorized"],
                })
    divergences = sum(r["adopted"] and r["differs_from_rules"] for r in records)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    print(json.dumps({
        "runtime_git_commit": commit, "runtime_worktree_dirty": dirty, "actual_model_alias": config.alias,
        "telemetry_enabled": False, "execution_requests": 0,
        "adopted_different_decisions": divergences, "requests": records,
    }, ensure_ascii=True, indent=2), flush=True)
    # Do not turn five identical/unadopted answers into a passed takeover demo.
    return 0 if divergences else 2


if __name__ == "__main__":
    raise SystemExit(main())
