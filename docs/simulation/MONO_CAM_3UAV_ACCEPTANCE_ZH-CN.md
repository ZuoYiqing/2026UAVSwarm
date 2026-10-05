# 三机单目相机阶段验收记录（2026-10-05，飞行待回归）

本记录对应候选配置 `simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json`。
它保留 `simple_recon_v0_1` 世界和三机 NED 出生位置，仅把 PX4 airframe
切为 `4010`、模型切为 `gz_x500_mono_cam`。原默认三机配置仍用于无相机回归。

## 本轮实测

- WSL PX4 checkout：`171f0f38cffa95f28d5e159f7aaf7599756f9e0e`；Gazebo `8.14.0`。
- 仿真分支起测 HEAD：`907e174d64ad79344ae4dede670fbbe8b704207c`。
- harness run_id：`d0dbde92c9de48e3bdb947f4c8c6ad08`。
- `x500_mono_cam_0/1/2` 全部启动，依次对应 UAV-01/02/03、PX4 instance
  0/1/2、sysid 1/2/3、endpoint 14540/14541/14542。
- 三个模型各有独立的 `/world/simple_recon_v0_1/model/<model>/link/camera_link/sensor/camera/image`
  和同路径 `camera_info`。15 秒墙钟时间内每路收到 48 张完整 RGB8
  1280×960 图像（每帧 3,686,400 bytes），仿真时间戳严格递增，约 30.3 Hz。
  三路首帧 SHA-256 各不相同；本场景中三台相机视野内容可区分。
- `camera_info` 内参一致：`fx=539.93633, fy=539.93637, cx=640, cy=480`。
- 10 秒墙钟 clock 采样的 real-time factor 为 **0.113**，低于 health 的
  **0.20** 门槛。health 返回 `not_ready` / `gazebo_clock_slow`。
- health 曾额外报告 `gazebo_models_missing`：其模型采样窗口原为 50 ms，
  在低实时因子下漏掉 pose 更新。本分支把窗口改为 2 秒并与 MAVLink/clock
  并行采样；后续真实三机复测已观察到全部模型和新鲜遥测。
- harness stop 按进程身份校验后完成，`cleanup.clean=true`、world 已停止，
  14540/14541/14542 和相关端口均已释放。

**结论：三路成像与话题隔离在本次场景中得到实测支持；三机相机配置尚未通过
完整验收。** 低 RTF 下未执行 ARM/TAKEOFF/GOTO/HOLD/LAND，也未进行正式
Runtime integrated 验收。执行端应保持禁用或返回 `camera_not_validated`。

图像哈希和采样时间摘要见
[`fixtures/mono-cam-three-uav-20261005.json`](fixtures/mono-cam-three-uav-20261005.json)。
完整临时采样留在本机 ignored `.runtime/px4_gazebo/camera_acceptance.json`，
不会进入 Git。

## GPU 适配器对照（同日补充）

用户提示 WSL 可能选错 GPU 后，使用完全相同的 manifest/world/PX4 checkout 做
两次独立 harness run。每次都检查受管理 Gazebo PID、`/proc/<pid>/maps`、
`nvidia-smi`、Gazebo clock；两次之间按身份安全停止并确认 world 退出。

| 启动环境 | run_id | 10 秒 RTF | RTX 4050 利用率 | 结果 |
| --- | --- | ---: | --- | --- |
| 未设置适配器变量 | `2682801e6d5e455aa27f293be5e99aff` | 0.175 | 5–11% | 低于 0.20 |
| `MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA` | `ddeec4d154e14d6aaa3c303b7cd2c919` | 0.839 | 13–46% | 高于 0.20 |

显式 NVIDIA 组在**同时订阅三路图像**的 12 秒窗口中 RTF 仍为 **0.809**，
三路分别采到 370/370/369 张完整 RGB 图像，仿真帧率约 30.3 Hz。
修复 health 的串行 pose 采样导致的遥测过期后，standalone health 实测
`ready`、三个 model 和三个节点均 `ok`，其 10 秒 clock RTF 为 **0.888**。
该轮 stop 返回 `cleanup.clean=true`、world 停止、14540–14542 端口释放。

两组 Gazebo maps 均加载 Mesa/D3D12、`swrast_dri.so` 和
`libnvidia-encode.so.1`。**仅凭这些库名无法判定实际 D3D12 适配器**；
`nvidia-smi` 中默认组也有少量 RTX 活动，不能声称它完全没参与。
但只改进程级适配器变量，RTF 从 0.175 升至 0.839，且三路图像订阅时保持
0.809，说明适配器选择是本机低 RTF 的主要因素。未修改 Windows 注册表，
也未降低相机分辨率、帧率或放宽 RTF 门槛。

复现显式 NVIDIA 组时，仅给本次启动进程设置环境变量：

```bash
MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA \
  bash simulation/px4_gazebo/scripts/start_three_uav.sh --headless \
  --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json
```

对照 fixture 见
[`fixtures/mono-cam-gpu-adapter-20261005.json`](fixtures/mono-cam-gpu-adapter-20261005.json)。
**这解除本机三机相机的 RTF/standalone health 阻塞，但尚未完成本轮真实飞行
和 Runtime integrated 验收。** 执行端继续保持 `camera_not_validated`。

## 复现与下一轮门槛

先确认 Runtime、其他 PX4/Gazebo 及 endpoint 已空闲，然后在 WSL 中执行：

```bash
cd /mnt/d/2026UAVSwarm-worktrees/px4-gazebo-runtime-integration
python3 simulation/px4_gazebo/harness.py validate-config \
  --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json
bash simulation/px4_gazebo/scripts/start_three_uav.sh --headless \
  --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json
python3 simulation/px4_gazebo/scripts/verify_three_uav_cameras.py \
  --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json \
  --duration 15 --output .runtime/px4_gazebo/camera_acceptance.json
python3 simulation/px4_gazebo/scripts/health_three_uav.py --mode standalone \
  --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json \
  --stability-window 10 --pretty
bash simulation/px4_gazebo/scripts/stop_three_uav.sh
```

相机采样脚本只订阅 Gazebo，不连接 MAVLink。其 `camera_stream_status=observed`
仅表示图像流和本场景的三路区分证据成立；`system_readiness=not_assessed`。
完整验收还需逐机飞行、持续图像采集与安全停止，最后由 Runtime 独占 session
进行 integrated 验收。任何一步失败都不能把
`CAPTURE` 或 `OBSERVE` 标为执行成功。
