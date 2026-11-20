"""M-v0.1: mixed-team work allocation on fictional maintenance snapshots."""
from __future__ import annotations

from collections import Counter
from itertools import product

from .contracts import ContractError


METHODS = ("fixed", "rules", "model", "model-no-preference")
FILES = "benchmarks/platform_coordination_m_v0_1.json"
TERMINAL = {"COMPLETE", "NOT_NEEDED"}
WAIT_CODES = (
    "WAIT_FOR_AERIAL_EVIDENCE", "REVIEW_PENDING", "EVIDENCE_SCOPE_MISMATCH",
    "NO_ELIGIBLE_NODE", "NODE_BUSY", "PREFERRED_UNAVAILABLE", "UNASSIGNED",
)
PUBLIC_RULES = (
    "这是虚构巡检的下一轮任务派工；只给候选分工，不输出飞行或设备指令。",
    "一个平台本轮最多接一件事，必须在线、不 stale、电量不少于题设阈值、有任务要求的能力。",
    "证据必须属于同一任务和对象，并来自具备任务能力的平台。captured_only 表示已采集、待核实，不重派，也不视为已核实。",
    "已有有效核实结果的任务不重做。地面 B 组复核只由同一资产的已核实异常打开；核验结果无异常时不安排地面 B 组复核。",
    "尽量同时推进无依赖的工作。未安排且仍须跟进的任务写 deferred 和 reason_code；完成或不需做的任务不要放入两张清单。",
)


def snapshot(bench: dict, case: dict) -> dict:
    return {
        "objective": bench["objective"], "scene": bench["scene"],
        "rules": list(PUBLIC_RULES), "min_battery_pct": bench["min_battery_pct"],
        "tasks": bench["tasks"],
        "fleet": [{**node, **case["fleet_patch"].get(node["node_id"], {})} for node in bench["fleet"]],
        "observations": [bench["evidence_catalog"][ref] | {"evidence_id": ref} for ref in case["observations"]],
    }


def check_state(state: dict) -> tuple[dict, dict, dict]:
    tasks = {task["task_id"]: task for task in state["tasks"]}
    fleet = {row["node_id"]: row for row in state["fleet"]}
    proof = {row["task_id"]: row for row in state["observations"]}

    def observed(task_id):
        row = proof.get(task_id)
        if row is None:
            return None
        task = tasks[task_id]
        node = fleet.get(row["by"])
        if (row["asset_id"] != task["asset_id"] or node is None or not row["evidence_id"]
                or task["capability"] not in node["capabilities"]):
            return "EVIDENCE_SCOPE_MISMATCH"
        return row["status"]

    status = {}
    for task_id, task in tasks.items():
        fact = observed(task_id)
        if fact in {"verified_clear", "verified_anomaly"}:
            status[task_id] = "COMPLETE"
        elif fact == "captured_only":
            status[task_id] = "REVIEW_PENDING"
        elif fact:
            status[task_id] = "EVIDENCE_SCOPE_MISMATCH"
        elif parent := task.get("requires_anomaly_from"):
            upstream = observed(parent)
            if tasks[parent]["asset_id"] != task["asset_id"]:
                status[task_id] = "WAIT_FOR_AERIAL_EVIDENCE"
            elif upstream == "verified_clear":
                status[task_id] = "NOT_NEEDED"
            elif upstream == "verified_anomaly":
                status[task_id] = "READY"
            else:
                status[task_id] = "WAIT_FOR_AERIAL_EVIDENCE"
        else:
            status[task_id] = "READY"

    eligible = {
        task_id: sorted(
            (node_id for node_id, node in fleet.items()
             if node["online"] and not node["stale"] and node["battery_pct"] >= state["min_battery_pct"]
             and task["capability"] in node["capabilities"]),
            key=lambda node_id: (node_id != task["preferred"], node_id),
        ) for task_id, task in tasks.items()
    }
    return tasks, status, eligible


