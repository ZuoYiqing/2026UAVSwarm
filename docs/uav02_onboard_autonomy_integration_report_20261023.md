# UAV-02 平台侧自治组合验证记录（2026-10-23）

本记录仅覆盖已提交代码的离线、fake 和 loopback 验证。未启动 PX4/Gazebo，未发真实飞行命令；HTTP 202、fake `succeeded` 和单元测试通过均不是飞行验收。

## 固定版本

| 工作线 | 已纳入组合分支的提交 | 交付边界 |
| --- | --- | --- |
| GitHub `main` | `12e301a` | 当前基线；相对 `0e51c01` 的新增改动限于 UGV 运维文档 |
| Runtime | `332b6c4`，Draft PR #97 | UAV-02 常驻任务、唯一会话所有权、授权/Policy、持久事件、地面网关 |
| 仿真 | `db1c8e6`，Draft PR #95 | 单节点拓扑、应用链路故障代理、fake 部署与 `run_id` 对齐 |
| 主控台 | `fc98648`，Draft PR #94 | 平台任务/事件只读补收；显示断链与最后可信状态，不自动重发动作 |
| 算法 | `17017cd`，Draft PR #96 | 本地候选选项、越权拒绝、与 Runtime 一致的输入哈希 |

组合分支为 `codex/uav02-autonomy-integration`、Draft PR #93。以上均以提交祖先关系核对；原 `main` 工作区未用于组合写入。

## 本地复核结果

在该组合工作区执行，测试产物置于忽略的 `.runtime/` 目录：

| 命令/范围 | 结果 | 解释 |
| --- | --- | --- |
| `python -m pytest -q tests/integration/test_uav02_onboard_autonomy.py` | 10 passed | 已提交四线代码上的 fake/loopback 跨边界检查；没有借用负责人未提交源码 |
| Runtime 平台与仿真拓扑/代理/部署、三机 harness/health 定向测试 | 115 passed | 首次与其他测试并行时 1 项 loopback POST 连接中止；单项隔离及整组串行复跑均通过，原因未定，保留为环境/稳定性观察项 |
| `python -m pytest -q` | 989 passed, 6 skipped | 全仓离线回归，92.64 s；包含本线 10 项测试 |
| `npm run check`、`npm test`（`frontend/swarm-console`） | 检查通过，135 passed | 主控台静态检查与单元测试 |
| `python -S -m unittest discover -s platform_candidate_lab/tests -q`（`algorithm_lab`） | 13 passed | 算法候选适配器的离线测试，不含真实模型 |

本线 10 项测试覆盖：同任务幂等/变更冲突、失链前后起飞门控、重启后 `recovery_required` 与人工核对、错误节点/过期授权/超限参数零执行、模型非法输出与超时的有限回退、算法候选契约交叉验证、HTTP 202 后独立后台执行、事件 `store_id`/游标保护，以及经仿真应用代理切链后只续行已授权 `hold_position → land`、重连仅补报不重飞。代理切链单项另连续复跑 3 次通过。

## 未完成的验收门槛

1. **Linux 同侧模型后端未闭环。** 算法负责人已在两套 WSL 跑通候选适配器的 13 项离线测试，权重可读；但现有推理引擎是 Windows PE，没有已核验的 Linux `llama-server` 与依赖清单。Windows 模型服务的 5/5 响应不能代替 WSL 同侧 `18080 → 8872` 的冷/热 2 秒时限测试。真实模型链路记为 pending。
2. **真实 SITL/飞行未测。** 未验证 UAV-02 的唯一 `14541` 接收者、PX4 ACK 后新鲜遥测、真实保持与 LAND、01/03 始终 disarmed、故障注入期间机载链路持续、退出后的进程/端口清理。相关 A3、A7、A8、A11 只能记为离线部分覆盖，不能记为实飞通过。
3. **落地参考与安全停止未测。** LAND 成功须使用未续期的新鲜地面参考、落地与上锁证据。仿真侧旁路证据只能作为评估 oracle，不能当机载模型输入。SITL Agent 停止须核对同一 `run_id`、进程身份、`source=px4_telemetry`、`active_task=null` 与 `safe_to_stop=true`；证据不足不得强停或宣称任务成功。

下一窗口先做只读端口/进程/身份检查，不抢占现有服务；补齐可溯源 Linux 推理制品后，先无飞行验证模型服务及截止时间。只有模型链路、唯一 MAVLink 所有权、有效标定/地面参考和 UAV-01/03 初态证据同时齐备，才可另行授权 UAV-02 限定 `takeoff → hold_position → land` 与地面应用链路故障注入。当前 PR 应保持 Draft，不合并到 `main`。
