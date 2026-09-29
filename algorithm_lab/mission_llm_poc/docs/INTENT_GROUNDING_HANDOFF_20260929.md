# 自然语言目标 → 任务清单：最小验证与集成答复

本次针对 `docs/algorithm_side_next_steps_20260929.md`，代码仍位于独立 Algorithm Lab 模块。

## 已实现的最小闭环

输入 `examples/simple_recon_flight_intent.json` **不含 `tasks[]`**；它提供自然语言 `objective`、合成集群快照、共享 `scene_ned` 航点和带来源的可供性 `regions[]`。`ground` 命令先从目标原文匹配供应方给出的标签，按出现顺序绑定到 `region_id`，再用供应方给出的 `waypoint_ids` 生成 `tasks[]`，最后复用原有载具分配与提案校验器。绑定记录包含 `matched_text`、目标 ID、航点 ID、`source_reference`。没有匹配、歧义或外部输入 `tasks[]` 时直接拒绝。

这个规则基线只认明确给出的标签；它不推断未知地名，也不算航线。飞行验证动作模板要求目标明确按顺序写出“起飞、前往、降落”；含否定或混合巡检意图的文本被拒绝。巡检模板会保留 `OBSERVE`、`RETURN_HOME`，目前不能交 Runtime 执行。`objective` 是权威意图；外部 `tasks[]` 不可同时作为输入，冲突应要求澄清，不能让模型静默覆盖。

另有 `ground-model` 本机模型入口：模型只提出意图类型、有序区域 ID 与从目标原文复制的指代片段；确定性校验拒绝虚构 ID、乱序、非原文片段和过期快照。若片段并非供应方标签的精确匹配，结果只留作人工语义审核候选，不输出可供转换器使用的 `proposal`。本轮已用本地 4B Q4 模型完成一次真实请求：输出 `flight_validation`，绑定到 `verified-flight-route-001`，通过受限 JSON Schema 和确定性检查；端到端 2.92 秒，110/123 prompt/completion tokens。原始记录保存在 D 盘忽略目录 `artifacts/runs/request-20260929T145917705Z`。这只是一条明确 ID 的样例，**不是自然语言泛化准确率**。

## `simple_recon_v0_1` 交付物

- 输入：`examples/simple_recon_flight_intent.json`
- 可复现输出：`examples/simple_recon_flight_handoff.json`，其中 `context` 与 `proposal` 可直接传给 Runtime 侧 `proposalToPlan(..., {takeoffAltitudeM: 3})`
- 场景：`scene_id=simple_recon_v0_1`、`map_version=simple_recon_v0_1-map-1`
- 航点：`N=60 E=12 D=-20`，来自集成负责人文件第 4.2 节所述已验证路线，不是 Algorithm Lab 生成的坐标
- `verified-flight-route-001` 是本实验为这条交接路线建立的局部引用名，**不是** `scene.json` 中已存在的实体；它不能用于推断其他区域或航线
- 动作：`TAKEOFF/GOTO/LAND`，起飞高度 `3 m` 由转换调用显式提供
- 目标：`UAV-01`，`execution_authorized=false`

该输入的 `source=synthetic_benchmark`：在线、位置、电量和能力字段只是测试假设，**不是本机此刻的遥测**。输出 `execution_ready=false`。真实执行前应换成新鲜 Runtime 快照，确认载具能力、场景与标定，再由人提供 `operator_id` 并审批。算法不发送 `/api/plans/execute` 请求。本样例仅为飞行验证，不能称为完成巡检。已用真实 JS 转换器在本机展开为 3 个 step；没有提交执行端点。

## 多机时序接口答复

1. 当前 proposal 不增加绝对时刻或时间窗字段；现有输入没有速度包线、延迟预算与并发执行能力，写出数值时间会形成伪保证。后续可版本化加入语义顺序约束（例如 `A` 完成后才能开始 `B`），绝对排程由调度器计算。
2. Algorithm Lab 提供任务意图、区域绑定与载具分配候选。航迹几何、间距和时间可行性由规划/调度侧判定并可否决，Runtime 执行前再检查实时状态和 Policy。
3. 在时序接口上线前，`assignments[]` 仅代表每机各自的动作序列，不构成协同、同时起飞或安全间隔保证。当前 Runtime 依次执行 step，不能把三机分配结果写成“三机协同飞行已验证”。

## 缺失数据与下一步

`scene.json` 尚缺已导入 Gazebo 的 12 栋楼；当前不能把它当完整障碍物真值。真机的续航、相机、视场与速度数据仍未确定，规则基线不使用这些参数。若需在自然语言里指代“楼群东侧”等地点，请集成侧提供带来源和版本的场景可供性清单；过渡期可使用显式仿真假设，但须标明并经人审核。模型语义准确率仍需在更丰富、标注过的指代数据上独立评测。

4B Q4 首次真实请求曾因顶层 `reason_code` 不匹配而被拒。加强 schema 和提示词后，本轮已真实复跑原三机输入：顶层原因码正确，JSON 合法，三项分配正确；但模型仍宣称 “Direct path feasible within constraints”，并在 warning 中假定电量足够。原版校验器曾误判通过，现已增加有限的未经证明安全宣称过滤；对同一原文离线回放返回 `UNPROVEN_ROUTE_CLAIM`、`UNPROVEN_ENERGY_CLAIM`，`accepted_proposal=null`。原始记录位于 `artifacts/runs/request-20260929T145638765Z`。这项过滤不能证明没有其他形式的幻觉，也不代替规划侧的几何及能源审查。两次请求后模型服务均已停止。
