# Runtime 演示接口 v1.0（R1–R5）

Runtime 维护本文、生产者和 [JSON fixture](fixtures/runtime_demo_readiness_v1.json)。
主控台消费这些字段；Simulation #98 提供面积函数和区域边界。这里不修改既有
控制协议、遥测端口、Policy Gate 权限规则、仿真或前端源码。

## R1：车辆快照与分值

`GET /api/vehicle-snapshot` 的 `vehicles[]` 增加：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `link_quality` | 整数 0–100 | 展示值，有显式演习覆盖时为覆盖分 |
| `link_quality_measured` | 整数 0–100 | 原始接收新鲜度评分，不受演习覆盖 |
| `link_quality_mode` | `LIVE` / `DEMO` | 仅指本行分值来源；不改变遥测和位置来源 |

同一持久 MAVLink 会话分别记录匹配 sysid/compid 的 `HEARTBEAT`、有限数值
`LOCAL_POSITION_NED` 的单调接收时刻。不增加 receiver，也不以快照发布时间、
本机发出的 GCS heartbeat 或其他报文延续样本寿命。两类评分取较低值：

- 心跳：在 0–2.5 s 由 100 降到 80，到 4.5 s 降到 0。
- 位置：在 0–0.5 s 由 100 降到 80，到 2 s 降到 0。
- 未收齐两类样本、RX 停止或节点离线/陈旧时为 0。

这是**接收新鲜度代理分数**，不是测得的射频强度、吞吐率、抖动或丢包率。
旧 `connected`、`telemetry.stale`、坐标字段及其判定不变；不能把 0 分
或 DEMO 覆盖当成新的飞行完成判据。单测验证新鲜样本与超时边界，
现场正常分布与实际停机下降时间仍待三机验收。

## R2/R3：受控演习

仅在本地 Runtime 进程启动前设置 `UAV_RUNTIME_DEMO_ENABLED=1` 才启用。
现有 loopback 监听不变；这不是远程认证接口，不要通过对外代理暴露写路由。
写请求要求 loopback 客户端、`application/json`、1–4096 字节请求体，
并拒绝不在已有白名单里的浏览器 Origin。无 Origin 的本机 CLI 可以调用。

| 路由 | 请求/结果 |
| --- | --- |
| `GET /api/demo/state` | 返回 `enabled`、`mode`、`overrides`、`held_out`、`assignments`；未开启仍可查询 |
| `POST /api/demo/inject` | `{"node_id":"UAV-02","kind":"link_degraded","value":18,"duration_s":60}` |
| `POST /api/demo/inject` | `{"node_id":"UAV-02","kind":"link_lost"}`，覆盖为 0；`recover` 等价于清除 |
| `POST /api/demo/clear` | `{"node_id":"UAV-02"}`，立即撤销该机覆盖 |

仅接受已注册且启用的节点。降级分须为 1–59 的整数，省略取 18；
降级/失联的有效期为 0.1–300 秒，默认 60 秒。回包包含状态和 `changed`。
覆盖有效期内重发相同参数不延长 TTL、不重复产生动作；清除不存在的覆盖
为 `changed:false`。过期后显式重新注入是新演习。后台每 250 ms 检查到期，
不依赖前端轮询；GET 不执行处置。清除后立即展示当前实测分，不人为抬高到 100。

主要错误：`404 demo_disabled`、`400 invalid_demo_node`、
`invalid_demo_kind`、`invalid_demo_value`、`invalid_demo_duration`、
`unexpected_demo_field`、`invalid_demo_body_length`；
`403 local_demo_origin_required`、`415 json_content_type_required`。

演习注入触发规则：`<10` 优先模拟返航，`<40` 模拟 HOLD；未覆盖且
实测分恢复到 `>=60` 时允许重新入演习队列。动作建议先经过统一 Policy Gate，
只有 allow 才调用 Fake Adapter。不调用飞行动作端点，不改网络、MAVLink、
PX4、Gazebo 或正在运行的真实计划。

审计链包含 `demo_inject` → `policy_decision_event` →
`adapter_execution_started` → `action_result`，以及可能的
`demo_reassignment`、`demo_clear`、`demo_recovered`。
演习工作项 ID 为 `demo-work:<node_id>`，分配给可用演习节点或保持未分配，
不是实际任务重调度。事件保留 `trace_id`、规则名及原因；DEMO 动作结果是
`status:simulated`、`result:simulated`，并标记
`execution_authorized:false`、`flight_command_sent:false`。
通过既有 `/api/events`、`/api/policy/decisions`、`/api/actions/recent`、
`/api/replay` 消费；不加入真实动作生命周期或姿态。演习状态仅在进程内，
重启不会重播注入；审计记录仍可回放。

