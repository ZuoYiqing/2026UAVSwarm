# PX4 / Gazebo 三机验证记录

## 1. 历史真实基线

日期：2026-07-30（Asia/Shanghai）

结论：**PASS（SITL_ONLY，逐机隔离验证）**

该历史记录证明：

- 三个 Gazebo x500 model 存在；
- UAV-01 / UAV-02 / UAV-03 分别绑定 system_id 1 / 2 / 3；
- endpoint 分别为 14540 / 14541 / 14542；
- 三机逐机 ARM / TAKEOFF / LAND 成功；
- 主动节点飞行时，其余节点保持 disarmed；
- 停止后 PX4、Gazebo world、state 和 PID 文件已清理。

环境证据：

| 项目 | 值 |
| --- | --- |
| PX4 commit | `171f0f38cffa95f28d5e159f7aaf7599756f9e0e` |
| Gazebo Sim | `8.14.0` |
| world | `simple_recon_v0_1` |
| model | 3 x `gz_x500` |
| 模式 | headless |
| 逐机目标高度 | 2.0 m |
| 完成阈值 | 1.4 m（70%） |

逐机结果：

| node_id | ARM ACK | TAKEOFF ACK | 最大高度 | LAND ACK | 最终高度 | 被动节点隔离 |
| --- | --- | --- | ---: | --- | ---: | --- |
| UAV-01 | accepted | accepted | 1.41 m | accepted | 0.105 m | PASS |
| UAV-02 | accepted | accepted | 1.41 m | accepted | 0.112 m | PASS |
| UAV-03 | accepted | accepted | 1.40 m | accepted | 0.108 m | PASS |

该基线不代表三机同时巡检、航点飞行、Runtime 多机会话或前端实时联动已经验证。

## 2. 当前三机巡检工作线

分支：`codex/px4-gazebo-three-uav-mission`

新增目标：

- 10 秒连续 heartbeat 和 `LOCAL_POSITION_NED` 健康证明；
- Gazebo world/model/clock 和 Process Identity 联合证据；
- Standalone health 直连 MAVLink，integrated health 只消费 Runtime telemetry；
- Standalone validator 与 Runtime endpoint 强互斥；
- 8 / 10 / 12 m 三条固定 `scene_ned` 巡检航线；
- `scene_ned` 与每机 `vehicle_local_ned` 之间执行 spawn 平移和 yaw 旋转；
- PX4 telemetry 转回 `scene_ned` 后再计算障碍物、航点和机间距离；
- patrol JSON 同时记录 `scene_position` 与 `vehicle_local_position`；
- 每机 3 个航点、2 m 到达半径、连续新样本判据；
- 全程三机最小空间距离；
- 顺序 LAND 和 disarm 确认；
- 停止后 world 和 UDP 端口释放证明；
- 机器可读 health 与 patrol JSON。

当前自动化证据会在 PR 中记录。真实三机巡检只有在 WSL 中实际完成以下闭环后才能写为 PASS：

```text
start
-> 10 s health
-> retained isolation validation
-> deterministic patrol
-> land/disarm
-> stop
-> residual process/world/port check
```

## 3. 结果文件

真实运行证据写入：

```text
.runtime/px4_gazebo/validation/
```

文件包括：

```text
three_uav_validation_<timestamp>.json
three_uav_patrol_<timestamp>.json
```

这些是运行产物，不提交 Git。PR 只记录命令、统计、环境版本和结论，不能用单元测试替代真实飞行结果。
