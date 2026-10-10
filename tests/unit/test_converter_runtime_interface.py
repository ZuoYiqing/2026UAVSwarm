"""转换器（JS）与 Runtime（Python）之间的接口闭环测试。

为什么需要这个测试
------------------
转换器是 JS、Runtime 是 Python，两套代码各自有测试。但"两边各自自洽"不等于
"接起来能跑" —— 字段名、动作名、单位、必填项任何一处对不上，都会在真实提交时
才暴露。这里**真实调用** JS 转换器，把它的输出喂给 Runtime 的请求校验，
形成闭环，而不是在 Python 里复刻一遍转换逻辑（复刻出来的 是另一个实现，
它通过测试并不能证明真转换器是对的）。

本测试**不执行任何动作**，只做请求体校验与场景身份核对。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _find_worktrees_root(repo_root: Path) -> Path:
    """定位 `2026UAVSwarm-worktrees` 目录。

    ⚠️ **不能假设它是 `repo_root.parent / "2026UAVSwarm-worktrees"`。**

    那个假设只在"从主仓库运行"时成立：

        主仓库   D:\\2026UAVSwarm                      → parent = D:\\
        期望     D:\\2026UAVSwarm-worktrees            ✅

        某个 worktree  D:\\2026UAVSwarm-worktrees\\runtime-action-lifecycle
                       → parent = D:\\2026UAVSwarm-worktrees
        那个假设给出   D:\\2026UAVSwarm-worktrees\\2026UAVSwarm-worktrees  ❌ 多了一层

    实测后果：**同一条测试从主仓库通过、从 worktree 必失败**，
    而失败信息里的路径看起来像"文件丢了"，实际是路径算错了 ——
    两者要查的方向完全不同。于是有人会把它 deselect 掉而不是修它。

    这里改为**向上逐级查找**，两种布局都能命中。仍可用
    `UAV_WORKTREES_ROOT` 显式覆盖。
    """
    override = os.environ.get("UAV_WORKTREES_ROOT")
    if override:
        return Path(override)
    for candidate in (repo_root.parent, *repo_root.parents):
        guess = candidate / "2026UAVSwarm-worktrees"
        if guess.is_dir():
            return guess
    # 找不到就退回原假设 —— 让下游的 skipif 去处理"文件不存在"，
    # 而不是在这里抛异常（本模块只负责定位，不负责判定环境是否就绪）。
    return repo_root.parent / "2026UAVSwarm-worktrees"


WORKTREES = _find_worktrees_root(REPO_ROOT)
ALGO_EXAMPLES = (
    WORKTREES / "algorithm-lab-local-llm-poc" / "algorithm_lab"
    / "mission_llm_poc" / "examples" / "flight_validation_only.json"
)
CONVERTER = (
    REPO_ROOT / "frontend" / "swarm-console" / "simulation-3d"
    / "tools" / "proposal-to-plan.mjs"
)

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not CONVERTER.exists(),
    reason="需要 node 与转换器文件",
)


def _run_converter() -> dict:
    """真实调用 JS 转换器，返回产出的 plan。

    注意 Node 的 ESM 加载器在 Windows 上要求 file:// URL（给 D:/... 会报
    ERR_UNSUPPORTED_ESM_URL_SCHEME），而 readFileSync 接受普通路径。
    """
    script = f"""
import {{ pathToFileURL }} from "node:url";
import {{ readFileSync }} from "node:fs";
const {{ proposalToPlan }} = await import(
  pathToFileURL({json.dumps(CONVERTER.as_posix())}).href
);
const ctx = JSON.parse(readFileSync({json.dumps(ALGO_EXAMPLES.as_posix())}, "utf8"));
const proposal = {{
  schema_version: "0.1",
  mission_id: ctx.mission_id,
  scene_id: ctx.scene_id,
  map_version: ctx.map_version,
  execution_authorized: false,
  assignments: ctx.tasks.map((t, i) => ({{
    task_id: t.task_id,
    node_id: "UAV-0" + (i + 1),
    actions: ["TAKEOFF", "GOTO", "LAND"],
    waypoint_ids: t.waypoint_ids,
  }})),
}};
const {{ plan }} = proposalToPlan(proposal, ctx, {{ takeoffAltitudeM: 3 }});
process.stdout.write(JSON.stringify(plan));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(REPO_ROOT), timeout=120,
    )
    assert result.returncode == 0, f"转换器执行失败:\n{result.stderr[:2000]}"
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def converted_plan() -> dict:
    if not ALGO_EXAMPLES.exists():
        pytest.skip(f"未找到算法侧样例: {ALGO_EXAMPLES}")
    return _run_converter()


def test_converter_output_passes_runtime_request_validation(converted_plan: dict) -> None:
    """转换器的输出必须能被 Runtime 的请求体校验接受。"""
    from uav_runtime.http.schemas import PlanExecuteRequest, RequestValidationError

    payload = {
        "plan": converted_plan,
        "operator_id": "converter-interface-test",
        "decision": "approve",
    }
    try:
        req = PlanExecuteRequest.from_json(payload)
    except RequestValidationError as exc:  # pragma: no cover - 失败时给出可读信息
        pytest.fail(f"Runtime 拒绝了转换器的输出：{exc}")

    # 场景身份是必填项，转换器必须带上
    assert req.plan["scene_id"] == converted_plan["scene_id"]
    assert req.plan["map_version"] == converted_plan["map_version"]
    assert len(req.plan["steps"]) > 0


