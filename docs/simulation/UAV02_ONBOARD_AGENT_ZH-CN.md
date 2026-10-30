# UAV-02 虚拟伴随机：仿真拓扑与地面链路故障注入

本线只负责 PX4/Gazebo 三机底座、UAV-02 平台进程的**仿真部署边界**、地面到
平台代理的应用链路故障注入及旁路物理观测。任务授权、执行器、Policy Gate、HTTP
任务接口和唯一 MAVLink session 由 Runtime 实现。当前 PR 保持 Draft；本文件的
启动命令在 Runtime 平台模块合入同一验收 checkout 之前不能视为已验证。

## 固定拓扑

`simulation/px4_gazebo/config/uav02_onboard_topology_v0_1.json` 从相机版
`three_uav_mono_cam_sitl.json` 派生绑定，不重写共享 `config/vehicles.sitl.json`。

| 节点 | 单一接收者 | PX4 sysid/compid | 既有 endpoint |
| --- | --- | --- | --- |
| UAV-01 | 地面 Runtime | 1/1 | `udpin:127.0.0.1:14540` |
| UAV-02 | 平台 Agent | 2/1 | `udpin:127.0.0.1:14541` |
| UAV-03 | 地面 Runtime | 3/1 | `udpin:127.0.0.1:14542` |

地面 Runtime 必须以 `--exclude-node UAV-02` 启动，不能再绑定 14541。平台代理
`127.0.0.1:8766` 只接应用请求；透明代理 `127.0.0.1:8767` 只转发地面 Runtime
到 8766 的 HTTP/SSE 字节流。地面 Runtime 的 `--platform-url` 应指向 8767。
故障代理不绑定或转发 14540–14542，也不触碰 Gazebo 相机话题。SITL 进程独占
14541 的实际验收必须由集成独占窗口验证；端口映射表本身不是验收通过。

## 本线已有命令与限制

在同一 Linux/WSL checkout，先按原 runbook 启动**相机版** PX4/Gazebo，并确认
managed `harness_state.json` 的 run_id、三模型和进程身份。WSL 本机相机版曾因
GPU 适配器选择出现 RTF 0.175；启动进程需设置
`MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA`，且现场 health 仍必须达标。

Runtime 平台模块可用、密钥文件已由 Runtime 准备后，可先用**不连接 PX4 的 fake
模式**检查部署与应用断链；以下命令不会发送飞行命令：
密钥文件须含至少 32 个无空白字符的本地 token；编排器会把当前 harness `run_id`
传给 Agent 的 `--run-id`，供状态交叉核对。

```bash
python3 simulation/px4_gazebo/onboard_deployment.py start-fake \
  --token-file .runtime/px4_gazebo/platform.token
python3 simulation/px4_gazebo/onboard_deployment.py status
python3 simulation/px4_gazebo/onboard_deployment.py link --mode down
python3 simulation/px4_gazebo/onboard_deployment.py link --mode delay --delay-ms 250
python3 simulation/px4_gazebo/onboard_deployment.py link --mode up
python3 simulation/px4_gazebo/onboard_deployment.py stop-fake
```

`status=process_ready` 只证明当前 run_id 的进程身份和应用端口；它不验证 Agent
认证 API、心跳、PX4 接收者或系统任务就绪，输出 `system_readiness=unverified`。
fake 模式不绑定 14541，端口独占性留给集成窗口中的 SITL 检查。

代理的 `down` 会拒绝新连接并关闭已有连接，包括 SSE；`delay` 双向延迟应用流。
代理原样转发 Bearer token，不解码任务或事件。状态文件与进程日志在 ignored
`.runtime/px4_gazebo/` 下，不入 Git。控制文件缺失、损坏或 run_id 不符时链路
默认为 `down`。进程状态校验 PID、PGID、启动时间、可执行文件、命令行、cwd 和
run_id；fake 停止复用 harness 的 SIGTERM→超时身份复核→SIGKILL 流程，重复停止安全。
`start-fake` 只传不含 world/目标真值的只读 `config/vehicles.sitl.json` 给 Agent，
并对它与相机版 manifest 的 sysid/endpoint 做一致性检查。

