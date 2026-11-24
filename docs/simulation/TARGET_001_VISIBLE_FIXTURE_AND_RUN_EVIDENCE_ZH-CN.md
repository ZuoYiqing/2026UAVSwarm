# target-001 可辨认正例与当次取证清单

项目基线 `2d01ffc889d70e64f74391a5dce6f8eadd77ce38`，采集夹具基线 `6952513e8ee8482d7cf48e364603b2893909dbfe`。本轮交付独立合成图、可复跑校验及未来窗口的取证清单。

## 同一判据的三个离线样本

| 样本 | L1 采集归属 | L2 观察 |
| --- | --- | --- |
| [绿色椭圆 PNG](fixtures/target_001_visible_synthetic.png) | [正例元数据](fixtures/simple_recon_v0_1_target_001_visible_v1.json) 沿用 UAV-02 的 manifest、相机参数以及 Fake 位姿和时间配对。用独立的 Runtime run、Gazebo run 与采集请求 ID。 | 图中只有一个完整绿色实心椭圆，原始像素框为 `x=500, y=736, w=281, h=121`。算法侧可按 `target-001-green-disk-pixels-v0.1` 构造 `observed` 的测试复核。只有采集样本时，观察仍是 `undetermined`。 |
| 原夹具的色条帧 | 同节点、时间新鲜且字节完整。 | 整帧没有可辨认的标记轮廓，也无法仅从画面确认应复核的区域。保留 `undetermined`。 |
| 原夹具的错机话题或旧帧 | 即使像素哈希正确，错机话题返回 `image_source_mismatch`，不晚于本次采集水位的帧返回 `frame_stale`。 | 采集证据未通过，保留 `undetermined`。 |

合成图的尺寸为 1280×960，颜色顺序为 RGB，每通道 8 bit。PNG SHA-256 固定在 `image.png_sha256`，解码后 3,686,400 字节的原始 RGB SHA-256 写在 `overrides.sample.payload_sha256`。两者对应不同字节序列。组合时将 `overrides` 按段覆盖原夹具的 `arrival`、`capture_request`、`sample`，从 PNG 解码像素并替换原夹具的 `synthetic_rows_rgb` 像素来源。原文件保留以复跑两个反例。

椭圆由确定性像素方程生成，轮廓未裁切，无标注覆盖层。像素框用于校验这份合成样本，现场照片的复核员应从原图独立记录位置。正例没有 Gazebo 实拍或真实人工签发记录，`expected_outcome_for_synthetic_pixel_review` 是预期值。L2 测试记录沿用 `linked_task_completion: not_asserted`。

## 将来同一运行的取证清单

| 证据 | 当次保存与核对 |
| --- | --- |
| 批准、任务及采集关联 | 记录 Runtime 的 `plan_id / run_id / arrival_step_id / observe_step_id / request_id / node_id / target_id` 及 Policy 决定、步骤结果。分别保留到场证据与采集请求。Runtime 执行 ID 由 Runtime 附加，PX4 或 Gazebo 消息不自带该 ID。 |
| 仿真来源与归属 | 保存 harness 的 `gazebo_run_id`、受管进程身份、`scene_id / map_version`、world 摘要及算法、manifest 版本和实际 Gazebo model 实体 ID。用 manifest 从节点推导图像与 `camera_info` 话题，采集器记录订阅回调的实际来源。重启、模型重建、时钟回退或绑定变化后废止原关联。 |
| 原图与光学参数 | 保存可回读的当次图像、采集 ID、格式、尺寸、行步长、编码、原始 RGB 或存储文件的明确哈希对象。记录图像帧原始仿真戳、`CameraInfo` 及内参，以及带轴定义和版本的机体到相机外参。单独以 UTC 时间供追溯。 |
| 同刻位姿与时钟 | 同 Gazebo run 和实体的 `base_link` 位姿保留 ENU 平移、姿态四元数及仿真戳，以同域仿真时间与图像配对，并报告时差。用单采集进程的 monotonic 核对采集请求、收包与截止，从相同仿真域的开始水位拒绝旧帧。另存公共 `scene_ned` 位置和当次标定版本、平移及会话 position epoch，PX4 本地坐标按有效标定转换。重启或 EKF 原点重置后重新标定。 |
| 观察结论 | 保留可追溯的复核人、图像引用和哈希、原图区域或说明、判据版本及结论。当前虚拟标记判据只支持从像素判断标记能否辨认，设备实际状态需另有证据。 |

采集及位姿配对的真实可用性、时差阈值、相机姿态和光学轴仍待现场验证。既有三路相机报告用于对照，本次证据必须从同一运行提取。

## 观察失败后的独立收尾

现有普通计划步骤在观察失败处停止，排在后面的 LAND 会留在未执行列表。本轮 Runtime 拟用隔离 Fake sink 验证独立收尾。记录触发的 `observe_step_id` 与失败原因、策略决定、稳定 `cleanup_id`、收尾启动前的 RX sequence 水位、同一 session epoch、单调起点及截止。按 `(Runtime run_id,node_id)` 关联和去重，观察任务保留失败。ACK 仅用来追踪动作投递。

收尾确认需要以下三份互相独立的证据，全部来自同一节点的长期 Runtime 会话及本次收尾窗口。Gazebo 图像的仿真戳不用于计算这些遥测的新鲜度。

1. **落地状态**来自 PX4 `EXTENDED_SYS_STATE` 的 on-ground，保存来源 sysid/compid、RX sequence、接收 monotonic、session epoch。
2. **上锁状态**来自 PX4 `HEARTBEAT` 的 armed=false，单独保存同样的身份和时间字段。两条状态样本均需在收尾水位之后、判定时仍新鲜。
3. **地面位置**来自新鲜 `LOCAL_POSITION_NED`、当次有效平移及同 scene/map/world 的地面参考。保留标定和 position epoch，并在两条状态之后取得位置。基线已有地面收尾判据要求位置落在参考平面范围、垂向误差 ≤0.3 m、至少三个连续样本且持续 ≥0.5 s。状态接收年龄上限为 2 s，位置间隔上限 0.5 s。未来 Fake 可使用独立测试阈值，实际策略以验收版本为准。

超时、样本缺失或过期、节点与 epoch 不一致、坐标未标定及地面未知均保留 `unconfirmed`。例如 ACK 已接收、飞控报 on-ground 且 armed=false，但经标定的位置仍在约 10 m 高的屋顶，不能认定在指定地面收尾。另一个反例是两条地面状态都在收尾水位之前，即使更新了外层报告时间也不可复用。[基线地面参考](fixtures/ground_reference_simple_recon_v0_1.json) · [屋顶事件复盘](RETURN_HOME_LAND_ROOFTOP_20261009_ZH-CN.md)

## 离线复跑

```powershell
python -B -m pytest -q -p no:cacheprovider tests/unit/test_target_001_visible_capture_fixture.py tests/unit/test_target_001_capture_fixture.py tests/unit/test_runtime_ground_completion.py
```
