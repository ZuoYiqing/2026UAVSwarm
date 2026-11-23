# target-001 采集与观察证据提案

版本基线为 `2d01ffc889d70e64f74391a5dce6f8eadd77ce38`，场景为 `simple_recon_v0_1 / simple_recon_v0_1-map-1`。[离线夹具](fixtures/simple_recon_v0_1_target_001_capture_v1.json) 使用合成 RGB 字节检验采集证据的归属、时间和完整性。阈值与字段是评审提案。真实 SITL 取证另约窗口。

| 需要证明的事实 | 判据 |
| --- | --- |
| **到场** | 同一计划执行的指定节点收到 GOTO 到达结果，且有该次有效标定和新鲜公共坐标支撑。沿用[导航验收说明](TARGET_001_OFFLINE_NAVIGATION_ZH-CN.md)。 |
| **采集确认（L1）** | 同一请求收到指定 Gazebo 模型在采集窗口内发出的合格图像。保留可读图像、哈希、相机参数和与帧对齐的位姿，校验通过后再签发 `capture_id`。 |
| **观察结论（L2）** | 复核人根据这张图的像素判断该标记是否可辨认，记录目标、图像区域或理由和判据版本。复用[人工复核规格 v0.1](../OBSERVE_review_record_spec_v0_1.md)。无有效复核时保持 `undetermined`。 |

### 候选取景点

`target-001` 是地面视觉标记，中心参考为公共 NED `(30,15,0)`。当前相机版是前视 `x500_mono_cam`，历史三机采样确认了独立话题、RGB8 1280×960 和内参。物理模型配置的相机相对 `base_link` 安装平移为 `(0.12,0.03,0.242)` m，旋转为零，坐标按 Gazebo 机体定义。光学轴映射需在后续带图像取证中核实。[历史相机验收](MONO_CAM_3UAV_ACCEPTANCE_ZH-CN.md) · [接口草案的相机参数](../OBSERVE_interface_requirements_draft.md)

上一轮第三个 GOTO 是标记正上方，水平前视相机在该点通常无法直接看到机腹下方的标记。建议先验证已有东侧航点 `goto-1`，UAV-02 位于 `(30,25,-6)`，机头朝西、机体近水平。从机体参考点算，标记中心水平距离约 10 m、俯角约 31°，低于按标称内参估算的垂直半视场约 42°。安装偏移、姿态、遮挡及像素内容仍需实测。现有 GOTO 只在本样例中证明位置到达，取景朝向须另取同时刻姿态验证。地物坐标和视场只用于选点与离线评估。

### 字段来源与校验

| 字段 | 来源与判据 |
| --- | --- |
| `plan_id / runtime_run_id / step_id / node_id / request_id / target_id` | Runtime 当次执行和人工确认后的采集请求。到场步骤与采集请求分别标识，由受信记录关联。按执行 ID、步骤、节点和请求匹配，换 run 时重新绑定。 |
| `scene_id / map_version / world_sha256 / gazebo_run_id / gazebo_model_entity_id` | 场景及其版本、harness 本次受管运行和世界摘要、Gazebo 实际模型实体。运行与进程身份不一致，或 world/model 重建后，作废旧绑定。Gazebo 的启动 ID 与 Runtime 的执行 ID 各自保留。 |
| `image_topic / camera_info_topic / camera_frame` | 从有效相机 manifest 的节点映射推导完整话题，由订阅回调记录实际来源。UAV-02 的模型为 `x500_mono_cam_1`，两路话题分别以 `/camera/image`、`/camera/camera_info` 结尾。即使图像字节与时间戳一致，来自 `x500_mono_cam_0` 也拒绝。 |
| `image_sim_stamp_ns / camera_info_sim_stamp_ns / pose_sim_stamp_ns` | Gazebo 消息原始仿真时间。按同一次运行的采集请求保存开始水位，图像时间戳必须晚于水位。图像和相机信息由各自的消息取得。位姿按同一模型的 `base_link` 与 Gazebo 时间关联，不能用回调接收时间代替仿真戳。时钟回退或样本乱序时拒绝，缺少可靠位姿关联时等待或超时。 |
| `requested_monotonic_ns / received_monotonic_ns / checked_monotonic_ns` | 同一采集进程的单调墙钟，用于请求截止、收包先后和新鲜度。夹具提案以收包到校验 ≤500 ms、图像与位姿或相机信息相差 ≤100 ms 仿真时间为起点，阈值待实测。运行记录另存 UTC 采集时间供复核与追溯。 |
| `body_pose_enu / intrinsics_k / camera_frame` | 同一运行的 Gazebo 位姿与 `CameraInfo`。留存带轴定义的机体到相机外参和来源版本。验证四元数、相机参数及时间对应，公共 NED 按 `(E,N,U) → (N,E,-U)` 取位。若另附 PX4 遥测，其 EKF 局部位姿须经当次有效标定转换。 |
| `width / height / row_stride_bytes / encoding / payload_sha256 / image_ref` | `gz.msgs.Image` 及采集产生的不可变图像。第一版按 RGB8 1280×960、步长 3840、原始像素 3,686,400 bytes 校验。写入后回读，哈希必须与引用指向的**同一字节序列**一致。若另存 PNG，需给 PNG 本身独立哈希，清楚标明哈希针对哪种载荷。 |
| `capture_id / review_id / reviewer / criterion_version / outcome` | 采集成功后签发唯一采集 ID。人工复核用既有记录格式，并与已持久化的同任务、目标、节点和图像哈希关联。目标标记须能从像素本身辨认，`observed` 附图像区域或说明，人工置信度为 `null`。画面中没辨认到只适用于该张图。任务完成仍由上层依据任务条件独立判定。 |

