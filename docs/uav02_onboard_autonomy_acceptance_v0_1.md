# UAV-02 平台侧自治：集成验收草案 v0.1

基线：`0e51c01`（包含 `6fe7057`）。本文是算法、Runtime、仿真和主控台四条开发线的集成检查表；接口字段以各线提交的可执行 fixture 为准。当前记录的是待验收条件，不是已完成的飞行证据。

## 首轮范围

UAV-02 有独立的常驻 Agent、任务存储和唯一的 PX4 MAVLink session。地面给出明确授权的 `takeoff → hold_position → land` 任务；平台保存进度。新任务和新起飞要求地面链路健康；断联后只能继续已授权的保持与降落，且每步仍需本地 Policy 准入。恢复链路后，平台补送有序事件，地面去重并恢复观察，不重复发动作。UAV-01/UAV-03 始终 disarmed。

本轮不验收 `goto`、未知场景的感知或安全着陆推断，也不把 Gazebo 真值位姿当成机载定位。算法候选计划必须经确定性校验、Runtime 的实时 Policy Gate 和唯一执行会话；小模型不可用时走事先定义的有限处理策略。

## 边界与证据

| 边界 | 负责人 | 集成时必须看见的证据 |
| --- | --- | --- |
| 任务提案与小模型 | 算法 | 本地推理的候选输出、校验结果、超时/非法输出处理；候选本身不授予飞行权限 |
| 任务、授权、动作、事件 | Runtime | 任务持久化、恢复游标、Policy 判定、动作幂等键、单机 session 所有权及有序事件 |
| 飞机与故障注入 | 仿真 | UAV-02 的 PX4/MAVLink 连通；只断地面链路时机载链路保持；01/03 状态不变 |
| 显示与重连 | 主控台 | 在线状态与最后确认状态有区别；按事件游标补齐，重复响应不重复显示或下发 |

跨线 fixture 应使用同一组 `task_id`、`node_id=UAV-02`、步骤/请求标识、事件序号和时间基准。若某线使用不同字段名，集成测试应显式适配并保留原始值，不能凭展示文本猜测动作是否完成。每项通过结论应记录实现提交 SHA、fixture 路径和测试命令。

## 首轮 Runtime 接口提案

Runtime 负责人于 2026-10-22 给出了待实现的 v1.0 接口。下面只作为组合测试的目标，直到其实现 SHA 与 fixture 提交后才算可执行契约。

平台代理进程支持 `fake` 和 `sitl` 模式。默认 `fake` 不连接 PX4；`sitl` 只为 UAV-02 独占 `14541`。服务只监听 loopback，所有平台 API 要求本机 token 文件对应的 Bearer token。地面 Runtime 从其三机 manifest 中排除 UAV-02 的接收会话，经带 token 的平台代理调用它。主控台网页断开不构成地面链路故障；地面服务定期发送的 heartbeat 才驱动平台代理的链路状态。

| 方法/路径 | 用途 |
| --- | --- |
| `POST /api/platform/tasks` | 校验并持久接收任务，返回 HTTP 202；后台 worker 独立于请求生命周期 |
| `GET /api/platform/tasks/{task_id}` | 查询任务和步骤状态 |
| `GET /api/platform/status` | 查询 `node_id`、`boot_id`、`store_id`、`execution_mode`、`event_seq`、`ground_link` 和当前任务 |
| `GET /api/platform/events?after_seq=N` | 按持久递增序号补取事件 |
| `GET /api/platform/events/stream` | SSE 事件流；断线后仍须用序号补取 |
| `POST /api/platform/link/heartbeat` | 地面服务与平台代理之间的链路心跳 |
| `POST /api/platform/tasks/{task_id}/cancel` | 请求取消；执行状态和终态仍以平台记录为准 |

任务 `contract_version=1.0`，包含 `node_id=UAV-02`、`task_id`、`task_version=1`、`request_id`、`trace_id`、`authorization` 和按序的 `steps`。授权包含操作员、ISO-8601 过期时间、`offline_policy=continue_authorized`、最大高度 3 m 和最大保持 10 s。首轮只接受 `takeoff → hold_position → land`。任务状态集合为 `accepted`、`executing`、`succeeded`、`failed`、`cancelled`、`recovery_required`；步骤与事件需要保留 `execution_id` 和版本以便去重。SQLite 持久保存任务、步骤与事件序号。进程重启后未完成任务进入 `recovery_required`，不得自动重放。取消或异常只在已有授权范围内执行 LAND 收束，不发 in-air disarm，也不把任务标成成功。

