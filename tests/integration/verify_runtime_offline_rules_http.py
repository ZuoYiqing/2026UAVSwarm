"""Run the shipped preview server (no mocks, PX4 or model) and print evidence.

Run from the Runtime checkout:
    python -B tests/integration/verify_runtime_offline_rules_http.py
The normal Runtime loopback port 8765 must be free. The campus catalog is
test-only, loaded via the normal vehicle config from a temporary directory.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "simulation/px4_gazebo/config/three_uav_sitl.json"
SCENE = ROOT / "scenarios/simple_recon_v0_1/scene.json"
PIN = ROOT / "tests/fixtures/runtime_intent_recognition_vendor_v0.json"
BASE_URL = "http://127.0.0.1:8765"
PREVIEW_PATH = "/api/planner/plan-mission"
CLIENT = build_opener(ProxyHandler({}))


@dataclass(frozen=True)
class Case:
    id: str
    objective: str
    status: str = "resolved"
    reason: str = "INTENT_BOUND"
    targets: tuple[str, ...] = ()
    preview: tuple[str, ...] = ()
    reference: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    only_listed: bool = False
    choices: tuple[str, ...] = ()


CAMPUS = (
    Case("S01", "三机联巡任务预演：只核对西侧光伏区。", preview=("S-PV-W",), only_listed=True),
    Case("S02", "这轮检查园区西面那排用于发电的太阳能板。", preview=("S-PV-W",)),
    Case("S03", "把水表点列为本轮核对目标。", "needs_clarification", "TARGET_AMBIGUOUS",
         choices=("访客入口水表点", "展厅门外水表点")),
    Case("S04", "北仓只用来定位，不用核对；本轮只核对热泵机房。",
         preview=("S-THERM",), reference=("S-STORE-N",), excluded=("S-STORE-N",), only_listed=True),
    Case("S05", "核对热泵机房之前，先核对西侧光伏区。", preview=("S-PV-W", "S-THERM")),
    Case("S06", "录入北仓和东侧充电棚，两处都必须核对。", "unsupported", "UNSUPPORTED_OBJECTIVE"),
)
RECON = (
    Case("recon-prefix", "麻烦这一轮巡检西北区域。", preview=("demo-area-001",)),
    Case("recon-header", "三机联巡任务预演：只核对东北视觉标记。", targets=("target-001",), only_listed=True),
    Case("recon-negation", "麻烦这一轮别核对中央建筑；本轮只核对东北视觉标记。",
         targets=("target-001",), excluded=("building-001",), only_listed=True),
    Case("recon-ambiguity", "麻烦把参考点列为本轮核对目标。", "needs_clarification", "TARGET_AMBIGUOUS",
         choices=("西侧参考点", "东侧参考点")),
    Case("recon-order", "核对西北区域之前，先核对西侧参考点。", preview=("demo-anchor-001", "demo-area-001")),
    Case("recon-conflict", "巡检西南和东南。", "needs_clarification", "CONFLICTING_TARGETS"),
    Case("recon-reference-guard", "巡检西北区域和中央建筑。", "needs_clarification", "TARGET_REFERENCE_ONLY"),
    Case("recon-pronoun", "检查那栋。", "needs_clarification", "REFERENCE_CONTEXT_REQUIRED"),
)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def campus_config(directory: Path) -> Path:
    scene = read_json(SCENE)
    identity = {"scene_id": "demo-campus-v1", "map_version": "a-v04-draft-semantic-v1"}
    rows = [
        ("S-PV-W", "西侧光伏区", ["园区西面一排用于发电的太阳能板"]),
        ("S-THERM", "热泵机房", []),
        ("S-STORE-N", "北仓", []),
        ("S-METER-A", "访客入口水表点", ["水表点"]),
        ("S-METER-B", "展厅门外水表点", ["水表点"]),
    ]
    scene.update(identity, targets=[], obstacles=[], intent_catalog={
        **identity, "contract_version": "1.0", "catalog_id": "demo-campus-v1",
        "entries": [{"entity_id": i, "label": label, "aliases": aliases} for i, label, aliases in rows],
        "preview_only_entity_ids": [row[0] for row in rows],
    })
    scene_path = directory / "test-campus-scene.json"
    scene_path.write_text(json.dumps(scene), encoding="utf-8")
    config = read_json(CONFIG)
    config.update(identity, scene_path=str(scene_path))
    config_path = directory / "test-campus-vehicles.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


@contextmanager
def running_runtime(config: Path, directory: Path, profile: str):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        if probe.connect_ex(("127.0.0.1", 8765)) == 0:
            raise RuntimeError("Port 8765 is already in use; no existing service was changed")
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("UAV_RUNTIME_")}
    env.update(PYTHONPATH=str(ROOT / "src"), UAV_RUNTIME_TELEMETRY_ENABLED="false",
               UAV_RUNTIME_VEHICLE_CONFIG=str(config), UAV_RUNTIME_DEMO_ENABLED="0",
               UAV_RUNTIME_AUDIT_PATH=str(directory / f"{profile}-audit.jsonl"))
    log_path = directory / f"{profile}-server.log"
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            [sys.executable, "-B", "-m", "uav_runtime.http.server", "--vehicle-config", str(config)],
            cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            until = time.monotonic() + 15
            while time.monotonic() < until and proc.poll() is None:
                try:
                    with CLIENT.open(BASE_URL + "/api/health", timeout=1) as response:
                        if json.load(response)["status"] == "ok" and proc.poll() is None:
                            break
                except (OSError, URLError):
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Runtime did not start: " + log_path.read_text(encoding="utf-8", errors="replace"))
            yield
            if proc.poll() is not None:
                raise RuntimeError("Runtime exited during the preview smoke")
        finally:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def verify_case(profile: str, scene_id: str, case: Case) -> dict:
    request = Request(
        BASE_URL + PREVIEW_PATH, json.dumps({"objective": case.objective, "dry_run": True}).encode(),
        {"Content-Type": "application/json"}, method="POST",
    )
    with CLIENT.open(request, timeout=5) as response:
        http_status, body = response.status, json.load(response)
    resolved = case.status == "resolved"
    resolution = body["intent_resolution"]
    bindings = resolution["bindings"]
    actual_ids = {role: [row["entity_id"] for row in bindings[role]] for role in
                  ("targets", "preview_only_targets", "reference_only", "excluded_targets")}
    assert (http_status, body["intent_source"], body["plan_source"], body["fallback_reason"]) == (
        200, "rules", "template" if resolved else "none", None,
    ), (case.id, body)
    assert body["execution_authorized"] is False and (body["plan"] is not None) == resolved, (case.id, body)
    assert resolution["catalog"]["scene_id"] == scene_id, (case.id, body)
    assert (resolution["status"], resolution["reason_code"], resolution["mission_type"]) == (
        case.status, case.reason, "inspection_snapshot" if resolved else None,
    ), (case.id, body)
    expected_ids = dict(targets=case.targets, preview_only_targets=case.preview,
                        reference_only=case.reference, excluded_targets=case.excluded)
    assert actual_ids == {role: list(ids) for role, ids in expected_ids.items()}, (case.id, body)
    assert bindings["only_listed_targets"] is case.only_listed, (case.id, body)
    assert all(choice in (resolution["question"] or "") for choice in case.choices), (case.id, body)
    if resolved:
        assert body["plan"]["preview_binding"]["steps_are_outline"] is True, (case.id, body)
    return {"profile": profile, "case": case.id, "objective": case.objective, "http_status": http_status,
            "status": resolution["status"], "reason_code": resolution["reason_code"],
            "question": resolution["question"], "intent_source": body["intent_source"],
            "plan_source": body["plan_source"], "fallback_reason": body["fallback_reason"],
            "plan_present": body["plan"] is not None, **actual_ids,
            "only_listed_targets": bindings["only_listed_targets"],
            "execution_authorized": body["execution_authorized"]}


def digest(path: str) -> str:
    return sha256((ROOT / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def main() -> None:
    if not __debug__:
        raise SystemExit("Run without Python optimization so all verification assertions are active")
    subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], cwd=ROOT, check=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    pin = read_json(PIN)
    entry = pin["files"][0]
    source_sha, vendor_sha = digest(entry["upstream_path"]), digest(entry["vendored_path"])
    assert source_sha == vendor_sha == entry["sha256_lf"]
    with TemporaryDirectory(prefix="uav-offline-rules-http-") as temp:
        directory = Path(temp)
        requests = []
        for profile, scene_id, config, cases in (
            ("campus_fixture", "demo-campus-v1", campus_config(directory), CAMPUS),
            ("simple_recon_v0_1", "simple_recon_v0_1", CONFIG, RECON),
        ):
            with running_runtime(config, directory, profile):
                requests.extend(verify_case(profile, scene_id, case) for case in cases)
    evidence = {
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_git_commit": revision,
        "upstream_commit": pin["upstream_commit"],
        "source_sha256_lf": source_sha,
        "vendor_sha256_lf": vendor_sha,
        "production_wiring_changed": True,
        "runtime_entrypoint": "python -B -m uav_runtime.http.server --vehicle-config <scene config>",
        "reproduce": "python -B tests/integration/verify_runtime_offline_rules_http.py",
        "preview_endpoint": BASE_URL + PREVIEW_PATH,
        "telemetry_enabled": False,
        "model_requests": 0,
        "execution_requests": 0,
        "dry_run": True,
        "summary": {"passed": len(requests), "failed": 0, "skipped": 0,
                    "by_profile": {"campus_fixture": len(CAMPUS), "simple_recon_v0_1": len(RECON)}},
        "requests": requests,
    }
    print(json.dumps(evidence, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
