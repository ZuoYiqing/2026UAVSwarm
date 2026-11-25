"""Explicit opt-in: actual Runtime CLI, actual loopback 4B, no flight or telemetry."""
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from time import monotonic, sleep

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("UAV_RUNTIME_VERIFY_LOCAL_4B") != "1",
    reason="requires explicit opt-in and an existing local 4B engine on TCP 18116",
)
ROOT = Path(__file__).resolve().parents[2]
MODEL = "qwen3.5-4b-q4-lab"


def request(port, path, body=None):
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        payload = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json", "Origin": "http://127.0.0.1:5178"}
        connection.request("GET" if body is None else "POST", path, payload, headers)
        with connection.getresponse() as response:
            assert response.status == 200, (path, response.status)
            return json.load(response)
    finally:
        connection.close()


def test_actual_runtime_cli_adopts_valid_live_4b_preview(tmp_path):
    assert request(18116, "/health")["status"] == "ok"
    assert MODEL in {row["id"] for row in request(18116, "/v1/models")["data"]}
    with socket.socket() as probe:
        probe.settimeout(1)
        assert probe.connect_ex(("127.0.0.1", 8765)) != 0, "Existing Runtime listener was not changed"
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("UAV_RUNTIME_")}
    env.update(PYTHONPATH=str(ROOT / "src"), UAV_RUNTIME_AUDIT_PATH=str(tmp_path / "audit.jsonl"))
    log_path = tmp_path / "runtime.out"
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            [sys.executable, "-B", "-m", "uav_runtime.http.server", "--read-only-model-preview"],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            deadline = monotonic() + 12
            while monotonic() < deadline and proc.poll() is None:
                try:
                    if request(8765, "/api/health")["status"] == "ok" and proc.poll() is None:
                        break
                except OSError:
                    sleep(0.1)
            else:
                pytest.fail(log_path.read_text(encoding="utf-8", errors="replace"))
            # Match the existing console: it sends objective and omits dry_run.
            for objective, role, ids in (
                ("巡检西北区域。", "preview_only_targets", ["demo-area-001"]),
                ("只核对东北视觉标记。", "targets", ["target-001"]),
            ):
                started = monotonic()
                body = request(8765, "/api/planner/plan-mission", {"objective": objective})
                elapsed_ms = round((monotonic() - started) * 1000)
                evidence = {key: body[key] for key in
                            ("intent_source", "plan_source", "fallback_reason", "execution_authorized")}
                resolution = body["intent_resolution"]
                print(json.dumps({
                    "objective": objective, "elapsed_ms": elapsed_ms, **evidence,
                    "reason_code": resolution["reason_code"], "bindings": resolution["bindings"],
                }, ensure_ascii=True))
                assert evidence == {
                    "intent_source": "local_model", "plan_source": "template",
                    "fallback_reason": None, "execution_authorized": False,
                }
                assert resolution["reason_code"] == "LOCAL_MODEL_CONFIRMED_INTENT"
                assert [row["entity_id"] for row in resolution["bindings"][role]] == ids
                assert body["plan"]["preview_binding"]["steps_are_outline"] is True
            clarification = request(8765, "/api/planner/plan-mission", {"objective": "把参考点列为目标。"})
            assert clarification["intent_source"] == "rules" and clarification["fallback_reason"] is None
            assert clarification["intent_resolution"]["reason_code"] == "TARGET_AMBIGUOUS"
            assert clarification["plan"] is None and clarification["execution_authorized"] is False
        finally:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
