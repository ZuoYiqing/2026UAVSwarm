# Simulation Backends Plan

## 1) 本步目标

明确当前仿真后端路线、备选路线、扩展顺序，以及各类仿真器与当前 runtime / adapter / backend 架构的关系。

本阶段只新增设计文档，不修改代码，不接入新的仿真器，不改变 protocol / policy contract。

---

## 2) 当前仿真路线判断

### 2.1 当前主线

当前主线仍然是：

```text
PX4 SITL + Gazebo
```

原因：

- 当前软件主线已具备 `mavlink adapter`、`px4_sitl_backend` readiness、optional dependency check、connect probe 与 `check-backend` 诊断入口；
- 当前最小真实飞控 smoke 目标仍然是 `backend_connected` 后进入 `takeoff smoke`；
- PX4 SITL + Gazebo 与 MAVLink、多旋翼、飞控 readiness、takeoff smoke 的当前目标最贴合；
- fake adapter 已经作为稳定测试基线存在，不需要用多个真实仿真器替代 fake baseline。

### 2.2 当前不同时接多个真实仿真后端

当前不应同时推进 PX4、ArduPilot、Webots、AirSim 多条真实仿真链路。原因：

- 多仿真器并行接入会扩大 backend seam、环境依赖、文档与测试矩阵；
- 当前更重要的是先把一条最短真实链路跑通：`PX4 SITL readiness -> backend_connected -> takeoff smoke`；
- 过早引入多仿真器会把控制面、adapter/backend、环境脚本和验收标准混在一起，导致路线发散。

### 2.3 fake adapter 的定位

fake adapter 继续作为稳定测试基线：

- 用于默认 runtime / policy / audit / replay 回归；
- 不依赖真实仿真器、网络、MAVLink 或图形环境；
- 不替代 PX4 SITL 主线，但为 CI 和本地开发提供稳定 fallback。

---

## 3) 仿真后端分类

### A. PX4 SITL + Gazebo

**定位：当前第一主线。**

适合：

- 飞控链路 readiness；
- 多旋翼基础动作；
- MAVLink endpoint / heartbeat / connect probe；
- 第一轮 `takeoff smoke`；
- 后续最小 flight backend 验证。

当前接入策略：

- 继续沿用 `mavlink adapter -> px4_sitl_backend` seam；
- 先完成 `backend_connected` 手工验证；
- 再进入只包含最小动作的 `takeoff smoke`；
- 不在本阶段扩展复杂任务、多机或 GUI。

---

### B. ArduPilot SITL

**定位：后续备选，不作为当前第一接入对象。**

适合：

- 无人车、无人船、多平台扩展；
- ArduPilot 生态平台；
- 后续对 MAVLink 兼容路径进行横向验证。

当前不优先接入原因：

- 当前 PX4 SITL backend readiness 已经开始成形；
- 过早接入 ArduPilot 会要求新增 backend config、probe 语义、环境 runbook 与测试矩阵；
- 在 PX4 `backend_connected + takeoff smoke` 完成前，ArduPilot 只保留路线规划，不进入实现。

---

### C. Webots

**定位：后续机器人 / 传感器 / 地面平台仿真备选。**

适合：

- 非飞行机器人仿真；
- 传感器建模；
- 地面平台、简单机器人场景；
- payload/device simulator placeholder 的后续扩展。

当前不作为飞控主线原因：

- 当前主线目标是 MAVLink / PX4 / takeoff smoke；
- Webots 更适合作为后续非空中机器人或传感器仿真扩展；
- 不应为了 Webots 改动 protocol/policy contract。

---

### D. AirSim

**定位：历史 / 视觉仿真备选，不作为当前主线。**

适合：

- 视觉仿真；
- 历史 AirSim 资产复用；
- 图像/感知类演示的候选环境。

当前避免作为第一优先级原因：

- 当前主线已经围绕 PX4 SITL readiness 与 MAVLink backend seam 展开；
- AirSim 可能引入额外环境、图形、插件、平台兼容复杂度；
- AirSim 不应反向驱动当前控制面或 policy gate 设计。

---

## 4) 与当前架构的关系

所有仿真后端都必须通过既有 adapter / backend seam 接入，不得绕过 runtime 和 policy gate。

目标链路：

```text
control plane
-> policy gate
-> adapter gateway
-> backend adapter
-> simulator / SITL
-> action_result
-> audit/replay
```

架构规则：

- 仿真器不应改变 protocol contract；
- 仿真器不应改变 policy contract；
- 每个仿真后端都应通过 adapter/backend seam 接入；
- 不允许把 Gazebo、ArduPilot、Webots、AirSim 等仿真器细节直接写入控制面消息；
- 仿真器选择不应影响 policy gate 的授权、委托、抢占、链路状态、风险确认等裁决语义；
- simulator/backend 的失败应收敛为 backend/readiness/action result 层的稳定 code/message/detail/evidence/execution_trace。

---

## 5) 当前优先级排序

### P0：当前主线

- PX4 SITL readiness；
- PX4 SITL `backend_connected`；
- 最小 `takeoff smoke`；
- 继续保持 fake adapter 作为默认稳定基线。

### P1：下一层规划

- ArduPilot SITL route planning；
- payload/device simulator placeholder；
- 明确是否需要 ground / rover / boat 等非多旋翼仿真对象。

### P2：后续扩展

- Webots / non-air robotics；
- AirSim historical / vision fallback；
- 感知、视觉、复杂环境演示类仿真。

---

## 6) 当前不该做的事

当前阶段明确不做：

- 不同时接 PX4 + ArduPilot + Webots + AirSim；
- 不做多机复杂仿真；
- 不做 GUI；
- 不做复杂任务规划；
- 不改 protocol contract；
- 不改 policy contract；
- 不让仿真器选择影响 policy gate；
- 不把仿真器 SDK / endpoint / world / model 细节写入控制面消息；
- 不用仿真器路线替代 fake adapter 的稳定测试基线。

---

## 7) 后续决策点

后续只有在满足明确条件时，才考虑新增 ArduPilot / Webots 等路线。

### 7.1 考虑 ArduPilot SITL 的条件

- 硬件清点发现公司平台使用 ArduPilot；
- 需要无人车 / 无人船 / 固定翼等 ArduPilot 更适配的平台；
- PX4 SITL 主线已完成 `backend_connected + takeoff smoke`；
- 需要验证 MAVLink adapter/backend seam 对非 PX4 MAVLink 平台的兼容性。

### 7.2 考虑 Webots 的条件

- payload/device 需要非飞行机器人仿真；
- 需要传感器或地面平台仿真；
- 当前 payload/device adapter skeleton 已形成稳定 runtime/audit/replay 路径；
- Webots 只作为 backend/simulator seam，不改变 control plane。

### 7.3 考虑 AirSim 的条件

- 需要复用历史 AirSim 资产；
- 明确需要视觉/图像仿真；
- PX4 SITL 主线不被打断；
- AirSim 不作为 flight backend 第一优先级，也不驱动 protocol/policy contract 变化。

---

## 8) 后续建议

1. 继续完成 PX4 SITL 手工 readiness：确认 `dependency_missing`、`backend_not_configured`、`backend_probe_failed`、`backend_connected` 四类结果可复现。
2. 在 `backend_connected` 稳定后，进入只包含最小飞行动作的 `takeoff smoke`，仍不扩展多动作、多机或复杂任务。
3. 将 ArduPilot / Webots / AirSim 保持为文档级路线，等硬件清点和 PX4 主线 smoke 完成后再决策。
4. payload/device simulator 只做 placeholder 路线规划，不接真实硬件、不引入危险动作。
