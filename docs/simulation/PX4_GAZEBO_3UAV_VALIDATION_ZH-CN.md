# PX4 / Gazebo 三机验证记录

## 1. 结论

状态：**PASS（SITL_ONLY）**

验证日期：2026-07-30（Asia/Shanghai）

本记录只证明本机三架 PX4 SITL + Gazebo 的身份、heartbeat、单机控制隔离、低高度起飞和
降落闭环。它不代表实机、编队、复杂航迹或集群算法已完成。

## 2. 环境

| 项目 | 值 |
| --- | --- |
| PX4 commit | `171f0f38cffa95f28d5e159f7aaf7599756f9e0e` |
| Gazebo Sim | `8.14.0` |
| UAV repository base commit | `11a22f9` |
| 模式 | headless |
| world | `simple_recon_v0_1` |
| model | 三架 `gz_x500` |
| 目标高度 | 2.0 m |
| 完成阈值 | 1.4 m（70%） |

验证时 UAV repository 是 dirty worktree，包含本任务修改和任务开始前已有的 audit、
egg-info、pytest 缓存等本地运行产物。未执行 Git commit/push。

## 3. Mapping

| node_id | instance | sysid | model | endpoint | spawn NED |
| --- | ---: | ---: | --- | --- | --- |
| UAV-01 | 0 | 1 | `x500_0` | `udpin:127.0.0.1:14540` | `(0, 0, 0)` |
| UAV-02 | 1 | 2 | `x500_1` | `udpin:127.0.0.1:14541` | `(0, 8, 0)` |
| UAV-03 | 2 | 3 | `x500_2` | `udpin:127.0.0.1:14542` | `(0, -8, 0)` |

## 4. 静态和单元验证

| 检查 | 结果 |
| --- | --- |
| Python compile | PASS |
| manifest validation | PASS |
| scene validation | PASS，`vehicle_count=3` |
| `gz sdf -k` | PASS |
| shell `bash -n` | PASS |
| 相关 unit tests | PASS，18 passed |
| 默认完整 pytest | PASS，230 passed |

unit tests 使用 fake heartbeat、fake PID 和 fake model probe，不访问 `14540/14541/14542`。

## 5. Health 结果

| node_id | expected sysid | observed sysid | heartbeat | process | model | readiness |
| --- | ---: | ---: | --- | --- | --- | --- |
| UAV-01 | 1 | 1 | PASS | alive | `x500_0` | PASS |
| UAV-02 | 2 | 2 | PASS | alive | `x500_1` | PASS |
| UAV-03 | 3 | 3 | PASS | alive | `x500_2` | PASS |

三个 observed sysid 唯一，未出现 telemetry 串线。

## 6. 控制隔离和动作完成

### UAV-01 active

| 项目 | 结果 |
| --- | --- |
| ARM ACK | accepted |
| TAKEOFF ACK | accepted |
| 最大观测高度 | 1.41 m |
| 起飞阈值 | reached |
| UAV-02 passive | unarmed，最大 0.022 m |
| UAV-03 passive | unarmed，最大 0.015 m |
| LAND ACK | accepted |
| 最终观测高度 | 0.105 m |
| 落地连续样本 | PASS |

### UAV-02 active

| 项目 | 结果 |
| --- | --- |
| ARM ACK | accepted |
| TAKEOFF ACK | accepted |
| 最大观测高度 | 1.41 m |
| 起飞阈值 | reached |
| UAV-01 passive | unarmed，最大 0.000 m |
| UAV-03 passive | unarmed，最大 0.033 m |
| LAND ACK | accepted |
| 最终观测高度 | 0.112 m |
| 落地连续样本 | PASS |

### UAV-03 active

| 项目 | 结果 |
| --- | --- |
| ARM ACK | accepted |
| TAKEOFF ACK | accepted |
| 最大观测高度 | 1.40 m |
| 起飞阈值 | reached |
| UAV-01 passive | unarmed，最大 0.000 m |
| UAV-02 passive | unarmed，最大 0.038 m |
| LAND ACK | accepted |
| 最终观测高度 | 0.108 m |
| 落地连续样本 | PASS |

原始机器可读结果保存在 `.runtime/px4_gazebo/validation/`，该目录不提交 Git。

## 7. 停止验证

`stop_three_uav.sh` 返回成功。停止后：

- 无 PX4 进程；
- 无 Gazebo world topic；
- `harness_state.json` 已删除；
- 三个 `px4.pid` 已删除。

未使用全局 `pkill`/`killall`。

## 8. 已知问题与未测试

- 首次冷启动曾在 45 秒模型等待窗口内超时，自动清理成功；第二次启动三机成功。首机等待现
  已提高到 75 秒，后续实例为 45 秒。
- Gazebo GUI：**NOT TESTED**，本轮只验证 headless。
- 三架同时起飞：**NOT TESTED**，本轮按要求优先验证逐机隔离。
- 编队、航点任务、避障、故障注入：**NOT IMPLEMENTED**。
- Runtime 多会话 Registry 和 `/api/vehicle-snapshot`：由下一工作线实现。
- 5/10 架真实资源与性能：**NOT TESTED**。

## 9. 状态分类

**IMPLEMENTED**

- manifest、三机 scene、对齐 world、launcher、stopper、health、isolation validator。

**UNIT TESTED**

- 身份唯一性、端口规则、scene 绑定、NED/ENU/yaw、health 判定、SDF 模型边界。

**INTEGRATION TESTED**

- 三机启动、三个唯一 heartbeat、逐机 ARM/TAKEOFF/LAND、被动隔离、动作完成、停止清理。

**NOT TESTED**

- GUI、同时起飞、编队、复杂任务、5/10 架、Runtime 多机接入、Cesium 实时链路。