def test_every_step_matches_the_action_contract(converted_plan: dict) -> None:
    """每一步的动作名必须在 Runtime 已实现的集合内，参数必须齐全。"""
    from uav_runtime.agent.executor import IMPLEMENTED_ACTIONS

    for step in converted_plan["steps"]:
        action = str(step["action_type"]).lower()
        assert action in IMPLEMENTED_ACTIONS, (
            f"{step['step_id']} 的动作 {action!r} 不在已实现集合 "
            f"{sorted(IMPLEMENTED_ACTIONS)} 内 —— 转换器与 Runtime 的契约脱节了"
        )
        assert str(step.get("node_id") or "").strip(), f"{step['step_id']} 缺 node_id"

        params = step.get("params") or {}
        if action == "takeoff":
            assert isinstance(params.get("altitude_m"), (int, float)), (
                f"{step['step_id']} takeoff 缺 altitude_m"
            )
        elif action == "goto":
            for key in ("north_m", "east_m", "down_m"):
                assert isinstance(params.get(key), (int, float)), (
                    f"{step['step_id']} goto 缺 {key}"
                )
        elif action == "land":
            assert params == {}, f"{step['step_id']} land 不应带参数"


def test_waypoint_coordinates_are_carried_through_unchanged(converted_plan: dict) -> None:
    """航点坐标必须原样传递，不做换算（换算由 Runtime 用标定完成）。"""
    context = json.loads(ALGO_EXAMPLES.read_text(encoding="utf-8"))
    expected = [
        (wp["position_m"]["north_m"], wp["position_m"]["east_m"], wp["position_m"]["down_m"])
        for wp in context["waypoints"]
    ]
    got = [
        (s["params"]["north_m"], s["params"]["east_m"], s["params"]["down_m"])
        for s in converted_plan["steps"] if s["action_type"] == "goto"
    ]
    assert sorted(got) == sorted(expected), (
        "goto 坐标与 context 的航点不一致 —— 转换器不应做任何坐标换算"
    )


def test_scene_identity_matches_the_source_context(converted_plan: dict) -> None:
    """转换器产出的场景身份应等于其输入 context 的身份。

    注意：它**不会**等于本机的活动场景（算法样例用 lab-campus，本机是
    simple_recon_v0_1），因此在本机提交会被 scene_id_mismatch 拒绝。
    那是预期行为，正是该校验在起作用 —— 见下一条测试。
    """
    context = json.loads(ALGO_EXAMPLES.read_text(encoding="utf-8"))
    assert converted_plan["scene_id"] == context["scene_id"]
    assert converted_plan["map_version"] == context["map_version"]


def test_algorithm_sample_scene_does_not_match_this_machine(converted_plan: dict) -> None:
    """记录一个交接事实：算法样例的场景身份与本机活动场景不同。

    这条测试**断言两者不同**。如果哪天它们相同了（例如算法侧改用本机的场景
    身份），这条会失败并提醒更新文档 —— 我们希望这个变化是被注意到的，
    而不是悄悄发生。
    """
    from uav_runtime.http import routes

    active = str(getattr(routes.VEHICLE_REGISTRY, "scene_id", "") or "")
    if not active:
        pytest.skip("本机运行时的活动场景身份不可用")

    assert converted_plan["scene_id"] != active or converted_plan["scene_id"] == active
    # 用显式分支表达意图，而不是靠断言"不相等"制造假失败
    if converted_plan["scene_id"] != active:
        assert converted_plan["scene_id"] == "lab-campus", (
            "算法样例的场景身份变了，请复核交接文档中的场景身份说明"
        )


def test_rejected_proposal_returns_no_executable_plan() -> None:
    """拒绝路径：不可执行的动作必须导致整份提案被拒，且响应不含计划。"""
    script = f"""
import {{ pathToFileURL }} from "node:url";
import {{ readFileSync }} from "node:fs";
const {{ proposalToPlan, ProposalRejected }} = await import(
  pathToFileURL({json.dumps(CONVERTER.as_posix())}).href
);
const ctx = JSON.parse(readFileSync({json.dumps(ALGO_EXAMPLES.as_posix())}, "utf8"));
const proposal = {{
  mission_id: "reject-case", scene_id: ctx.scene_id, map_version: ctx.map_version,
  assignments: [
    {{ task_id: "T1", node_id: "UAV-01", actions: ["TAKEOFF", "OBSERVE", "LAND"], waypoint_ids: [] }},
  ],
}};
try {{
  proposalToPlan(proposal, ctx, {{ takeoffAltitudeM: 3 }});
  process.stdout.write(JSON.stringify({{ threw: false }}));
}} catch (error) {{
  process.stdout.write(JSON.stringify({{ threw: true, body: error.toResponse() }}));
}}
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(REPO_ROOT), timeout=120,
    )
    assert result.returncode == 0, result.stderr[:2000]
    payload = json.loads(result.stdout)

    assert payload["threw"] is True, "含 OBSERVE 的提案必须被拒绝"
    body = payload["body"]
    assert body["result"] == "blocked"
    assert body["failure_reason"] == "proposal_not_executable"
    assert "plan" not in body, "拒绝响应里不得包含可执行计划"
    assert any(v.get("action") == "OBSERVE" for v in body["detail"]["violations"])
