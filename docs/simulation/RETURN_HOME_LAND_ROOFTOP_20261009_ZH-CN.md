# `return-home` 后 `land` 落在 10 m 屋顶：仿真物理证据

日期：2026-10-09。用户交接见主仓库 `ops/HANDOFF_return_home_then_land.md`。
运行场景 `simple_recon_v0_1`、地图版本 `simple_recon_v0_1-map-1`，
相机版三机，harness `run_id=3c62c0a0f9ab4e78a820832ae520acb4`，
PX4 commit `171f0f38cffa95f28d5e159f7aaf7599756f9e0e`，Gazebo `8.14.0`。
本报告只读解析该运行中的 PX4 ULog 和 world SDF，未绑定 MAVLink 或发送命令。

## 结论与时间线

`LAND` 没有被 RTL 覆盖。PX4 `Commander.cpp` 的
`VEHICLE_CMD_NAV_LAND` 分支强制请求 `AUTO_LAND`，记录
`Landing at current position`；ULog 同时证明 mode 从 RTL `nav_state=5`
切到 AUTO.LAND `nav_state=18`，随后下降。问题在于当前位置的正下方是屋顶，
飞控报落地、解除解锁与真实物理相符，但任务需要回到起降点。

证据源（本机 ignored，未提交 ULog）：
`.runtime/px4_gazebo/UAV-01/log/2026-10-09/03_43_32.ulg`。
时间 `t` 为该 ULog 的 PX4 boot 秒，不是墙钟时间；北/东/高度为 PX4 本机
local NED 近似值，与 scene_ned 的当次标定平移需分开理解。

| t (s) | 事件 / 模式 | 北 (m) | 东 (m) | 相对原点高度 (m) | PX4 `dist_bottom` | 落地状态 |
| ---: | --- | ---: | ---: | ---: | ---: | --- |
| 152.872 | `MAV_CMD_NAV_LAND`；ACK 152.876 s 接受；RTL→AUTO.LAND | 22.93 | -1.08 | 29.71 | 29.73 | 空中、armed |
| 167 | AUTO.LAND 下降中 | 15.62 | -0.71 | 9.87 | 10.11 | 空中、armed |
| 169 | 高度约 10 m | 15.61 | -0.71 | 9.96 | 0.01 | `landed=True` |
| 171 | 位置稳定 | 15.60 | -0.69 | 9.98 | 0.01 | `landed=True`、disarmed |

world `building-001` 是实际碰撞体：Gazebo ENU 中心 `(E=0,N=15,U=5)`，
箱体尺寸 `6×6×10 m`，故屋顶 `U=10 m`，水平覆盖公共场景
`N=[12,18], E=[-3,3] m`。该机停在 `N≈15.6,E≈-0.7`，屋顶范围内。
`dist_bottom≈0.01 m` 与碰撞体接触相符。此前手工只看相对原点高度约 10 m，
把它称作“空中悬停”；本证据表明是**屋顶着陆，未回到 home/pad**。
现场后续已发生另一轮飞行，当前模型在公共坐标约 `N=23.54,E=0.29,U≈0`，
PX4 `landed=True`、disarmed；不能用当前位姿代替事故时刻的位姿。

Runtime 审计记录还表明 `return-home` 当时 `initial_distance_m=28.625`，
`final_distance_m=23.704`，`distance_reduction_m=5.039`。它采用途中
`max_distance-final_distance` 判进展，因此不是 `28.625−23.704≥5`；
这里得到的证据只能证明开始向 home 收敛，不能证明已到 home。
本线已将 Runtime 的动作完成语义、pad 限制及 `/api/actions/recent`
重复记录问题移交 `agent runtime`。正式动作执行与 HTTP 路由不由仿真线修改。

## 仿真验收判据与站点边界

本线 standalone 巡逻仅验收 `simple_recon_v0_1` 的地面 `z_down=0`；
现在要求 `landed`、disarmed、公共 `scene_ned` 高度在地面 ±0.3 m 内，
并取得至少 3 个新位姿样本、保持 0.5 秒。屋顶的 `landed=True` 会报
`scene_ground_not_reached`，已上锁但没有地面证据时恢复流程不会重复发送 LAND。
这个判据**不**使 Runtime 的 `land` 动作自动变安全，且不能作为新场景
任意高度地面/屋顶的通用规则。

三处现有起降标识 `landing-pad-UAV-01/02/03` 的公共坐标中心分别为
`(N,E,D)=(0,0,0)/(0,+8,0)/(0,-8,0)`，world 中为半径 1.5 m 的
圆柱**视觉对象**，顶面 `U=0.05 m`；它们没有 collision，承重面是
`ground_plane` 的 `U=0` 碰撞平面。不能把视觉半径 1.5 m 直接当成
已验证安全半径。可先提案中心到位容差 ≤0.75 m，需逐机真实着陆验证后
再标 `valid=true`，并以单独版本化站点证据向 Runtime 发布；无证据时
Runtime 应拒绝“已在指定起降点”这一任务完成声明。
