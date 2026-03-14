from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class PlanArtifacts:
    decision_json: Dict[str, Any]
    notes: str = ""


class Planner:
    def generate(self, mission: Dict[str, Any], scene: Dict[str, Any], kb_context: str = "") -> PlanArtifacts:
        raise NotImplementedError


class RulePlanner(Planner):
    """Deterministic rule-based planner.

    The goal is to provide a runnable baseline that you can replace with:
    - Teacher LLM (strong online model)
    - Student / NanoGPT-Edge (offline small model)
    """

    def generate(self, mission: Dict[str, Any], scene: Dict[str, Any], kb_context: str = "") -> PlanArtifacts:
        nodes = scene.get("nodes", [])
        gs = next((n for n in nodes if n.get("role") in {"global_controller", "gs", "ground_station"}), None)
        head = next((n for n in nodes if n.get("role") in {"cluster_head", "head"}), None)
        members = [n for n in nodes if n.get("role") in {"member", "uav_member"}]

        gs_id = (gs or {}).get("id", "GS")
        head_id = (head or {}).get("id", "UAV_1")
        member_ids = [m.get("id") for m in members if m.get("id")]

        # Pull some constraints with safe defaults
        constraints = mission.get("constraints", {})
        max_bw = constraints.get("max_total_bandwidth_bps", 1_000_000)
        lost_contact_timeout = constraints.get("lost_contact_timeout_s", 10)
        time_limit_s = mission.get("time_limit_s", 600)

        # Policy rules (human-readable, easy to audit)
        global_rules: List[str] = []
        global_rules.append(f"在初始阶段，要求{len(member_ids)+1}架UAV均匀划分区域进行搜索覆盖（含簇首{head_id}）")
        global_rules.append(f"当收到任何 TARGET_REPORT 且威胁等级为高时，应在 5 秒内回复")
        global_rules.append(f"当链路总带宽受限（<= {max_bw} bps）时，优先保证心跳/状态上报与目标上报的可靠传输")
        global_rules.append(f"任务总时限 {time_limit_s} 秒；如出现失联，超过 {lost_contact_timeout} 秒触发降级策略")

        head_rules: List[str] = []
        head_rules.append(f"接收簇内成员({', '.join(member_ids) if member_ids else '无'})的 TARGET_REPORT 并进行融合，形成 TARGET_SUMMARY 上报 {gs_id}")
        head_rules.append(
            f"在 {gs_id} {lost_contact_timeout} 秒内未对高威胁目标做出指示时，可在权限范围内临时指派 1 架 UAV 进行短时跟踪；其余保持搜索"
        )
        head_rules.append("如发现多目标冲突，优先处理威胁等级更高且置信度更高的目标")

        member_rules: List[str] = []
        member_rules.append("正常状态下按分配区域进行搜索，每 5 秒发送 UAV_STATUS")
        member_rules.append(f"如本机检测到可疑目标，立即向簇首 {head_id} 发送 TARGET_REPORT")
        member_rules.append("如接到 CLUSTER_CMD 调整任务，则切换到指定子任务（继续搜索/重点搜索/返回等）")

        decision = {
            "global_policy": {"controller": gs_id, "rules": global_rules},
            "cluster_head_policy": {"node_id": head_id, "rules": head_rules},
            "member_policy": {"nodes": member_ids, "rules": member_rules},
            "message_usage_hint": {
                "status_report": "UAV_STATUS 每 5 秒",
                "target_report": "TARGET_REPORT 触发式（发现目标立即上报）",
                "cluster_command": "CLUSTER_CMD 簇首 -> 成员（调整任务）",
                "mission_command": "CMD_MISSION / CMD_ACTION 由 GS 下达",
            },
        }

        notes = "rule_planner: output is fully deterministic and auditable. Replace this planner with an LLM backend when ready."
        if kb_context:
            notes += "\nKB_context_used: yes"

        return PlanArtifacts(decision_json=decision, notes=notes)


class LLMPlanner(Planner):
    """Placeholder for a real LLM planner.

    This demo does not ship model weights. You can plug in:
    - transformers local model
    - vLLM server
    - your intranet model service

    Expected behavior: take mission/scene + KB context, return JSON that validates decision_schema.
    """

    def __init__(self, endpoint: Optional[str] = None):
        self.endpoint = endpoint

    def generate(self, mission: Dict[str, Any], scene: Dict[str, Any], kb_context: str = "") -> PlanArtifacts:
        raise NotImplementedError(
            "LLMPlanner is a stub in this demo. Use RulePlanner for now, or implement a call to your model service."
        )
