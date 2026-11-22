# target-001 的像素复核判据及独立反例

基线 `2d01ffc`。判据 ID：`target-001-green-disk-pixels-v0.1`。
范围限于 `simple_recon_v0_1 / simple_recon_v0_1-map-1` 的**绿色虚拟代用标记**。
这不是设备识别器、飞控或观测 API；关联包装只是 Fake 联调夹具，不冻结线上接口。

## 人工判定只看原图

参考外观来自已跟踪的 [SDF](../../../scenarios/simple_recon_v0_1/worlds/simple_recon_v0_1.sdf)：
`target-001-marker` 是绿色薄圆盘。斜视时可以呈椭圆，不以某个 RGB 精确值作为判据。
复核员只用当前这一帧的原始 RGB 像素；可以放大查看，但按原分辨率记像素框。
不得用坐标、到场、模型输出、标记 ID、场景真值或画面叠加提示补足缺失的视觉证据。

- **`observed` 的合格例**：原图中有唯一可区分的实心绿色圆盘或椭圆，
  其颜色和连续曲边能与背景、反光或色条区分，主要轮廓没有被遮挡、裁切。
  本夹具建议候选框短边至少 16 个原图像素；这是待验证的可读性下限，不是通用或实测指标。
  复核员记原图范围内的 `region {x,y,w,h}` 和说明。绿色块、只有一截边、多个不可区分的相似物都不足以成立。
  这里是正例**判据**，没有提供「已看见」或真采集结论。
- **`not_observed`**：仅当原图像素本身能确认预期复核区域在画面内并足够清楚，
  才能说明「本图按判据没看到」；附所看区域和说明。不能从「照片里没有绿色」推断实际场景没有目标。
- **`undetermined`**：看不清、区域无法从画面确认、轮廓不完整或有无法区分的候选时，
  如实记原因。这和帧的来源或字节校验失败不同，不把有效帧记作无效，也不将其记作目标缺失。

即使将来获得人工 `observed`，观察记录仍保持 `linked_task_completion: not_asserted`；
不以标签替代 Runtime 任务完成证据。本例没有运行模型，没有调用飞控、SITL 或共享服务。

## 同一有效帧仍不能判定的反例

[复核夹具](../examples/target_001_valid_capture_undetermined_v0_1.json) 引用仿真侧
本地提交 `6952513e8ee8482d7cf48e364603b2893909dbfe` 的
`docs/simulation/fixtures/simple_recon_v0_1_target_001_capture_v1.json`。
脚本从其色条配方重建**同一份**原始 RGB8（1280×960、3,686,400 字节）并复算 SHA-256；
不是另一张图，也不使用仿真真值判定。帧的接收年龄 50 ms、与位姿帧差 1 ms，仅是夹具数据。
整帧只有交替色条而无可辨认的圆盘轮廓，复核结果为 `undetermined`，有说明且
`confidence: null`。`human:fixture-reviewer` 是**测试占位符**，不是人工签发记录。

| 复核或绑定字段 | 来自哪里 |
| --- | --- |
| `plan_id / runtime_run_id / node_id`、到场 `goto-1` | 上游 `arrival`；同一 Fake 计划和 Runtime run、同一 UAV-02。被提议的 `observe-01` 不代表已启动步骤。 |
| `scene_id / map_version / target_id` | 同一采集夹具；`TASK-target-001` 是测试任务名，不等同执行 `plan_id/run_id`。 |
| `capture_id` | 上游只有 `request_id`，本例以规范化 JSON 的 `plan_id, runtime_run_id, request_id, image_ref` 哈希派生测试标识；不是 Runtime 签发的 ID。 |
| `image.ref / sha256 / width / height / encoding` | 同一 sample 和重建字节；`vehicle_id` 取到场节点；`camera_id` 使用该 sample 的完整传感器话题前缀，避免用通用 `camera_link` 充当全局 ID。 |
| `image.captured_at` | 原始模拟纳秒时间仍另存；复核字段用测试纪元 2000-01-01 + 模拟偏移表达 ISO 时间，不是现实 UTC，也不用于上游帧时效判断。 |

