# PX4 / Gazebo 三机 Discovery

## 1. 目的

本文记录 2026-07-30 在本机实际 PX4 源码中确认的多实例机制。端口、环境变量和模型命名
均来自当前 checkout，不依赖记忆猜测。

## 2. 本机环境

| 项目 | 实际值 |
| --- | --- |
| WSL 发行版 | Ubuntu / WSL2 |
| PX4 目录 | `~/PX4-Autopilot` |
| PX4 branch | `main` |
| PX4 commit | `171f0f38cffa95f28d5e159f7aaf7599756f9e0e` |
| Gazebo Sim | `8.14.0` / Harmonic |
| PX4 SITL build | `build/px4_sitl_default`，已存在 |
| pymavlink | WSL Python 中已安装 |

PX4 checkout 在 Discovery 时无已跟踪修改。

## 3. 当前 PX4 多实例规则

### 3.1 实例和 system ID

PX4 通过以下形式启动实例：

```bash
./build/px4_sitl_default/bin/px4 -i INSTANCE -d build/px4_sitl_default/etc
```

`ROMFS/px4fmu_common/init.d-posix/rcS` 明确执行：

```text
MAV_SYS_ID = px4_instance + 1
UXRCE_DDS_KEY = px4_instance + 1
```

因此本 Harness 使用实例 `0/1/2`，对应 sysid `1/2/3`。

### 3.2 Gazebo 模型生成

当前版本支持：

- `PX4_SYS_AUTOSTART=4001`
- `PX4_SIM_MODEL=gz_x500`
- `PX4_GZ_MODEL_POSE=x,y,z,roll,pitch,yaw`
- `PX4_GZ_WORLD=<world name>`
- `PX4_GZ_STANDALONE=1`
- `PX4_HOME_LAT/LON/ALT`

`PX4_GZ_MODEL` 已废弃，由 `PX4_SIM_MODEL` 替代。使用 `PX4_SIM_MODEL` 时，
`px4-rc.gzsim` 自动将模型命名为：

```text
<model without gz_>_<px4_instance>
```

所以三架 x500 是 `x500_0`、`x500_1`、`x500_2`。第一实例启动 Gazebo world，
后续实例设置 `PX4_GZ_STANDALONE=1` 并连接同一个 world。

### 3.3 MAVLink 端口

`ROMFS/px4fmu_common/init.d-posix/px4-rc.mavlink` 的当前规则：

```text
offboard local  = 14580 + instance
offboard remote = 14540 + instance
GCS local       = 18570 + instance
payload local   = 14280 + instance
gimbal local    = 13030 + instance
```

实例大于 9 时，offboard remote 固定为 `14549`，因此未来扩展到 10 架时需要重新评估
Runtime 的 endpoint 隔离；不能把当前简单递增规则无限外推。

Runtime/pymavlink 在 v0.1 监听：

```text
udpin:127.0.0.1:14540
udpin:127.0.0.1:14541
udpin:127.0.0.1:14542
```

### 3.4 工作目录和日志

PX4 官方通用多实例脚本会为每个实例创建独立 working directory。本项目保持相同原则，
但将运行文件放到：

```text
.runtime/px4_gazebo/UAV-01/
.runtime/px4_gazebo/UAV-02/
.runtime/px4_gazebo/UAV-03/
```

每个目录独立保存 PX4 参数、dataman、飞行日志、`stdout.log`、`stderr.log` 和 `px4.pid`。

## 4. 官方脚本评估

PX4 当前包含 `Tools/simulation/sitl_multiple_run.sh`，但本项目没有直接调用它，原因是：

1. 脚本启动前执行无边界 `pkill -x px4`，不符合只管理 Harness 自身进程的要求。
2. 脚本没有表达每架 Gazebo spawn pose 和项目 manifest 的接口。
3. 默认示例仍偏向 gazebo-classic/SIH，不直接覆盖本项目的 Gz Harmonic 自定义 world。

本 Harness 没有重写 PX4 内部逻辑，而是按 PX4 官方多机文档直接调用同一个 `px4`
binary、`-i` 参数和官方环境变量。

## 5. 自定义 world 接入

Harness 不修改 `~/PX4-Autopilot`。它将：

- `PX4_GZ_MODELS` 指向 PX4 官方 x500 模型目录；
- `PX4_GZ_WORLDS` 指向本项目 scenario world 目录；
- `GZ_SIM_SERVER_CONFIG_PATH` 指向 PX4 官方 `server.config`；
- 由官方 server config 加载 Physics、UserCommands、Sensors、Imu、NavSat 等系统。

world SDF 不静态创建 x500。三个模型均由各自 PX4 实例通过 `/world/.../create` 生成，
防止重复模型。

## 6. 采用方案

采用“一个 manifest + 一个 Python 进程管理核心 + 两个 shell 入口”的方案：

- manifest 是身份、端口和 spawn 的唯一实现来源；
- launcher 逐个启动并等待对应 Gazebo 模型出现；
- state 文件记录 PID 和 process group；
- stopper 只对记录的 process group 发 TERM，超时后才有限 KILL；
- health checker 同时验证 endpoint、sysid、模型名和进程；
- isolation validator 使用真实 telemetry 判定动作完成。

未采用复制三套脚本或按启动顺序猜身份的方案。
