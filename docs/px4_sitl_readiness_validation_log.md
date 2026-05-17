# PX4 SITL Readiness Validation Log Template

## 0. 文档用途与边界

本模板用于记录 **PX4 SITL readiness** 手工验证过程与结果，面向以下状态语义：
- `dependency_missing`
- `backend_not_configured`
- `backend_probe_failed`
- `backend_connected`

### 当前阶段边界（冻结）
- 本文档只记录 readiness，不记录真实飞控动作；
- 不执行 `takeoff` / `arm` / `set_mode` / `command_long`；
- 不作为飞行安全验证报告；
- 不替代后续动作级 smoke 验证文档。

---

## 1. 验证环境信息（每轮必填）

- 验证日期：
- 操作系统：
- Python 版本与环境名：
- 当前 Git commit：
- `pymavlink` 是否安装（是/否，版本）：
- PX4 SITL 是否启动（是/否，启动方式简述）：
- `transport_endpoint` 配置值：
- `connect_timeout_ms`：
- 验证人：

---

## 2. Readiness 场景记录

> 说明：每一类场景至少保留一次完整记录；如多次验证可复制小节追加。

### A) dependency_missing

- 执行命令：
  ```bash
  python -m uav_runtime.console.cli check-backend --backend px4_sitl --backend-mode sitl --backend-enabled --transport-endpoint udp://127.0.0.1:14540 --pretty
  ```
- 预期 `connect_probe.code`：`dependency_missing`
- 实际 `connect_probe.code`：
- 实际 `readiness`：
- 关键输出粘贴/截图位置：
- 结论（通过/不通过）：
- 问题备注：

---

### B) backend_not_configured

- 执行命令：
  ```bash
  python -m uav_runtime.console.cli check-backend --backend px4_sitl --backend-mode sitl --backend-enabled --pretty
  ```
- 预期 `connect_probe.code`：`backend_not_configured`
- 预期 `connect_probe.reason`：`transport_endpoint_missing`
- 实际 `connect_probe.code`：
- 实际 `connect_probe.reason`：
- 实际 `readiness`：
- 关键输出粘贴/截图位置：
- 结论（通过/不通过）：
- 问题备注：

---

### C) backend_probe_failed

- 执行命令：
  ```bash
  python -m uav_runtime.console.cli check-backend --backend px4_sitl --backend-mode sitl --backend-enabled --transport-endpoint udp://127.0.0.1:14540 --connect-timeout-ms 1500 --pretty
  ```
- 预期 `connect_probe.code`：`backend_probe_failed`
- 预期 `connect_probe.reason`（其一）：`heartbeat_timeout` / `connection_failed` / `probe_exception`
- 实际 `connect_probe.code`：
- 实际 `connect_probe.reason`：
- 实际 `readiness`：
- 关键输出粘贴/截图位置：
- 结论（通过/不通过）：
- 问题备注：

---

### D) backend_connected

- 执行命令：
  ```bash
  python -m uav_runtime.console.cli check-backend --backend px4_sitl --backend-mode sitl --backend-enabled --transport-endpoint udp://127.0.0.1:14540 --connect-timeout-ms 3000 --pretty
  ```
- 预期 `connect_probe.code`：`backend_connected`
- 预期 `readiness`：`ready`
- 实际 `connect_probe.code`：
- 实际 `readiness`：
- 关键输出粘贴/截图位置：
- 结论（通过/不通过）：
- 问题备注：

---

## 3. 汇总结论

- 本轮 readiness 总体结论（通过/不通过/部分通过）：
- 失败场景清单：
- 是否阻塞下一阶段：
- 建议修复项与责任人：
- 目标完成日期：

---

## 4. 进入“真实 takeoff smoke（仅 SITL）”准入条件

满足以下条件后，才可进入下一阶段（仍仅限 SITL，不上真机）：

1. `pymavlink` 已安装且版本可用；
2. `transport_endpoint` 配置正确；
3. `check-backend` 返回 `backend_connected`；
4. `action_result` 结构在现有 contract 下保持稳定；
5. `audit/replay` 链路可追踪、可复盘；
6. 明确本阶段仍仅在 SITL 中执行，不进入真机飞行验证。

---

## 5. 附件索引

- 日志文件路径：
- 控制台输出文件：
- 截图/录屏链接：
- 关联 issue/任务单：