本例期望 `capture=fixture_valid`、`observation=undetermined`、不推进 `observe-01`。
这组期望供 Runtime 的独立 Fake 测试使用；算法侧复跑验证的是来源、字节、字段和 L2 结构，
不是 Runtime 生命周期、人工确实看过或现场采集已验收。

## 离线复跑

从本短分支的仓库根目录执行。脚本核对外部夹具的规范化 SHA-256；
仿真工作树若已切换版本，使用上面的固定提交中的同一文件。

```powershell
$env:PYTHONPATH = 'src'
python -B algorithm_lab/mission_llm_poc/scripts/check_target_001_review_fixture.py --capture-fixture 'D:/2026UAVSwarm-worktrees/simulation-observation-evidence/docs/simulation/fixtures/simple_recon_v0_1_target_001_capture_v1.json'
```

预计得到 `cap-11f8579bf75d7dd8` / `rev-6b0fd6110cade0c1`，验证结果是
`fixture_valid` 与 `undetermined` 同时成立。

## 可复核的合成正例

[正例标注](../examples/target_001_visible_pixel_annotation_v0_1.json) 引用仿真本地提交
`940a9d93a74e1fa98d312a39969f8e220212d107` 的原 PNG 和对应清单。原图下部中央只有一个
完整绿色实心椭圆，记录原像素框 `(500,736,281,121)` 和可供人工复核的理由。PNG 文件
与解码后的 RGB8 分别算哈希，图像、采集和 Runtime run 身份均与旧色条反例不同。
这只是一份可复核标注：`observed` 是合成条件下的**预期**，`review_record` 仍为
`null`。没有签发人工结论就仍是观察未判定，不改变任务或收尾，也不证明现场相机成像。

可用本机已安装的 Pillow 做独立解码验证；没装时可在仿真分支运行其
`tests/unit/test_target_001_visible_capture_fixture.py`（不请求安装依赖）。
从本算法短分支仓库根目录运行：

```powershell
$env:PYTHONPATH = 'src'
python -B algorithm_lab/mission_llm_poc/scripts/check_target_001_visible_annotation.py --simulation-root 'D:/2026UAVSwarm-worktrees/simulation-observation-positive'
```

## 观察失败后的 Fake 收尾验收断言

这组断言给 Runtime 测试使用，不新增线上状态或权限：

- `OBSERVE` 超时或失败后，保留任务失败及原始原因，后续名义任务步骤不推进。
  合格采集后 `undetermined/not_observed` 不算观察完成；复核记录本身不执行或授权收尾。
- 收尾独立于原计划的剩余步骤，仍需从 Runtime 自己的授权和 Policy 路径进入。
  Runtime 的本地 Fake 实现（`4df1408`）要求本节点、同计划/run 与同标定会话下的新鲜且对齐的证据，
  同时确认 landed、disarmed 和已标定的近地判据 `at_ground`。已证实收尾也不改变原任务失败，
  不补报后续动作成功。
- 普通 `LAND` 处在 pending、只有 ACK、只证实落地或只证实解锁关闭、证据陈旧、
  错节点或错 run，均不能报「收尾已证实」。超出 Fake 收尾验证窗口后缺证据，应保留收尾
  未证实及原因，不将其当作任务完成。双向对照更换 L2 为 `observed` 且
  `linked_task_completion:not_asserted` 时，不能因此得到收尾授权或把任一结论补为成功。

分别在 Runtime 的两个独立工作树复跑：`e26cc23` 的
`tests/integration/test_observe_offline_evidence_handoff.py` 用固定色条/未判定夹具，31 通过；
`4df1408` 的 `tests/integration/test_observe_failure_cleanup_fake.py`，35 通过。
后者还覆盖了「航点全到达但任务失败」：`completion_basis=verified_waypoints` 时的 100% 只是航点到达率，
不能当巡检完成率，也不证明收尾；收尾状态另看对应证据。本次没有接生产收尾执行链路或写入 Runtime。
