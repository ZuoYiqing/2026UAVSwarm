# PX4 / Gazebo 三机运行手册

## Runtime transport / safe stop addendum (v0.1.1, 2026-08-11)

Runtime directly consumes `config/three_uav_sitl.json` and creates one shared
MAVLink session/RX owner per vehicle. Do not start a second telemetry listener
on the same `14540/14541/14542` endpoint. Finish the short-lived health command
before starting Runtime.

The stopper no longer trusts PID/PGID alone. Harness state contains `/proc`
start time, executable, cmdline, cwd, node and process group. If any live record
does not match, stop exits with `stale_state` or `process_identity_mismatch`,
preserves state for inspection, and sends no TERM/KILL. Never replace this with
`pkill` or `killall`.

Runtime integration order:

1. validate the manifest;
2. start the harness and run health to completion;
3. start Runtime and confirm three shared sessions are connected;
4. query vehicles, per-node telemetry, and the full snapshot;
5. take off/land UAV-02, observe landing, and verify UAV-01/UAV-03 stay passive;
6. stop Runtime first, then use the identity-checked harness stopper.

## 1. 边界

本 Harness 只管理本地 Gazebo + PX4 SITL 三机仿真。它不修改 Agent Planner、
Policy Gate、前端，不连接实机，不实现编队或任务规划。

## 2. 前置条件

在 WSL 中确认：

```bash
cd ~/PX4-Autopilot
git rev-parse HEAD
gz sim --versions
test -x build/px4_sitl_default/bin/px4
python3 -c "import pymavlink"
```

如果 binary 不存在：

```bash
cd ~/PX4-Autopilot
make px4_sitl
```

本机项目示例路径：

```bash
cd /mnt/d/2026UAVSwarm
```

如果仓库位于 WSL home，请进入实际 checkout 后使用相同的相对命令。

## 3. 配置验证

```bash
python3 simulation/px4_gazebo/harness.py validate-config
python3 scripts/validate_scene.py scenarios/simple_recon_v0_1/scene.json
gz sdf -k scenarios/simple_recon_v0_1/worlds/simple_recon_v0_1.sdf
```

唯一实现绑定来源：

```text
simulation/px4_gazebo/config/three_uav_sitl.json
```

语义地图来源：

```text
scenarios/simple_recon_v0_1/scene.json
```

PX4 目录可通过环境变量覆盖：

```bash
export PX4_AUTOPILOT_DIR=/path/to/PX4-Autopilot
```

## 4. 固定映射

| node_id | PX4 instance | MAV_SYS_ID | Gazebo model | Runtime command/telemetry endpoint | PX4 local | GCS local | spawn NED |
| --- | ---: | ---: | --- | --- | ---: | ---: | --- |
| UAV-01 | 0 | 1 | `x500_0` | `udpin:127.0.0.1:14540` | 14580 | 18570 | `(0, 0, 0)` |
| UAV-02 | 1 | 2 | `x500_1` | `udpin:127.0.0.1:14541` | 14581 | 18571 | `(0, 8, 0)` |
| UAV-03 | 2 | 3 | `x500_2` | `udpin:127.0.0.1:14542` | 14582 | 18572 | `(0, -8, 0)` |

Runtime 必须同时校验 `node_id + endpoint + system_id`，禁止把“收到的第一个 heartbeat”
当成 UAV-01。

## 5. 一键启动

### Headless

```bash
bash simulation/px4_gazebo/scripts/start_three_uav.sh --headless
```

### GUI

```bash
bash simulation/px4_gazebo/scripts/start_three_uav.sh --gui
```

GUI 需要 WSLg、`DISPLAY`/`WAYLAND_DISPLAY` 和可用图形驱动。headless 是自动验证的推荐模式。

启动前 Harness 会检查：

- PX4 checkout、commit、build binary；
- Gazebo 版本；
- manifest、scene 和 world；
- 相关 UDP 端口；
- 已存在的 Harness state；
- 外部 PX4 进程或已运行 Gazebo world。

发现外部进程时只报错，不会自动 `pkill`。

## 6. Health / Readiness

```bash
python3 simulation/px4_gazebo/scripts/health_three_uav.py --pretty
```

PASS 必须同时满足：

- 三个 Harness PID 存活；
- `x500_0/1/2` 三个模型存在；
- 三个 endpoint 均收到 heartbeat；
- observed sysid 分别等于 `1/2/3`；
- observed sysid 全局唯一。

Health 是短连接。运行 Runtime 长连接前先结束 health 命令，避免两个进程争用同一
`udpin` 监听端口。

## 7. 控制隔离验证

```bash
python3 simulation/px4_gazebo/scripts/validate_three_uav.py
```

默认流程：

1. 三机 health 必须先 PASS。
2. 只 ARM/TAKEOFF UAV-01 到 2 m。
3. 遥测确认 UAV-01 达到 70% 高度阈值。
4. 同时检查 UAV-02/UAV-03 未解锁且接近地面。
5. UAV-01 LAND，并用连续低高度样本确认落地。
6. 对 UAV-02、UAV-03 重复。

结果写入：

```text
.runtime/px4_gazebo/validation/
```

`COMMAND_ACK accepted` 只表示接收命令；脚本另外使用 `LOCAL_POSITION_NED` 证明起飞和
降落完成。

## 8. 一键停止

```bash
bash simulation/px4_gazebo/scripts/stop_three_uav.sh
```

stopper 读取 `.runtime/px4_gazebo/harness_state.json`，只停止本 Harness 记录的 process
group。它先发送 TERM、等待退出，必要时才对这些 process group 发送 KILL。

禁止用以下命令代替：

```text
pkill -f python
pkill -f gz
killall
```

### 状态文件与安全停止机制