编排器现提供 `start-sitl` / `stop-sitl` 的受管入口；这只是进程生命周期，
**尚未经过真实三机 SITL 启停验收**。必须先在同一集成 checkout 启动相机版
harness，并核对当前 run_id、三机进程身份、资源余量和 14541 唯一接收者。
`start-sitl` 复用 manifest/Runtime 配置映射及受管进程身份检查，向平台 Agent
传 `--execution-mode sitl --run-id <当前 harness run_id>`，不发飞行命令。

```bash
python3 simulation/px4_gazebo/onboard_deployment.py start-sitl \
  --token-file .runtime/px4_gazebo/platform.token
python3 simulation/px4_gazebo/onboard_deployment.py status
# 飞行与最终安全观测由集成窗口执行；只在落地、上锁且无活动任务后：
python3 simulation/px4_gazebo/onboard_deployment.py stop-sitl
```

空的 active_task 不足以证明飞机在地面且已上锁。`stop-sitl` 先把受管
ground→Agent 应用代理置为 `down`，等待地面租约超过 3 秒失联，再绕过代理
直连本机 8766 的 bearer 认证只读 status。它要求同一 run_id、SITL 模式、
`ground_link.state=lost`、`active_task=null`、`safe_to_stop=true`，以及来源为
`px4_telemetry`、位置采样不超过 1.5 秒、landed_fresh、armed=false、
landed_state=1 的观测。任何条件不满足都保留进程并拒绝信号；成功后仍由
harness 复核 PID/PGID/starttime/executable/cmdline/cwd/run_id，再执行有序
SIGTERM→超时 SIGKILL。重复停止安全。启动中途出错的 SITL 进程不会自动清理，
保留状态供人工核验，不能借 fake 停止路径绕过。受管代理之外持 token 的直连
调用者不在此编排窗口支持范围，集成方须保证没有此类并发发令者。
地面 Runtime 同时使用 `--exclude-node UAV-02`、
`--platform-url http://127.0.0.1:8767` 与相同的 `--run-id`。
Runtime 的 `GET /api/platform/status` 提供上述停机证据；fake 模式的
`safe_to_stop` 不能证明真实飞机安全。集成方仍需旁路核对 Gazebo 实际落地，
并记录关停后的进程、world 与端口状态。新受管流程尚未实飞验收。

## 传感器与评估真值

运行输入允许 UAV-02 独立图像、`camera_info`、相机内外参及 PX4 自身遥测；图像
话题为 `/world/simple_recon_v0_1/model/x500_mono_cam_1/link/camera_link/sensor/camera/image`。
场景地图只能作为事先审定的版本化静态先验。Gazebo world pose、预置目标/碰撞
真值和 Gazebo 位姿参与的 `scene_ned` 标定只能供旁路评估与控制台展示，不能当作
机载模型的观测或自主定位。当前 Agent 与仿真同机、同 checkout，以上是**数据流
契约**，尚无 OS 文件系统隔离；真实数据防泄漏需集成侧另测。已有 `goto` 收敛问题
未关闭，不得用断链后的航点超时宣称自主任务通过。

集成方观测 UAV-01/03 时使用其**既有唯一** Runtime 会话的 armed、landed 和
位置遥测，仿真可旁路采样 Gazebo pose/PX4 uORB 验证物理未动；不得为观察再建
14540/14542 MAVLink receiver。故障注入夹具
`docs/simulation/fixtures/uav02_ground_link_fault_v0_1.json` 是预期判据，不是实飞
PASS。正式报告需记录版本、run_id、两侧代理进程身份、三个节点状态和断链期间的
HTTP/SSE、PX4、相机时间戳及安全收束结果。
