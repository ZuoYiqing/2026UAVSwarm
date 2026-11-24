# target-001 导航场景与离线验收

固定基线 `6a680fe`，场景 `simple_recon_v0_1`，地图 `simple_recon_v0_1-map-1`。本轮范围是静态场景核对与 Fake I/O 联调。[场景夹具 v1](fixtures/simple_recon_v0_1_target_001_navigation_v1.json) 的 `proposal` 字段供评审使用。Runtime 的执行请求和进度仍用既有接口。

## 场景事实

公共坐标系为 `scene_ned`，单位米，顺序为北、东、下。Gazebo ENU 位置 `(E,N,U)` 对应场景位置 `(N,E,-U)`。两者使用同一个 WGS84 场景锚点。场景文件保留历史的 `frame: local_ned`，应以 `public_frame: scene_ned` 解读全局几何。PX4 每机的 `vehicle_local_ned` 是该会话的独立原点，实际使用时由现场标定提供平移。起飞相对高度、场景 `down_m` 和当地离地高度需要分别解释。

| 稳定对象 | 位置与物理含义 |
| --- | --- |
| `target-001` | 地面参考点 `(30,15,0)`，半径 3 m。SDF 的 `target-001-marker` 是 0.1 m 厚的圆形视觉标记，底面在地面，无碰撞。可在示例任务中明确指定为设备巡检的代用标记。 |
| `building-001` | 中心 `(15,0,-5)`，北、东、高尺寸 `6×6×10 m`，SDF 有碰撞。 |
| `nfz-001` | 轴线 `N=10, E=10`，半径 5 m，`-20 ≤ down_m ≤ 0`。SDF 标记用于显示，约束由规划和执行准入检查。 |
| `landing-pad-UAV-01/02/03` | 各机起点在 `(0,0,0)`、`(0,8,0)`、`(0,-8,0)`。标记无碰撞，承重面是 `ground_plane`。 |
| `ground_plane` | `down_m=0`，北、东尺寸各 2000 m。 |

夹具以现有覆盖区 `three-uav-patrol-coverage-v1` 约束参考中心线，范围北 `[-45,50]`、东 `[-25,25]` m。这是此样例的范围，东侧 `E=25` 航段在覆盖区边界上。它不能代替飞行边界或避障检查。SDF 还有 `city-block-4-3` 的 12 个碰撞盒，均位于范围以北。对应 ID、位置和尺寸可查[既有几何导出](../fixtures/simple_recon_v0_1_scene_affordances.json)，本轮逐项与 SDF 核对了这些盒子。几何导出的审查状态仍为 `exported_from_physics_pending_review`。

## 参考航段

UAV-02 从 `(0,8,0)` 垂直上升 6 m。夹具列出五个 GOTO 点，依次为 `(0,25,-6)`、`(30,25,-6)`、`(30,15,-6)`、`(30,25,-6)`、`(0,25,-6)`。第三个点是目标正上方，索引从 0 开始。样例人工编写，用于构造可复现的 Fake 测试输入。算法需要另行从任务描述和场景生成候选计划。

离线检查覆盖每段参考直线和垂直上升，对盒形障碍和禁飞区使用 2 m 几何余量。该余量是样例参数，没有标定实机跟踪误差。若从 `(0,8,-6)` 直接连线到目标上方，将穿过 `nfz-001`，即使两端都在区外。最后一点位于 `N=0,E=25`，仍距 UAV-02 起降标记 17 m。如果要验收回原起降点，应另设 `(0,8,-6)` 到达步骤，随后单独取得落地证据。五点样例不支持“已回机位”的结论。

## 同一执行的证据

1. 计划使用已约定的 `POST /api/plans/execute`。保留候选的 `plan_id`、`intent_id`、`scene_id`、`map_version`，并给每步分配唯一 `step_id`，显式指定 `node_id`。GOTO 的 `north_m/east_m/down_m` 使用公共坐标。实际执行由操作者确认，Runtime 按步检查 Policy。夹具只提供导航输入。
2. 通过 `GET /api/mission/progress` 读取同一计划的 `mission_id=plan_id`，记录本次执行的 `run_id`。它与 Gazebo harness 的启动 ID 分开记录。将步骤结果按本次执行、步骤和节点关联起来，并保留动作返回的请求与追踪标识。旧执行的结果、其他节点的位置和历史 standalone 巡检记录不能归到当前执行。
3. 对照每个 GOTO 的目标和到达容差，要求同一步出现到达结果。ACK 只记录命令应答。基线进度以 `result=pass` 和 `arrival_observed=true` 累计已到达 GOTO，显示 `completion_basis=verified_waypoints`。对证据做位置复核时，还要有动作开始之后的样本（`sequence > start_sequence`），以及同场景、同地图、同位置 epoch 的有效标定。将样本 `(north,east,down)` 加上对应标定平移，得到公共位置，再比对三维到达误差。位置样本缺失、过期、重复、epoch 变化或标定失效时，不能作为本轮位置或覆盖证据。
4. 基线的 waypoint 计数和可选覆盖计算是两条判据。缺少可用位置证据时，已到达计数可能仍增长，不能因此增加位置覆盖或认定观测目标。五个 GOTO 全部达成时进度可显示 `5/5` 与 `100%`，最后的 LAND 仍须有自己的动作终态。真实落地要求新鲜的 on-ground、disarmed 和经标定的地面位置证据。Fake 中这些事实只能由测试桩构造并标明来源。
5. 到达目标上方证明导航到场。目标识别和设备状态需要独立证据，`targets_found` 和 `targets_total` 在本轮保持未知。没有执行时应保留 `no_runtime_plan_execution`，不要从路线本身推测进度。

离线校验可执行 `python -B -m pytest -q tests/unit/test_inspection_navigation_fixture.py`。测试从仓库里读场景、SDF、两种 manifest 和几何导出，无需 PX4、Gazebo 或端口。后续真实联合验收需要算法候选、Runtime 执行关联、正在运行的同版本世界和当次有效标定。该验收还需记录实际轨迹、位置误差、未分配节点状态和落地结果。
