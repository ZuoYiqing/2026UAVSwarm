# PX4 SITL Setup and Readiness Runbook

## 1) 本阶段目标（明确边界）

本阶段仅验证 **PX4 SITL backend readiness**，不执行飞控动作：

- 只验证 `connect_probe` 能否给出明确状态；
- 不实现/不发送 `takeoff`、`arm`、`set_mode`、`command_long`；
- 不修改 protocol/policy contract；
- 不做多机、ROS2、GUI。

目标链路：

`adapter=mavlink` + `backend=px4_sitl` + `backend_mode=sitl` + `transport_endpoint` 正确配置

并可得到以下 probe 结果之一：
- `dependency_missing`
- `backend_not_configured`
- `backend_probe_failed`
- `backend_connected`

---

## 2) 依赖安装

`pymavlink` 为 optional dependency。

推荐安装（开发环境）：

```bash
pip install -e .[sitl]
```

说明：
- 未安装 `pymavlink` 时，`check-backend` 应返回 `dependency_missing`；
- 默认 pytest 不依赖真实 PX4/SITL 网络。

---

## 3) PX4 SITL 启动方式（WSL 本地已验证）

本轮已在 WSL Ubuntu 22.04.4 + PX4-Autopilot + Gazebo Harmonic 环境完成 `backend_connected` 验证。

正确启动命令：

```bash
HEADLESS=1 make px4_sitl gz_x500
```

验证时 PX4 已进入 `pxh>`，并观察到 Onboard MAVLink 端口打印：

```text
udp port 14580 remote port 14540
```

语义说明：
- PX4 本地 Onboard MAVLink 端口是 `14580`；
- PX4 会向 remote port `14540` 发送 MAVLink；
- 外部 `pymavlink` / `uav_runtime` 应监听 `14540`；
- 本轮验证成功 endpoint 是 `udpin:127.0.0.1:14540` 和 `udpin:0.0.0.0:14540`。

建议记录：
- SITL 启动命令；
- 实际监听 endpoint；
- 启动日志关键行（心跳/端口信息）。

---

## 4) endpoint 配置示例

示例配置（命令参数）：
- `--backend px4_sitl`
- `--backend-mode sitl`
- `--backend-enabled`
- `--transport-endpoint udpin:127.0.0.1:14540`
- `--connect-timeout-ms 5000`

---

## 5) 手工 readiness 命令示例

### 5.1 依赖缺失场景
```bash
python -m uav_runtime.console.cli check-backend --backend px4_sitl --backend-mode sitl --backend-enabled --transport-endpoint udpin:127.0.0.1:14540 --pretty
```
预期（示意）：
- `connect_probe.code = dependency_missing`
- `readiness = not_ready`

### 5.2 endpoint 未配置场景
```bash
python -m uav_runtime.console.cli check-backend --backend px4_sitl --backend-mode sitl --backend-enabled --pretty
```
预期（示意）：
- `connect_probe.code = backend_not_configured`
- `connect_probe.reason = transport_endpoint_missing`
- `readiness = not_ready`

### 5.3 endpoint 已配置但探测失败
```bash
python -m uav_runtime.console.cli check-backend --backend px4_sitl --backend-mode sitl --backend-enabled --transport-endpoint udpin:127.0.0.1:14540 --connect-timeout-ms 1500 --pretty
```
预期（示意）：
- `connect_probe.code = backend_probe_failed`
- `connect_probe.reason in {heartbeat_timeout, connection_failed, probe_exception}`
- `readiness = not_ready`

### 5.4 endpoint 已配置且探测成功
```bash
python -m uav_runtime.console.cli check-backend \
  --backend px4_sitl \
  --backend-mode sitl \
  --backend-enabled \
  --transport-endpoint udpin:127.0.0.1:14540 \
  --connect-timeout-ms 5000 \
  --pretty
```
预期（示意）：
- `connect_probe.code = backend_connected`
- `readiness = ready`

> 注意：`backend_connected` 仅表示 probe 成功，不表示已经执行任何飞控动作。

---

## 6) 常见问题排查

1. **返回 `dependency_missing`**
   - 检查是否已安装 optional dependency：`pip install -e .[sitl]`。

2. **返回 `backend_not_configured`**
   - 检查 `--transport-endpoint` 是否填写且格式正确。

3. **返回 `backend_probe_failed` + `heartbeat_timeout`**
   - 检查 SITL 是否已启动；
   - 检查 endpoint 是否与 SITL 监听地址一致；
   - 适当增大 `--connect-timeout-ms`。

4. **返回 `backend_probe_failed` + `connection_failed`**
   - 检查主机网络栈、端口占用、防火墙策略；
   - 核对 UDP/TCP 连接串格式。

