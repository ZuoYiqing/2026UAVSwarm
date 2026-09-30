# 第二轮场景指代绑定交接

依据 Integration Owner 的 `docs/algorithm_side_round2_20260929.md` 和其交付的
`docs/fixtures/simple_recon_v0_1_scene_affordances.json`。算法侧代码只读取可供性数据，
不修改 Runtime、Gazebo、转换器或前端。主线场景清单状态为
`exported_from_physics_pending_review`，`coverage.complete_physical_map=false`；
这两个限制原样进入结果警告。

## 可复现结果

命令（从算法模块目录运行，先令 `PYTHONPATH=src`）：

```powershell
.\.venv\Scripts\python.exe -m uavswarm_llm_lab bind-scene D:\2026UAVSwarm\docs\fixtures\simple_recon_v0_1_scene_affordances.json '飞到北边那片楼群的东侧'
```

输入清单的规范化 JSON 哈希为
`1f431696ef96eaa1631ce60b0bf7d47c07a30ea619c706a5c909367e5c0b79ad`。

| objective | 绑定结果 | 下一步 |
| --- | --- | --- |
| 飞到北边那片楼群的东侧 | `city-block-4-3`，关系 `east_side`，中心 `N=350, E=-10`，原始 SDF 来源写入 binding | `ROUTE_PLANNING_REQUIRED`；没有导航航点或 proposal |
| 绕楼群一圈 | 同一楼群，关系 `circumnavigate` | `ROUTE_PLANNING_REQUIRED`；路径规划侧需要生成并验证绕行点 |
| 到最高的那栋楼旁边 | 52 m 并列：`link-block-4-3-2-1`、`link-block-4-3-3-2` | `AMBIGUOUS_HIGHEST_BUILDING`；要求操作员指定实体 ID |
| 到明确的建筑 ID 旁边 | 绑定该实体的中心与高度 | 仍需规划侧生成观察位，不能飞到建筑中心 |
| 到山谷东侧、到南边楼群 | 清单没有山谷；楼群中心在北侧 | 分别返回 `SCENE_REFERENCE_UNRESOLVED`、`DIRECTION_REFERENCE_MISMATCH` |

`楼群` 只是 `kind=building_cluster` 的通用中文表达，不是新增专有地名。
方位判定同时核对数值坐标：清单中的 `bearing_from_origin=北` 不代表 `E=0`，
结果始终保留 `E=-10 m`。`matched_text`、实体 ID、`reference_geometry`、来源文件、
清单哈希都保留以供复核。建筑尺寸是识别证据，**不等于可飞航点**。

## 感知目标与解析失败的区别

当目标被解析为 `reconnaissance`，派生 context 中保留 `OBSERVE` / `RETURN_HOME`
任务语义，但当前 `derive_proposal` 返回 `proposal=null`、`accepted=false`、
`reason_code=PERCEPTION_EXECUTION_UNAVAILABLE`，并列出
`OBSERVE_ENDPOINT_NOT_IMPLEMENTED` 与 `CAMERA_CAPABILITY_UNCONFIRMED`。
这表示**语义已解析、执行能力缺失**。无法绑定实体则返回
`SCENE_REFERENCE_UNRESOLVED` 等解析原因；两类结果不再都表现为“零分配”。
原有研究用结构化任务的 v0.1 提案 schema 保持不变。

若要在仿真中验证“是否观察到 target-001”，最小数据需求是有时间戳的 RGB 图像引用、
相机内参/视场、相机相对机体位姿、对应载具的场景定位和观察结果定义。可先以
640×480、5 Hz、图像年龄不超过 500 ms 作为**实验假设**建立基线；这些不是已确认
的 x500 或真机指标。`OBSERVE` 的成功证据还需定义目标 ID、图像/检测引用、置信度、
采集时间与对应节点。具体相机变体、真机能力及阈值须由仿真和机型负责人确认。

## 澄清通道建议

当 `objective` 与外部 `tasks[]` 同存，算法返回
`EXTERNAL_TASKS_FORBIDDEN` 及结构化 `clarification_request`：
`audience=originating_operator`、`mission_id`、冲突字段、问题文本与
`resolution=resubmit_objective_without_tasks`。调用方应在现有控制台把问题呈现给
最初下达目标的操作员；由该人修改或确认目标，再用新快照提交新请求。
算法不自动选边、不改写原目标，也不直接联系操作员或发送执行请求。

## 对转换器验收的边界

楼群清单只给障碍物与实体位置，**未给规划确认的 `scene_ned` 目标航点**。
因此本轮楼群绑定结果不能喂给 `proposalToPlan`，更不能把障碍物中心当 `GOTO`。
需要路径规划侧提供带来源、版本、净空和可达性检查的观察位/绕行候选点，
算法才可将候选点 ID 写入任务。上一轮的
`examples/simple_recon_flight_handoff.json` 仍使用集成负责人已验证的
`N=60 E=12 D=-20` 飞行验证点，已与当前转换器独立回归；它不代表楼群任务完成。

本轮没有将 `main` 合并进算法 worktree：当前实现只读取主线清单与转换器，
不需要改变模型/实验工作区的 Git 基线。若后续准备合并 PR，可在单独检查
主线差异和现有用户改动后再决定同步方式。