`verify_three_uav_cameras.py` 已有按机订阅和流观测能力。它输出图像摘要与内参，作为后续采集器的来源参考。留下本次原图、绑定 Runtime 请求并配对机体位姿仍是下一轮的工作。Runtime 继续独占 MAVLink，拟议采集器只读受管 Gazebo 话题。人工批准、Policy、场景和坐标校验沿用现有执行要求。在采集能力验收前继续返回 `camera_not_validated` 或按现有规则拒绝。

### 正例、反例与复跑

- 正例使用当次 UAV-02 的到场记录，以及取景点处两行交替的合成 RGB 帧。复跑程序从夹具重建 3,686,400 bytes 并验证 SHA-256。结果为 `arrived / fixture_valid / undetermined`。该图用于验证关联与完整性，未产出真实图像或观察结论。
- 反例保留到场记录、字节、哈希和时间戳，只把图像来源换成 UAV-01。结果为 `arrived / image_source_mismatch / undetermined`。旧运行、旧帧、过期收包、未对齐位姿和哈希不符也各有回归断言。

离线回放还要求位姿和位姿仿真戳同时存在，ENU 位置为有限三维向量，姿态为有限的单位四元数，范数允许偏差 0.001。缺位姿或时间戳返回 `capture_pose_missing`，非法值返回 `capture_pose_invalid`。[独立合成位姿来源](fixtures/simple_recon_v0_1_target_001_pose_sources_v1.json) 记录两份已知夹具各自的 Gazebo run 与模型实体，用来与图像请求的绑定比对。缺来源返回 `capture_pose_source_missing`，错 run 或实体返回 `capture_pose_source_mismatch`。

回放采用独立的 1 s 请求截止，校验时刻达到截止即返回 `capture_request_timeout`，即使该帧刚收到。原有的收包年龄、仿真时间水位和配对窗口仍分别检查。1 s 及四元数容差是 Fake 检查参数，实际来源鉴别、相机姿态和时限仍需现场取证。原色条 JSON、可见正例 JSON 及图像字节均不变。

在本提交的工作区执行离线测试。

```powershell
python -B -m pytest -q -p no:cacheprovider tests/unit/test_target_001_capture_fixture.py tests/unit/test_inspection_navigation_fixture.py tests/unit/test_observation_review_record.py
```

后续独占窗口中，先从本次受管运行核对 world 摘要、已验证模型实体及三路图像话题。然后在 Runtime 正式批准的执行中关联指定节点的到场、采集请求、同帧图像与位姿。保存两例可回读证据供人工复核，一张取景候选图和一份同任务的拒绝记录。分别汇报到场、采集与复核结论。旧采样报告可供对照，每次验收须自带当次运行的图像和记录。
