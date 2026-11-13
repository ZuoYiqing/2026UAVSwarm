# 三机演示仿真交付 · 2026-11-13

本线基于 `bb24e38`，负责 11 月 12 日任务书的 S1–S4。weier 的离线部署记录
可作为环境基线。三机地面遥测就绪、三机空中运动、动作完成和任务完成分别验收。

## S1 · 三机运动和降级动作的现场证据

本机 WSL 的 PX4 为 `171f0f38cf`，Gazebo 为 `8.14.0`。本轮检查时 Windows
空闲物理内存实测为 0.89–2.50 GiB，低于此前三机相机仿真启动时
观察到的约 2.7–3 GiB 主机余量下降。本轮未启动三机，S1 现场飞行与 S4 的真实
起停尚待独占窗口。weier Gazebo 8.15.0 也需在该机器上复验。

历史证据包括三机逐机隔离 ARM/TAKEOFF/LAND、相机版三机静态标定和无飞行
integrated health。10 月相机版巡检曾记录部分入场航点到达，随后遇到 Gazebo
位姿探针失败。11 月 1 日只读 HOME/RTL 预检通过。上述证据均有各自的版本和范围。

在同一 WSL checkout，用相机版 manifest 启动三机。先确认 standalone health
退出并释放 14540–14542，再启动 Runtime。使用现场重新采集的坐标标定和
simulation evidence 完成预检。Runtime 独占三机 MAVLink 接收会话，验收人员
通过既有控制台或 Runtime API 执行动作。记录独占窗口内的 `run_id`、两侧版本、
world、三机标定、身份和端口。

在地面、未解锁时先启动旁路采样，覆盖全部三机的动作窗口：

```bash
python3 simulation/px4_gazebo/scripts/observe_runtime_motion.py \
  --duration 180 --interval 0.5 \
  --output .runtime/px4_gazebo/validation/runtime-motion.json
```

采样只读取 `GET /api/telemetry/latest`，核对 sysid/compid 和每机新鲜样本，
记录每机起飞前参考位置、原始 NED 坐标、武装标志及模式。NED 的
`local_position.z_down_m` 在上升时**减小**，相对初始参考的上升量为
`baseline_z_down_m - current_z_down_m`。脚本以每机相对上升至少 2 m、空中水平位移
至少 3 m、至少两次相邻样本相差 0.5 m 判断运动，适合演示前验收，结果只代表运动证据。

| 验收项 | 需要留存的证据 |
| --- | --- |
| 各机独立起飞与航点 | Runtime 动作结果和目标节点、逐机上升与水平移动样本、已到达航点误差。逐机隔离回归时另两机保持地面和未解锁。 |
| 各机 HOLD | 对应节点的模式、持续时间和实际位置漂移。 |
| 各机 RETURN_HOME | 当前版本预检可用，记录真实 PX4 HOME、RTL 模式、到达容差和持续到达证据。 |
| 各机 LAND | 另行验证 Runtime 允许的 LAND，记录 ACK、公共场景地面、实际 landed 与 disarmed。执行人员按 Runtime 的动作准入安排先后。 |
| 安全收束 | 所有节点均有新鲜落地及未解锁证据，停止 Runtime 后执行受管停止并记录端口、world 和进程组。 |

独立飞行回归使用现有 `patrol_three_uav.py`，开始前关闭 Runtime，结束后释放
三路会话。任务演示的 hold、返航、降落执行结果由 Runtime 留存。

## S2 · 共用坐标与几何范围

- **Gazebo 地物**包括 2000×2000 m 地面、`building-001` 的 6×6×10 m 实体盒、
  `target-001-marker`、`nfz-001-marker` 及三个起降坪标识。标识是可视模型，
  起降坪承重面是地面。还包含由青岚市布局生成的 `city-block-4-3`，
  中心约为 ENU `(-10,350)`，共 12 栋有碰撞的箱体建筑。这 12 栋建筑是同源
  几何参照。青岚河、桥、道路和其余街区没有对应的已验收物理场景。