5. **返回 `backend_probe_failed` + `probe_exception`**
   - 保存 traceback 与命令参数；
   - 先复现最小命令，再定位 pymavlink 版本/环境问题。

### 6.1 `udp://127.0.0.1:14540` 为什么可能失败

本轮 WSL + PX4 SITL + Gazebo Harmonic 验证中，`udp://127.0.0.1:14540` 返回：

```text
backend_probe_failed / connection_failed
```

原因是 PX4 Onboard MAVLink 打印为：

```text
udp port 14580 remote port 14540
```

这表示 PX4 向 remote port `14540` 发出 MAVLink；外部程序应在 `14540` 上监听 heartbeat。
因此本轮验证使用 pymavlink listener endpoint：`udpin:127.0.0.1:14540`。

---

## 7) 执行记录建议

每次手工 readiness 验证建议记录：
- 命令行参数；
- JSON 输出（尤其 `connect_probe` 与 `readiness`）；
- SITL 启动日志摘要；
- 环境信息（Python 版本、pymavlink 版本）。

该记录将作为后续真实动作接入（仍先单动作）前的基线证据。


## 8) backend_connected 手工验证准备（进入 smoke 前置）

`backend_connected` 是进入“真实 takeoff smoke（仍仅 SITL）”前的**前置条件**，但它本身不代表已执行任何飞控动作。

请在验证记录中明确保存以下信息：
- PX4 SITL 启动命令（完整命令行）；
- SITL 实际监听 endpoint（与 `--transport-endpoint` 一致）；
- `check-backend` 原始 JSON 输出。

关键解释：
- `backend_connected` 仅表示 `pymavlink` 已完成最小连接/heartbeat probe；
- 不等于 `arm`/`set_mode`/`takeoff` 成功；
- 本阶段 adapter 侧只做 MAVLink heartbeat/probe，不发送控制命令。

---

## 9) 启动与执行原则（通用）

- PX4 SITL 需独立启动（与 runtime 进程解耦）；
- 推荐先使用单机 endpoint（如 `udpin:127.0.0.1:14540`）；
- 暂不做多机 endpoint 验证；
- 暂不执行 `arm` / `set_mode` / `takeoff`。

---

## 10) Minimal takeoff smoke 收尾记录（pymavlink 临时脚本）

`backend_connected` 后，本轮已使用临时 pymavlink 脚本完成一次 **PX4 SITL minimal takeoff smoke**。

边界说明：
- 这是 SITL-only 临时脚本验证；
- 不是 `uav_runtime submit-action takeoff` 正式闭环；
- 不代表真实无人机可飞；
- 不做多机；
- 不接 QGroundControl；
- 不修改 policy/protocol contract。

验证环境与 endpoint：
- WSL Ubuntu 22.04.4；
- PX4 commit：`171f0f38cffa95f28d5e159f7aaf7599756f9e0e`；
- Gazebo：`8.14.0`；
- runtime commit：`aca6d40`；
- PX4 启动命令：`HEADLESS=1 make px4_sitl gz_x500`；
- endpoint：`udpin:127.0.0.1:14540`。

smoke 流程：
1. wait heartbeat；
2. start GCS heartbeat；
3. request `LOCAL_POSITION_NED` interval；
4. ARM；
5. TAKEOFF 3m；
6. observe `LOCAL_POSITION_NED` altitude rise；
7. LAND。

验收结果：
- ARM ACK `result=0`；
- TAKEOFF ACK `result=0`；
- LAND ACK `result=0`；
- `max_altitude_m=2.13`；
- `threshold_reached=True`；
- `RESULT=PASS`。

已知问题：首次 ARM 在没有持续 GCS heartbeat 时返回 `TEMPORARILY_REJECTED`。加入 GCS heartbeat thread 后 ARM accepted。
因此下一阶段 runtime PX4 action 接入必须维持 companion/GCS heartbeat session，不能只做一次性命令连接。

详细记录见 `docs/px4_sitl_minimal_takeoff_smoke_validation_log.md`。
下一阶段设计见 `docs/px4_runtime_takeoff_action_integration_plan.md`。


## 11) Runtime smoke-takeoff v0.1 command

After PX4 is running with:

```bash
HEADLESS=1 make px4_sitl gz_x500
```

run the SITL-only runtime smoke command:

```bash
python -m uav_runtime.console.cli smoke-takeoff \
  --backend px4_sitl \
  --backend-mode sitl \
  --backend-enabled \
  --transport-endpoint udpin:127.0.0.1:14540 \
  --altitude-m 3 \
  --connect-timeout-ms 5000 \
  --command-timeout-ms 10000 \
  --observe-timeout-ms 25000 \
  --auto-land \
  --pretty
```

This command is still a minimal SITL action closure, not a full mission planner.
It keeps the GCS heartbeat active before ARM and records ACK / altitude / threshold evidence in the JSON action result and audit log.
