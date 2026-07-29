# 跨工作线交接提示词

下面三段可以分别发给主前端、Gazebo/平台仿真、Agent 对话。发送时保留路径和约束，不要让
各工作线另造一套不兼容的数据结构。

## 1. 给主前端对话

```text
你负责 D:\2026UAVSwarm\frontend\swarm-console 主前端。三维仿真子应用已经位于
frontend/swarm-console/simulation-3d，请先阅读：
1. simulation-3d/docs/VEHICLE_FEED_CONTRACT_ZH-CN.md
2. simulation-3d/public/contracts/vehicle-snapshot.schema.json
3. simulation-3d/src/main.js 中的 window.SwarmSimulationBridge

目标：把三维仿真作为平台的真实功能页接入，而不是重新实现 Cesium 场景。

要求：
- 在现有导航中提供明确的“三维仿真”入口，可路由进入全尺寸页面；若采用 iframe，优先
  同源部署并让三维画布占满内容区，不套装饰性卡片。
- 主前端负责连接运行时后端 WebSocket，接收 Vehicle Snapshot 1.0 完整快照，然后通过
  SwarmSimulationBridge.applyVehicleSnapshot 或 postMessage
  `uav-swarm/vehicle-snapshot` 传给三维子应用。
- 收到 `uav-swarm/simulation-ready` 后再发送最新快照；页面重连后立即发送一份完整状态。
- 不写死载具数量、ID 或机型；平台增删以 `vehicles` 数组为准。
- 明确显示数据源、连接状态、最后更新时间和断线状态。断线时保留最后状态但标记陈旧，
  不伪造继续飞行。
- 不从浏览器直接连接 MAVLink、Gazebo Transport 或 DDS。
- 控制命令必须经过现有权限、确认和运行时后端，不通过三维显示 Bridge 下发。
- 保留其他并行工作线的未提交改动，不进行无关重构，不提交 Git。

完成后给出：修改文件、路由地址、WebSocket/Bridge 数据流、可复现验证命令和仍需后端
提供的接口。
```

## 2. 给 Gazebo / 平台仿真对话

```text
你负责 WSL 中 Gazebo/PX4 多平台仿真及运行时数据输出。前端三维显示已经定义统一数据契约：
D:\2026UAVSwarm\frontend\swarm-console\simulation-3d\docs\
VEHICLE_FEED_CONTRACT_ZH-CN.md
机器可读 Schema：
D:\2026UAVSwarm\frontend\swarm-console\simulation-3d\public\contracts\
vehicle-snapshot.schema.json

目标：让 Gazebo 中真实存在的平台成为权威状态源，使前端按后端数据动态显示，而不是依赖
浏览器内置飞行路径。

要求：
- 先把当前单机起飞链路稳定下来，再扩展多实例；每个实例使用稳定且唯一的 vehicle id、
  MAVLink system id、端口和命名空间。
- 支持至少 multirotor；架构上预留 fixed_wing 和 vtol，不把模型假设写死为四旋翼。
- 建立 Gazebo/PX4 状态到 Vehicle Snapshot 1.0 的适配层，以 5 至 10 Hz 输出完整快照。
- 明确输出坐标系。PX4 local position 通常为 NED，可以原样标记 `pose.frame=NED`，不得把
  NED 数值误标为 ENU；同时记录统一任务原点，后续支持 WGS84。
- 快照包含 timestamp、source(kind=simulation)、connected、pose、attitude、velocity、
  armed、mode、电池等；不存在的平台从 full_state 快照移除。
- 仿真适配层输出给运行时后端，不让浏览器直接依赖 Gazebo Transport/DDS/MAVLink。
- 为进程启动、停止、实例端口、健康检查和日志写可复现脚本与文档。
- 不修改三维显示的数据契约；发现字段不足时先提出向后兼容的版本变更。
- 保留其他并行工作线的未提交改动，不提交 Git。

完成后给出：一条完整数据样例、多实例 ID/端口表、启动停止命令、坐标转换说明、状态输出
频率和已验证的飞行平台类型。
```

## 3. 给 Agent 对话

```text
你负责把无人平台建模为无人智能体。三维显示的数据契约在：
D:\2026UAVSwarm\frontend\swarm-console\simulation-3d\docs\
VEHICLE_FEED_CONTRACT_ZH-CN.md

目标：让 Agent 状态与平台遥测关联，但严格区分“意图/决策”和“飞控真实状态/控制命令”。

要求：
- 每个 Agent 通过稳定的 vehicle id 绑定平台；不要按数组下标、显示名称或临时端口绑定。
- 先使用兼容字段 `agent.id`、`agent.status`、`agent.intent`，由运行时后端合并进完整快照。
- Agent 可以生成任务意图、候选动作和解释，但不能绕过任务授权、冲突检查、地理围栏、
  人工确认和飞控安全门直接下发控制。
- 设计清晰状态机，例如 unassigned/planning/ready/executing/paused/blocked/completed/error，
  并说明每个状态由谁驱动、如何超时、如何恢复。
- 实机与仿真平台使用同一抽象，但 source.kind 必须保留 physical/simulation，禁止混淆。
- 平台断联时 Agent 必须收到明确事件并停止把预测位置冒充真实遥测。
- 给出 Agent 输出到运行时后端的独立消息格式；运行时后端负责校验和合并，前端只显示。
- 保留其他并行工作线的未提交改动，不提交 Git。

完成后给出：Agent 生命周期、vehicle id 绑定规则、权限/安全门、消息样例、异常与断联处理、
以及如何把 agent 字段合入 Vehicle Snapshot 1.0。
```
