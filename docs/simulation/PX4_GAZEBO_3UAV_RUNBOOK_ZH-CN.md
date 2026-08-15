# PX4 / Gazebo 三机仿真运行手册

## 1. 适用范围

本工作线只负责 PX4 SITL、Gazebo 场景、三机身份绑定、仿真健康证明、独立验收巡检和安全停止。

不负责：

- Agent / LLM 任务规划；
- Policy Gate 正式授权；
- Runtime Mission API；
- 前端或 Cesium 展示；
- 强化学习、动态任务分配或复杂编队控制。

确定性巡检脚本是短期 acceptance validator，不是第二套生产控制面。

## 2. 两种运行模式

### Standalone validation mode

```text
Patrol validator
  -> MAVLink
  -> PX4
  -> Gazebo
```

Runtime 必须停止。验证脚本独占 `14540/14541/14542`，用于证明三机底座自身能够真实飞行。

### Integrated mode

```text
Frontend / Agent
  -> Runtime
  -> Policy Gate
  -> Runtime MAVLink session
  -> PX4
  -> Gazebo
```

此模式下 Simulation 不发送 ARM、TAKEOFF、GOTO、RETURN_HOME 或 LAND，只提供生命周期、场景、identity binding、health 和 simulator evidence。

## 3. 权威配置和固定身份

仿真绑定权威来源：

```text
simulation/px4_gazebo/config/three_uav_sitl.json
```

Runtime 共享配置：

```text
config/vehicles.sitl.json
```

Harness 只读共享配置并校验漂移，不会自动覆盖。发现差异时返回 `shared_config_mismatch` 和 expected/actual JSON。

| node_id | PX4 instance | system_id | component_id | Gazebo model | Runtime/PX4 MAVLink endpoint | runtime dir |
| --- | ---: | ---: | ---: | --- | --- | --- |
| UAV-01 | 0 | 1 | 1 | `x500_0` | `udpin:127.0.0.1:14540` | `.runtime/px4_gazebo/UAV-01` |
| UAV-02 | 1 | 2 | 1 | `x500_1` | `udpin:127.0.0.1:14541` | `.runtime/px4_gazebo/UAV-02` |
| UAV-03 | 2 | 3 | 1 | `x500_2` | `udpin:127.0.0.1:14542` | `.runtime/px4_gazebo/UAV-03` |

三个 endpoint 同时承担遥测接收和受控命令发送，不应只称为 telemetry endpoint。

## 4. 坐标系

- Gazebo world：ENU / Z-up；
- 场景与巡检配置：local NED；
- PX4 `LOCAL_POSITION_NED`：NED，`z_down` 为正向下；
- 高度：`altitude_m = max(0, -z_m)`；
- Runtime / Cesium：消费 NED，并结合唯一 WGS84 origin 转换。

位置转换：

```text
NED x (north) = ENU y (north)
NED y (east)  = ENU x (east)
NED z (down)  = -ENU z (up)
```

禁止把 Gazebo ENU 坐标原样发送给 PX4。

## 5. 环境准备

在 WSL 中执行：

```bash
cd ~/PX4-Autopilot
git rev-parse HEAD
gz sim --versions
test -x build/px4_sitl_default/bin/px4
python3 -c "import pymavlink"
```

如 PX4 binary 不存在：

```bash
cd ~/PX4-Autopilot
make px4_sitl
```

进入项目：

```bash
cd /mnt/d/2026UAVSwarm
```

可通过环境变量指定外部 PX4 checkout：

```bash
export PX4_AUTOPILOT_DIR=/path/to/PX4-Autopilot
```

## 6. 静态配置验证

```bash
python3 simulation/px4_gazebo/harness.py validate-config
python3 scripts/validate_scene.py scenarios/simple_recon_v0_1/scene.json --pretty
gz sdf -k scenarios/simple_recon_v0_1/worlds/simple_recon_v0_1.sdf
```

配置验证包含：

- node、instance、system_id、model、endpoint、runtime dir 唯一；
- endpoint 固定为 `14540/14541/14542`；
- manifest 与 scene spawn 一致；
- `config/vehicles.sitl.json` 只读一致性检查；
- NED 到 Gazebo ENU 的显式转换。

## 7. 一键启动

Headless：

```bash
bash simulation/px4_gazebo/scripts/start_three_uav.sh --headless
```

GUI：

```bash
bash simulation/px4_gazebo/scripts/start_three_uav.sh --gui
```

启动前 Harness 会拒绝：

