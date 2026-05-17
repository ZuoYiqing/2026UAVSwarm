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

## 3) PX4 SITL 启动方式（占位）

> 本文不绑定具体 PX4 仓库版本或仿真器细节，仅给出 readiness 流程占位。

请按你们内部已验证的 PX4 SITL 启动流程先启动仿真实例，并确认监听 endpoint（示例常见为 `udp://127.0.0.1:14540`）。

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
- `--transport-endpoint udp://127.0.0.1:14540`
- `--connect-timeout-ms 3000`

---

## 5) 手工 readiness 命令示例

### 5.1 依赖缺失场景
```bash
python -m uav_runtime.console.cli check-backend --backend px4_sitl --backend-mode sitl --backend-enabled --transport-endpoint udp://127.0.0.1:14540 --pretty
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
python -m uav_runtime.console.cli check-backend --backend px4_sitl --backend-mode sitl --backend-enabled --transport-endpoint udp://127.0.0.1:14540 --connect-timeout-ms 1500 --pretty
```
预期（示意）：
- `connect_probe.code = backend_probe_failed`
- `connect_probe.reason in {heartbeat_timeout, connection_failed, probe_exception}`
- `readiness = not_ready`

### 5.4 endpoint 已配置且探测成功
```bash
python -m uav_runtime.console.cli check-backend --backend px4_sitl --backend-mode sitl --backend-enabled --transport-endpoint udp://127.0.0.1:14540 --connect-timeout-ms 3000 --pretty
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

---

## 7) 执行记录建议

每次手工 readiness 验证建议记录：
- 命令行参数；
- JSON 输出（尤其 `connect_probe` 与 `readiness`）；
- SITL 启动日志摘要；
- 环境信息（Python 版本、pymavlink 版本）。

该记录将作为后续真实动作接入（仍先单动作）前的基线证据。