- **现有标定**以 Gazebo 世界 ENU 位姿与 PX4 每机 `vehicle_local_ned` 样本配对，
  测量到公共 `scene_ned` 的平移。Gazebo 与 Cesium 的参考场景还需要同一 ENU
  渲染锚点与轴约定，不能把 PX4 局部原点平移直接当成青岚市配准。
- **演示视图选 `simple_recon_v0_1` 参考场景**。该 Cesium 视图已有地面网格和
  100 m 东、北标尺。场景 JSON、Gazebo WGS84 锚点与 Cesium reference 锚点均为
  纬度 47.3979709、经度 8.5461639、高程 0 m，单位为米。公共
  `(N,E,D)` 映射为 `(E,N,-D)`。所以 `(100,0,0)` 应在原点正北 100 m。
  青岚市合成锚点是纬度 39.9075、经度 116.3913，使用其展示模式时应保留仅展示标识。

**工期估算**：S2-a 已具备参考视图的原点与轴变换，具备现场窗口后预计半天核对
实际 100 m 参考点、屏幕位置和实测证据。S2-b 若扩大到一个 100–300 m 园区，
预计 2–4 个工作日完成稳定对象 ID、坐标、简化碰撞和复验，前提是三维负责人
确定任务区和导出版本。加入河流、桥、更多街区或地形需要另估。

## S3 · 覆盖面积

`scene.json.coverage_areas[]` 为新增区域，既有 `mission_areas` 的圆形定义
继续供原消费者读取。区域 `three-uav-patrol-coverage-v1` 的四个顶点使用
`scene_ned` 的 `north_m`、`east_m`，网格边长 1 m，总面积 0.00475 km²。
Runtime 可在当前任务中使用此函数：

```python
from simulation.px4_gazebo.area_coverage import AreaCoverage

coverage = AreaCoverage(scene, "three-uav-patrol-coverage-v1", footprint_radius_m=10)
coverage.observe(north_m=15, east_m=-20)
progress = coverage.report()
```

调用者负责按任务隔离实例、串行接入已校验且持续更新的公共场景位置。
`report()` 返回 `area_covered_km2`、`area_total_km2`、`completion_pct`、
`sample_count`、区域/地图身份、网格与足迹口径。栅格中心必须同时落在多边形
和至少一个圆形足迹内才计入面积。不会跨缺失样本插值。10 m 是演示假设，
此面积属于几何估计，目标发现和图像有效覆盖仍需独立证据。

Standalone 巡检使用 `--coverage-area three-uav-patrol-coverage-v1
--coverage-footprint-radius-m 10` 时会在最终 JSON 添加 `coverage`。它按机接入
巡航阶段新鲜、已标定的样本，故障时保留已有累计量和到达记录。Runtime R4
可消费同一函数口径，任务状态、活跃节点、降级、任务生命周期和发现目标由其
各自证据计算。Standalone 的报告不用于驱动正在运行的 Runtime。

## S4 · 受管起停

在同一 worktree 重复执行相同相机版启动命令，第二次应返回首轮 `run_id`。
检查 PID 未变且只有三个模型。更换配置、world 或运行模式时，先停止原运行。
启动的 world、PX4、模型资源和端口错误均给出路径或端口。关停后，报告必须
同时显示 `world_stopped=true`、`ports_released=true` 和空的
`live_group_member_pids`，第二次停止为幂等成功。若旧 Gazebo 子进程在 PX4
组长退出后仍存活，只有与已记录进程身份一致才会发送单进程信号。

## 本轮验证

- Windows 和 WSL 各 111 项通过、6 项跳过，跳过项需要真实三机。覆盖几何累计、
  运动判据、进程身份、健康、场景和标定。
- Cesium 参考场景坐标与城市布局合计 16 项通过。静态样本
  `scene_ned(100,0,0)` 投影为 `ENU(0,100,0)`。生成器的 12 栋楼和 SDF
  的建筑位置与碰撞尺寸逐一相符。现场飞行到参考点和屏幕位置待验证。
- 相机 manifest、Gazebo SDF、Python 语法、`bash -n`、ShellCheck 和
  `git diff --check` 通过。