- 非 Linux / WSL 环境；
- 缺少 PX4 binary、etc 或 world；
- 旧状态文件与当前进程身份不一致；
- 外部 PX4 进程或其他 Gazebo world；
- 需要的 UDP 端口已被占用。

启动成功不是完整健康证明，必须继续运行 health。

## 8. 持续健康检查

```bash
python3 simulation/px4_gazebo/scripts/health_three_uav.py \
  --stability-window 10 \
  --pretty
```

默认至少观察 10 秒连续 heartbeat。命令完成后才可启动 Runtime。

PASS 同时要求：

- 目标 world 存在；
- Gazebo `/world/<world>/clock` 至少两个样本且持续前进；
- `x500_0/x500_1/x500_2` 全部存在；
- 三个 PX4 state entry 均通过 PID/PGID/start-time/executable/cmdline/cwd/run_id 身份校验；
- 三个 endpoint 的 heartbeat 持续新鲜；
- 三个 endpoint 的 `LOCAL_POSITION_NED` 持续新鲜；
- observed system_id 分别为 1、2、3，且全局唯一；
- component_id 均为 1。

机器可读输出的稳定字段：

```json
{
  "simulator": "gazebo",
  "status": "ready",
  "server_running": true,
  "clock_advancing": true,
  "world": "simple_recon_v0_1",
  "models": ["x500_0", "x500_1", "x500_2"],
  "vehicles": [
    {
      "node_id": "UAV-01",
      "system_id": 1,
      "component_id": 1,
      "endpoint": "udpin:127.0.0.1:14540",
      "heartbeat_fresh": true,
      "telemetry_fresh": true,
      "process_identity_valid": true,
      "last_seen": "<UTC timestamp>",
      "reason": "ok",
      "evidence": {}
    }
  ]
}
```

任一节点失败时命令退出码为 1，配置/依赖错误退出码为 2。

最新 health 证据同时写入：

```text
.runtime/px4_gazebo/health/latest.json
```

Runtime 负责人可读取该短期快照接入 `/api/simulation/status`；Runtime 持有 endpoint 后不要重新启动 health probe。

## 9. 旧隔离回归

新巡检完成后仍必须运行旧逐机隔离验证：

```bash
python3 simulation/px4_gazebo/scripts/validate_three_uav.py
```

流程按 UAV-01、UAV-02、UAV-03 逐机执行低高度 ARM/TAKEOFF/LAND，同时证明另外两机保持 disarmed 且接近地面。该命令不替代三机巡检。

## 10. 独立三机巡检

确认 Runtime、QGroundControl、MAVProxy 和其他 receiver 均已停止：

```bash
python3 simulation/px4_gazebo/scripts/patrol_three_uav.py --pretty
```

脚本在 health 前后都检查三个 endpoint。任何一个已被 receiver 占用时拒绝运行并返回：

```text
runtime_session_active:endpoint_in_use
```

固定航线来源：

```text
scenarios/simple_recon_v0_1/missions/three_uav_patrol_v0_1.json
```

| node_id | 通道 | 高度 | NED y | 航点数 |
| --- | --- | ---: | ---: | ---: |
| UAV-01 | west | 8 m | -20 m | 3 |
| UAV-02 | central | 10 m | 0 m | 3 |
| UAV-03 | east | 12 m | 20 m | 3 |

执行顺序：

1. 完整三机 health；
2. UAV-01、02、03 顺序错峰 ARM；
3. UAV-01、02、03 顺序错峰 TAKEOFF；
4. 观察各自 85% 高度阈值；
5. 以 10 Hz 持续发送 `SET_POSITION_TARGET_LOCAL_NED`，观察 OFFBOARD；
6. 按 UAV-01、02、03 顺序进入各自走廊，其他飞机持续悬停；
7. 完成走廊进入后，三条分离航线并发执行，每机至少 3 个巡检航点；
8. 每个航点要求 3D 误差不超过 2 m，并连续保持 5 个新遥测样本；
9. 监测全程三机最小空间距离；
10. UAV-01、02、03 顺序 LAND；
11. 每机确认连续低高度样本和 heartbeat disarmed；
12. 输出 ACK、最大高度、航点、最小间距和失败恢复证据。

由于原有起飞坪水平间距为 8 m，全程验收阈值为 7 m；巡检走廊间距为 20 m。配置加载时会静态检查顺序走廊进入阶段的全路径间距，真实飞行时仍由遥测监测最终判定。后续扩大起飞坪后可提高全程阈值。

## 11. 四模块集成运行

推荐顺序：