def rule_proposal(state: dict, *, fixed: bool) -> dict:
    tasks, status, eligible = check_state(state)
    ready = [key for key in tasks if status[key] == "READY"]
    options = [[node for node in eligible[key] if not fixed or node == tasks[key]["preferred"]] + [None]
               for key in ready]
    best: tuple = ()
    best_quality = (-1, -1)
    for combo in product(*options):
        used = [node for node in combo if node is not None]
        if len(used) != len(set(used)):
            continue
        quality = (len(used), sum(node == tasks[key]["preferred"] for key, node in zip(ready, combo)))
        if quality > best_quality:
            best, best_quality = combo, quality
    active = {key: node for key, node in zip(ready, best) if node is not None}
    deferred = {key: value for key, value in status.items() if value not in TERMINAL and value != "READY"}
    for key in ready:
        if key in active:
            continue
        if not eligible[key]:
            deferred[key] = "NO_ELIGIBLE_NODE"
        elif fixed and tasks[key]["preferred"] not in eligible[key]:
            deferred[key] = "PREFERRED_UNAVAILABLE"
        else:
            deferred[key] = "NODE_BUSY"
    return {
        "assignments": [{"task_id": key, "node_id": node} for key, node in active.items()],
        "deferred": [{"task_id": key, "reason_code": code} for key, code in deferred.items()],
    }


def assess(state: dict, proposal: object, expected: dict | None = None) -> dict:
    tasks, status, eligible = check_state(state)
    assigned: dict = {}
    deferred: dict = {}
    used: set = set()
    errors = []

    def valid_row(row, second):
        return (isinstance(row, dict) and set(row) == {"task_id", second}
                and all(isinstance(value, str) for value in row.values()))

    if (not isinstance(proposal, dict) or set(proposal) != {"assignments", "deferred"}
            or not isinstance(proposal["assignments"], list) or not isinstance(proposal["deferred"], list)):
        errors.append("PROPOSAL_SHAPE_INVALID")
    else:
        for row in proposal["assignments"]:
            if not valid_row(row, "node_id"):
                errors.append("ASSIGNMENT_SHAPE_INVALID")
                continue
            key, node = row["task_id"], row["node_id"]
            if key not in tasks:
                errors.append("TASK_NOT_IN_SCOPE")
                continue
            if key in assigned or node in used:
                errors.append("DOUBLE_BOOKED_TASK_OR_NODE")
            assigned[key] = node
            used.add(node)
            if status[key] == "COMPLETE":
                errors.append("ALREADY_VERIFIED_REPEATED")
            elif status[key] == "NOT_NEEDED":
                errors.append("UNNEEDED_FOLLOWUP")
            elif status[key] == "WAIT_FOR_AERIAL_EVIDENCE":
                errors.append("PREMATURE_GROUND_HANDOFF")
            elif status[key] != "READY":
                errors.append("UNVERIFIED_WORK_REASSIGNED")
            if node not in eligible[key]:
                errors.append("INELIGIBLE_PLATFORM")
        for row in proposal["deferred"]:
            if not valid_row(row, "reason_code"):
                errors.append("DEFERRAL_SHAPE_INVALID")
                continue
            key, code = row["task_id"], row["reason_code"]
            if (key not in tasks or key in assigned or key in deferred
                    or status[key] in TERMINAL or code not in WAIT_CODES):
                errors.append("INVALID_DEFERRAL")
                continue
            deferred[key] = code

    result = {
        "valid_proposal": not errors, "violations": errors,
        "retained_verified": sorted(key for key, value in status.items() if value == "COMPLETE"),
        "not_needed": sorted(key for key, value in status.items() if value == "NOT_NEEDED"),
    }
    if expected is not None:
        result["strict_correct"] = not errors and set(assigned) == set(expected["assigned_tasks"]) and deferred == expected["defer"]
        result["missed_required_assignments"] = sorted(set(expected["assigned_tasks"]) - assigned.keys())
    return result


def schema_for(state: dict) -> dict:
    keys = [row["task_id"] for row in state["tasks"]]
    nodes = [row["node_id"] for row in state["fleet"]]

    def rows(field, options):
        return {"type": "array", "maxItems": len(keys), "items": {
            "type": "object", "additionalProperties": False, "required": ["task_id", field],
            "properties": {"task_id": {"type": "string", "enum": keys},
                           field: {"type": "string", "enum": options}},
        }}

    return {
        "type": "object", "required": ["assignments", "deferred"], "additionalProperties": False,
        "properties": {"assignments": rows("node_id", nodes), "deferred": rows("reason_code", list(WAIT_CODES))},
    }


