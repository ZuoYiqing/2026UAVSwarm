# 四模块端到端验收清单

本文只验证测试隔离与系统集成链路，不变更业务架构，也不调整正在统一的端口配置。验收边界为：

1. Gazebo/PX4 三机、`VehicleRegistry` 与 Runtime 遥测；
2. HTTP `snapshot` / `vehicle-snapshot` 与动作路由；
3. 主前端三机列表、动作身份和 Cesium 位置更新；
4. Audit/Replay 证据闭环。

## 一键自动验收

在仓库根目录执行：

```powershell
.\scripts\run_four_module_acceptance.ps1
```

默认运行确定性的 Python 集成测试、真实 PX4 可选测试、主前端 Node 测试、前端语法检查和 Cesium Node 测试。没有真实三机环境时，PX4 用例必须显示：

```text
BLOCKED_WAITING_FOR_PX4_MULTI_ENDPOINTS
```

运行完整 Python 测试套件：

```powershell
.\scripts\run_four_module_acceptance.ps1 -FullPytest
```

若系统临时目录不可写，可显式指定仓库外的 pytest 临时目录：

```powershell
.\scripts\run_four_module_acceptance.ps1 `
  -FullPytest `
  -PytestBaseTemp "D:\writable-temp\uavswarm-pytest"
```

脚本在开始时显示 `git status`，并对 `audit/runtime.audit.jsonl` 做前后 SHA-256 校验。测试审计输出由 pytest fixture 重定向到各用例的 `tmp_path`。

## 真实 Gazebo/PX4 三机操作清单

1. 使用当前已统一的仿真清单启动 Gazebo/PX4 三机；不要为测试另改 endpoint 或端口 JSON。
2. 确认 UAV-01、UAV-02、UAV-03 初始均已落地且 disarmed。缺少高度或 armed 遥测不算“已落地”。
3. 将真实环境清单路径传给 pytest：

   ```powershell
   $env:UAV_RUNTIME_PX4_MULTI_CONFIG = (Resolve-Path ".\simulation\px4_gazebo\config\three_uav_sitl.json").Path
   python -m pytest tests\integration\test_px4_multi_vehicle_runtime.py -ra
   ```

4. 检查发现结果严格为三机，`node_id` 分别为 UAV-01/02/03，`system_id` 唯一且与配置一致。
5. 测试会依次对 UAV-01、UAV-02、UAV-03 执行 TAKEOFF 与 LAND；每次确认未选中的两机保持低高度且 disarmed。
6. TAKEOFF 后确认 `/api/telemetry/latest` 高度上升，`/api/vehicle-snapshot` 的 NED `z` 变化，并在 Cesium 中转换为正向 `upM`。
7. LAND 成功只表示命令完成；必须继续等待高度不大于 0.3 m 且 `armed is false`。超时会明确报告 `grounded_disarmed_timeout`。
8. 任一断言失败时，`finally` 会重新读取真实状态；只要未确认 grounded/disarmed，就先 best-effort LAND，再等待落地或明确超时，最后才停止 Registry。
9. 单机遥测中断后，确认另外两机仍在线，但 `all_enabled_px4_connected` 为 `false`，主前端不得显示全局 ready。
10. 在 `/api/replay` 或临时审计 JSONL 中核对动作结果事件含 `node_id`、`system_id`、`action_id` 和 `result`。

## 自动覆盖矩阵

| 验收项 | 自动测试 |
|---|---|
| 三机发现与 identity | `test_registry_http_actions_telemetry_and_audit_replay_chain`、真实 PX4 snapshot 测试 |
| UAV-01/02/03 动作不串机 | Python 三节点动作循环、真实 PX4 三参数用例、主前端 request 测试 |
| 单机离线不误报全局 ready | Runtime `all_enabled_px4_connected` 与主前端 `isFleetReady` 测试 |
| TAKEOFF 遥测/三维高度变化 | Python HTTP snapshot 与 Cesium NED→ENU 高度测试 |
| LAND 后 grounded/disarmed | Python确定性链路与真实 PX4 清理测试 |
| Audit/Replay 必要字段 | Python action result/replay 断言 |
| pytest 审计隔离 | autouse `tmp_path` fixture、session 级受管文件不变断言、脚本 SHA-256 校验 |

## 验收结果判定

- `pass`：确定性测试全部通过；真实环境存在时真实 PX4 用例也全部通过。
- `skip`：仅允许真实 PX4 环境未提供，并带明确 `BLOCKED_WAITING_FOR_PX4_MULTI_ENDPOINTS` 原因。
- `fail`：任何断言失败、Node 测试失败、审计文件哈希变化、LAND 后未在时限内确认 grounded/disarmed，均视为失败。