```text
1. 启动 PX4/Gazebo Harness
2. 独立运行 health，等待命令退出
3. 启动 Runtime，使 Runtime 独占三个 MAVLink endpoint
4. 启动主前端和 Cesium 前端
5. 所有动作经 Runtime -> Policy Gate -> MAVLink session
6. 先停止前端，再停止 Runtime
7. 最后停止 Harness
```

Integrated mode 不运行 `validate_three_uav.py` 或 `patrol_three_uav.py`，否则会争抢 endpoint。

健康 JSON 后续可由 Runtime 负责人接入 `/api/simulation/status`；Simulation 不直接修改 Runtime route。

## 12. 安全停止和残留检查

```bash
bash simulation/px4_gazebo/scripts/stop_three_uav.sh
```

状态文件：

```text
.runtime/px4_gazebo/harness_state.json
```

state v1.2 记录：

- 唯一 `run_id`；
- PID、PGID；
- `/proc/<pid>/stat` start time；
- executable、cmdline、cwd；
- world 名称；
- 本次运行需要释放的 UDP 端口。

停止流程：

1. 重新读取 `/proc` 并验证身份；
2. 身份匹配才发送 SIGTERM；
3. 超时后再次验证身份，仍匹配才发送 SIGKILL；
4. 等待 PX4 PID 退出；
5. 验证目标 Gazebo world 消失；
6. 验证相关 UDP 端口可重新绑定；
7. 全部通过后删除 state 和 PID 文件。

身份不匹配返回 `stale_state` 或 `process_identity_mismatch`，不发送信号。残留未清理返回 `cleanup_incomplete` 并保留 state 供排查。

禁止使用：

```text
pkill -f px4
pkill -f gz
killall
```

## 13. 验收报告

所有真实验证 JSON 写入：

```text
.runtime/px4_gazebo/validation/
```

主要文件：

```text
three_uav_validation_<timestamp>.json
three_uav_patrol_<timestamp>.json
```

目录属于运行产物，不提交 Git。失败报告必须保留失败节点、阶段、原因和 recovery landing 结果。

## 14. 常见故障

### 端口冲突

症状：`endpoint_in_use`、`runtime_session_active` 或 preflight UDP port 错误。

处理：停止 Runtime、QGroundControl、MAVProxy 和旧验证脚本，再确认：

```bash
ss -lunp | grep -E '14540|14541|14542'
```

### UAV-02 单节点离线

依次检查：

```bash
cat .runtime/px4_gazebo/UAV-02/stdout.log
cat .runtime/px4_gazebo/UAV-02/stderr.log
cat .runtime/px4_gazebo/harness_state.json
ss -lunp | grep 14541
```

确认 instance=1、system_id=2、model=`x500_1`、endpoint=`14541`，不要复制 UAV-01 数据冒充 UAV-02。

### Gazebo model 不存在

```bash
gz model --list
gz topic -l | grep simple_recon_v0_1
```

检查 `PX4_GZ_MODEL_NAME`、instance 和对应 PX4 stderr。model 不齐时 health 必须失败。

### heartbeat stale

确认 endpoint 没有被其他 receiver 占用，并检查 PX4 MAVLink 输出端口。连续 10 秒证据不足时不要缩短判据伪造 PASS。

### telemetry stale

检查 `LOCAL_POSITION_NED` 是否持续输出、仿真时钟是否推进、PX4 estimator 是否正常。单次旧样本不算 ready。

### stop 返回 identity mismatch

不要手工改 PID 后重试。保存 state 和 `/proc/<pid>` 证据，确认 PID 是否被复用。只有人工确认进程归属后再处理残留。

### stop 返回 cleanup_incomplete

进程可能已退出，但 world 或 UDP 端口仍残留。先停止 Runtime/receiver，再检查：

```bash
gz topic -l | grep simple_recon_v0_1
ss -lunp | grep -E '14540|14541|14542|14580|14581|14582'
```

## 15. 测试

普通单元测试不连接本机 PX4：

```bash
python -m pytest \
  tests/unit/test_three_uav_harness.py \
  tests/unit/test_three_uav_health.py \
  tests/unit/test_three_uav_patrol.py \
  tests/unit/test_three_uav_validation_cleanup.py \
  -q
```

真实巡检测试必须显式 opt-in：

```bash
UAV_SIM_RUN_REAL_PATROL=1 \
python -m pytest tests/integration/test_three_uav_patrol_real.py \
  -m requires_px4_multi -q -s
```

未设置变量时应 skip，不得把 skip 写成真实 PASS。