def run_episode(bench: dict, decide) -> dict:
    """Advance a toy task ledger only from validated proposals; not a flight simulator."""
    scenario = bench["episode"]
    observations = []
    transitions = []
    offline_patch: dict = {}
    done = False
    for number in range(1, scenario["round_limit"] + 1):
        state = snapshot(bench, {"fleet_patch": offline_patch, "observations": []})
        state.update(round=number, observations=list(observations),
                     latest_feedback=transitions[-1]["feedback"] if transitions else [])
        proposal, trace = decide(state)
        audit = assess(state, proposal)
        tasks = {row["task_id"]: row for row in state["tasks"]}
        dropped = scenario["drop_node"] if number == scenario["drop_during_round"] else None
        feedback = []
        if dropped:
            offline_patch[dropped] = {"online": False}
            feedback.append({"kind": "NODE_OFFLINE", "node_id": dropped})
        if not audit["valid_proposal"]:
            feedback.append({"kind": "PROPOSAL_REJECTED", "reasons": audit["violations"]})
        else:
            for order in proposal["assignments"]:
                key, node = order["task_id"], order["node_id"]
                if node == dropped:
                    feedback.append({"kind": "TASK_RESULT_MISSING", "task_id": key, "node_id": node})
                    continue
                evidence = {"evidence_id": f"sim-{number}-{key}", "task_id": key, "asset_id": tasks[key]["asset_id"],
                            "by": node, "status": scenario["simulated_result_by_task"][key]}
                observations.append(evidence)
                feedback.append({"kind": "SYNTHETIC_EVIDENCE", "record": evidence})
        transitions.append({"round": number, "input": state, "proposal": proposal, "model_trace": trace,
                            "validation": audit, "feedback": feedback})
        _, status, _ = check_state({**state, "observations": observations})
        done = all(value in TERMINAL for value in status.values())
        if done:
            break
    return {"scenario_id": scenario["scenario_id"], "simulated_completion": done,
            "final_task_states": status, "transitions": transitions}


def evaluate(bench: dict, method: str, model_call=None) -> dict:
    if method not in METHODS or (model_call is not None) != method.startswith("model"):
        raise ContractError("MISSION_METHOD_AND_MODEL_DISAGREE")
    def decide(state):
        if model_call is None:
            return rule_proposal(state, fixed=method == "fixed"), None
        public = state
        if method == "model-no-preference":
            public = {**state, "tasks": [{key: value for key, value in task.items() if key != "preferred"}
                                          for task in state["tasks"]]}
        return model_call(
            "根据巡检目标、设备能力和已反馈证据，只决定这一轮派工。"
            "只返回 JSON（assignments 与 deferred），不宣称任务完成。", public, schema_for(state), 256,
        )

    rows = []
    for case in bench["cases"]:
        state = snapshot(bench, case)
        proposal, trace = decide(state)
        rows.append({"case_id": case["case_id"], "pair": case["pair"], "input": state,
                     "expected": case["expected"], "proposal": proposal, "model_trace": trace,
                     **assess(state, proposal, case["expected"])})
    pairs = {row["pair"] for row in rows}
    episode = run_episode(bench, decide)
    return {"cases": rows, "episode": episode,
            "conditions": {"preferred_nodes_visible_to_model": method == "model" if model_call else None},
            "metrics": {
        "snapshots": len(rows), "strict_correct": sum(row["strict_correct"] for row in rows),
        "valid_proposals": sum(row["valid_proposal"] for row in rows),
        "pairs": len(pairs), "both_snapshots_correct": sum(
            all(row["strict_correct"] for row in rows if row["pair"] == pair) for pair in pairs),
        "violations": dict(Counter(code for row in rows for code in row["violations"])),
        "missed_required_assignments": sum(len(row["missed_required_assignments"]) for row in rows),
        "episode_completed_in_simulation": episode["simulated_completion"],
        "episode_rounds": len(episode["transitions"]),
    }}