## R4：被动任务进度

`GET /api/mission/progress` 观察现有 `POST /api/plans/execute` 的最近
一次执行；不启动、批准或改变执行。单独操作动作和 standalone patrol
都不是这个接口的任务来源。当前无执行时 `status:unavailable`，计数为
`null`；其余状态为 `running`、`completed`、`failed`、`blocked`。

- `mission_id` 为计划 ID，`run_id` 区分每次执行，不是 Gazebo run ID；
  `source_timestamp` 表示进度更新时间，非 GET 返回时间。
- `completion_basis:verified_waypoints` 时，`completion_pct` 是已确认
  到达的 GOTO 步骤数 / 计划 GOTO 步骤数。ACK、模板规划、时间经过都不计入；
  100% 航点不代表计划已经完成或车辆已落地。
- `vehicles[]` 包含 `node_id`、`active`、`waypoints_reached`、
  `waypoints_total`。`vehicles_active` 表示仍分配在本次执行的节点数，
  不是在线、解锁或空中数量。经现有执行器确认 RETURN_HOME 完成后该机移出、
  `degraded:true`；确认 LAND 完成后也移出。结束后活跃数为 0。
- `targets_found`、`targets_total` 暂为 `null`；无目标检测生产者。
  并发执行时此接口展示最近启动的一次，通过 `run_id` 区分；不声称提供
  多任务调度或恢复持久化。

**面积可选依赖：**组合检出应包含 Simulation #98 的
`914b0423613fb4feb3e2f0baf4226020f5fa0a66` 或兼容版本、匹配的场景文件，
且仓库根目录在 Python import path 上。设置
`UAV_RUNTIME_COVERAGE_AREA_ID=three-uav-patrol-coverage-v1` 与正数
`UAV_RUNTIME_COVERAGE_FOOTPRINT_M`；足迹半径由验收场景显式选择。
复用 S3 `AreaCoverage`，只投影该动作已匹配的到达样本及相同原点世代、
场景与地图的有效标定，local NED 到 scene NED 只平移一次。

输出包括 `area_total_km2`、`area_covered_km2`、`coverage_pct` 及
`coverage.polygon`（`scene_ned`、米、`north_m/east_m` 顶点）。
面积是**到达样本的几何足迹并集**，不是连续航线覆盖、目标发现或相机实测；
不提供逐栅格可视证据。缺生产者、配置或地图不匹配时面积为 `null`，
见 `coverage_reason`，不影响已验证航点的百分比。

## R5：失败归因

场景地面 LAND 的观测超时接入既有 `classify_incomplete_evidence`。
`action_result` 审计、recent action 投影和回放保留
`completion_state`（例如 `partial_evidence`）、
`completion_timeout_detail` 与原 `failure_reason`。
分类仅描述观测为何不足，**不证明坠机，不把超时改成成功**。
拒绝、ACK 超时和地面判据不满足仍按原语义区分。

## 验证范围

Fixture 是可复跑的示例，不是 LIVE 遥测或飞行结果。
专项测试使用内存消息、测试会话、临时审计及本机 HTTP；不连接 PX4。
组合环境仍需检查真实 RX 分值、前端来源标记、Runtime 计划进度与 S3 标定。
演习注入与真实飞行动作链路是两项不同的验收。

2026-11-13，Windows / CPython 3.11.7：

- `python -B -m pytest -q -rs -p no:cacheprovider --basetemp .tmp_runtime_demo_final_20261113`
  → 935 passed、7 skipped、0 failed。跳过：5 项需要三机 PX4 端点，
  1 项真实巡逻 opt-in，1 项独立 Runtime 检出缺少可选 S3 提供者。
- 将上述固定 Simulation 检出加入 `PYTHONPATH` 后，
  `python -B -m pytest -q -rs -p no:cacheprovider tests/unit/test_runtime_demo_readiness.py --basetemp .tmp_runtime_demo_s3_final_20261113`
  → 19 passed、0 skipped、0 failed。另用同版本相机 manifest 和场景
  做只读导入与面积计算检查，确认四点边界及几何面积增长；未打开接收器。
- LAND 审计测试仅替换依赖可用性检查和测试会话，不改生产依赖门槛。
  验证场景地面超时仍是 `timed_out`，而分类和说明贯通到结果、审计和回放。
