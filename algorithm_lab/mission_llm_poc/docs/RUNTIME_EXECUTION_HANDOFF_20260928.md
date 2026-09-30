# Algorithm Lab → Runtime 执行接口交接（2026-09-28）

依据 `docs/algorithm_runtime_execution_contract_v0_1.md`（Runtime `524cdf8`）。
算法模块仍只产生 Mission Proposal，不提交执行请求，也不授予执行权限。

## 提案与转换边界

- `assignments[]` 的每项为 `task_id`、`node_id`、有序的大写 `actions[]`、有序的 `waypoint_ids[]`、原因码和解释。`node_id` 必须复制到展开后的每个 step。
- 航点 ID 只在同一次输入 context 的 `waypoints[]` 中解析。坐标为共享 `scene_ned` 的 `north_m/east_m/down_m`；转换器不得换算到单机 local NED。`down_m` 向下为正。
- 转换前全量运行 proposal schema 和语义校验，再检查所有动作和航点。仅 `TAKEOFF/GOTO/LAND` 可展开；任一不支持动作、缺失航点或缺失目标载具均拒绝整份提案，并返回具体 task/action/waypoint 与原因。不得静默跳过或提交可执行子集。
- 一个 `GOTO` 按 `waypoint_ids[]` 顺序展开为多个 goto step。`TAKEOFF` 的高度来自明确的飞行验证任务配置；不得把约束中的最低高度臆造为任务高度。`LAND` 不带参数。
- `operator_id` 和审批决定由人工及 Runtime 提供，不能从模型输出推断。`execution_authorized` 始终为 `false`。当前研究巡检任务需要 `OBSERVE` 与 `RETURN_HOME`，因此不得转换成“已完成巡检”的执行计划。
- `assignments[]` 没有时间调度语义；多机 step 的全局顺序须另行确定并做冲突检查。仅靠数组顺序不能声称完成协同巡检或安全间距验证。

## 场景身份

建议把 `scene_id` 与 `map_version` 放在顶层 `plan`，各 step 继承同一场景身份，不重复携带。转换器应要求 proposal 与其原始 context 两字段完全一致。Runtime 执行前应把这两个值与当前活动场景及地图版本比对；任一缺失、未知或不一致，整份计划在起飞前拒绝。建议分别返回 `scene_id_mismatch`、`map_version_mismatch`；活动身份不可用时返回 `scene_identity_unavailable`。这些是待双方实现的建议原因码，不是当前端点已经具备的能力。

在 Runtime 完成该校验之前，不能把“提案字段一致”当作实时场景匹配证据。坐标标定另需按 Runtime 的 60 秒有效期独立检查。

## 单独的飞行验证样例

`examples/flight_validation_only.json` 是合成输入，动作只含 `TAKEOFF/GOTO/LAND`，目标仅为验证提案形态及转换规则。它不含感知结果，不证明巡检、航线可飞性、避障、间距、能源或时序安全。此文件及其基线输出不得直接视为实机执行授权。