## 可执行验收情景

| ID | 输入/故障 | 必须观察到 | 失败判据 |
| --- | --- | --- | --- |
| A1 | 两次提交相同任务与稳定请求标识 | 只有一个任务和一组动作；第二次返回原任务/进度 | 重复 arm、takeoff 或新建执行链 |
| A2 | 同标识提交不同任务内容 | 明确冲突并拒绝执行 | 悄悄覆盖已授权任务 |
| A3 | UAV-02 已完成起飞后，执行中断地面 heartbeat | 平台持久化进度并只继续已授权的 `hold_position`/`land`；本机 PX4 session 仍可用 | 地面断联等同飞控断联，或断后产生新起飞/未经授权步骤 |
| A4 | 断联期间重启平台执行进程 | 同一任务进入 `recovery_required`，保留最后确认步骤和事件；不自动重发动作 | 从第一步重飞、丢失终态证据或静默宣称完成 |
| A5 | 恢复地面链路并重复拉取/重放事件 | 按游标补齐且稳定去重；动作记录与原请求可关联 | 补报变成新的飞行指令 |
| A6 | 小模型超时、输出非法或建议越权动作 | 确定性拒绝/预设安全处理，并记录原因 | 把模型输出直接送 MAVLink |
| A7 | UAV-02 执行期间观察 01/03 | 两机一直 disarmed，且无动作调用 | 目标路由串机或共用控制 session |
| A8 | 区分地面链路丢失与 UAV-02 飞控/遥测丢失 | 两种故障有不同原因和处置；飞控失联时不宣称任务成功 | 用缓存遥测判定动作完成 |
| A9 | 缺少/错误 Bearer token、过期授权、错误 node 或超出高度/保持时长 | 拒绝并记录原因，假 session 调用数为零 | 认证或授权失败仍发送命令 |
| A10 | POST 返回 202 后关闭该 HTTP 连接 | 任务仍由后台 worker 执行并可按 ID 查询 | 客户端断开导致任务丢失或重复执行 |
| A11 | 主控台网页断开但地面 heartbeat 持续；再单独停止 heartbeat | 第一种情况链路仍健康，第二种转为 `lost` | 以浏览器连接状态代替地面链路状态 |

`takeoff` 的通过证据包括 Policy allow、真实命令 ACK 和命令之后的新鲜高度稳定样本。`hold` 需要飞控模式/位置保持的可观测证据。`land` 需要真实 LAND ACK、落地与 disarm 证据，并沿用现有地面参考判据。任务终态不能只从 HTTP 200、ACK 或预定计时推断。

SITL 的 LAND 完成判据还依赖有效的地面标定和 `ground_reference`；地面网关透传时必须保留原始 `source_timestamp` 与 TTL，不得在转发时“续期”。断链时间若超过标定有效期，可由仿真侧验收监测器以独立、带 Bearer 的本机通道向平台代理提供新鲜证据，但这只能标为**评估 oracle**，不能送入机载模型输入，也不能据此宣称具备未知环境自主安全着陆能力。若缺少新鲜证据，真实 LAND 不得记为成功，应保留 `recovery_required` 等待人工核对。该路径仍待 Runtime 固定提交及联合窗口验证。

## 验证顺序

1. 各线提交 fixture 与最小接口，并给出 SHA。集成侧核对 `node_id`、任务/请求/事件 ID、授权范围、时间基准、状态和错误码；有分歧先定映射。
2. 在组合分支上跑离线端到端测试，使用假 session、可控时钟、临时任务库和可注入的地面链路。测试 A1–A8；断言假 session 的调用次数及 01/03 的零调用。
3. 通过后再安排一次 WSL/PX4/Gazebo 联合窗口。窗口前记录确切代码 SHA、端口所有权、三机初态和故障注入方式；窗口后保存 ACK、遥测、任务库、事件流及清理结果。

离线测试通过只证明接口和状态机；真实联合验收必须单独记录。若任何一线尚无可执行接口，对应情景记为“未测”，不能写成“通过”。