`.runtime/px4_gazebo/harness_state.json` 是一次 Harness 运行的进程所有权凭据，
不是普通 PID 列表。每次 `start` 都生成新的 `run_id`，状态顶层记录 `run_id`、
`started_at`、manifest、PX4/Gazebo 版本和本次启动的 process entries。每个 entry
包含便于运维查看的 `pid`、`pgid`、`node_id`、`runtime_dir`，以及从真实 Linux
`/proc/<pid>/` 采集的：

```json
{
  "process_identity": {
    "pid": 12345,
    "pgid": 12345,
    "proc_start_time_ticks": 987654321,
    "executable": "/home/user/PX4-Autopilot/build/px4_sitl_default/bin/px4",
    "cmdline": [".../px4", "-i", "0", "-d", ".../etc"],
    "cwd": "/mnt/d/2026UAVSwarm/.runtime/px4_gazebo/UAV-01",
    "run_id": "本次启动的唯一标识"
  }
}
```

PID 和 PGID 都可能在旧进程退出后被 Linux 复用，单独匹配它们不能证明进程属于
本 Harness。`stop` 在发送信号前重新读取 `/proc/<pid>/stat` field 22、`exe`、
`cmdline`、`cwd`、当前 PGID，并检查进程环境中的 Harness `run_id`。`stat` 的
`comm` 允许包含空格和括号，解析器不会对整行直接 `split()`。

停止判定分为四类：

- `match`：全部身份字段匹配，才允许向已记录 PGID 发送信号；
- `process_exited`：PID 已不存在，视为幂等成功，不发送信号；
- `stale_state`：状态缺字段、内部矛盾或 `/proc` 无法可靠读取，拒绝发送信号；
- `process_identity_mismatch`：PID 存在但启动时间、exe、cmdline、cwd、run_id 或
  PGID 任一不符，判定为 PID 复用或非 Harness 进程，拒绝发送信号。

正常流程仍是 `SIGTERM -> 有界等待 -> SIGKILL`。等待期间进程可能退出，PID 也
可能被重新占用，所以 `SIGKILL` 前必须再次完整校验身份；复查不匹配时禁止升级
信号。只有所有记录都已确认退出，才删除各运行目录中的 `px4.pid` 和
`harness_state.json`。身份不匹配时保留状态文件，避免丢失诊断证据。

出现 `stale_state` 或 `process_identity_mismatch` 时，先停止 Runtime，再只读检查：

```bash
cat .runtime/px4_gazebo/harness_state.json
ps -o pid,pgid,lstart,args -p <PID>
readlink /proc/<PID>/exe
readlink /proc/<PID>/cwd
tr '\0' ' ' < /proc/<PID>/cmdline
```

确认 PID 已经退出时可再次执行 Harness `stop`，它会幂等清理合法过期状态。若 PID
仍存在但身份不匹配，不要删除状态后重试，也不要用 `pkill`、`killall` 或模糊
`pgrep | kill` 绕过校验；应先确认该进程的真实所有者，再由运维人员处理并归档
诊断状态。无边界进程名匹配可能停止 Runtime、测试进程或同一 WSL 中的其他任务。

## 9. 日志

```text
.runtime/px4_gazebo/UAV-01/stdout.log
.runtime/px4_gazebo/UAV-01/stderr.log
.runtime/px4_gazebo/UAV-02/stdout.log
.runtime/px4_gazebo/UAV-02/stderr.log
.runtime/px4_gazebo/UAV-03/stdout.log
.runtime/px4_gazebo/UAV-03/stderr.log
```

运行目录和日志被 `.gitignore` 排除，不应提交。

## 10. 坐标合同

Scene 和 PX4 使用 local NED：

```text
x = North
y = East
z = Down
yaw = 从 North 顺时针
```

Gazebo 使用 ENU/Z-up：

```text
Gazebo X = NED Y
Gazebo Y = NED X
Gazebo Z = -NED Z
Gazebo yaw = pi/2 - NED yaw
```

yaw 结果规范化到 `[-pi, pi)`。唯一 WGS84 原点来自 `scene.json.origin`：

```text
47.3979709, 8.5461639, 0m
```

未来数据链：

```text
Gazebo/PX4 -> Runtime telemetry -> Vehicle Snapshot -> Cesium
```

浏览器不是仿真状态源。

## 11. 常见故障

### UDP port occupied

先停止 Runtime、旧 health checker 或旧 PX4，再重试。不要直接杀全部 Python/Gazebo。

### Other PX4/Gazebo process is running

Harness 为避免附着错误 world 会拒绝启动。请在原终端优雅停止原单机仿真。

### Timed out waiting for model

首次冷启动可能需要较长时间。检查对应 UAV 的 `stdout.log`/`stderr.log`，确认是否到达：

```text
Gazebo world is ready
Spawning Gazebo model
```

当前首机等待 75 秒，后续实例等待 45 秒；失败会清理已启动进程。

### GUI 不出现

先用 `--headless` 验证底座，再检查 WSLg、GPU/Mesa、`DISPLAY` 和 `WAYLAND_DISPLAY`。

### Heartbeat sysid 不匹配

立即停止验证。检查 manifest instance、endpoint，以及是否有其他进程向该 UDP 端口发送。

## 12. 扩展到 5/10 架

launcher、stopper、health 和 validator 都遍历 `vehicles[]`，没有三套硬编码分支。扩展时：

1. 增加 scene vehicle 和安全 spawn。
2. 增加 manifest binding。
3. 分配唯一 instance、sysid、model 和 endpoint。
4. 重新运行配置、health 和隔离测试。

注意当前 PX4 在 instance 大于 9 时会复用 offboard remote `14549`。扩展到第 11 个实例
前必须重新设计 Runtime 监听隔离，不能继续简单端口递增。
