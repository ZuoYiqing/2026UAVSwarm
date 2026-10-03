# OBSERVE 接口需求（草案，待各方确认）

**提出方**：Integration Owner（Runtime / 前端 / 仿真侧）
**日期**：2026-10-03（2026-10-04 更新：相机选型已确认，见第 2.4 节）
**状态**：**草案。** 本文只界定接口与判据，**不宣布能力可用**
**相关**：`docs/algorithm_side_round2_20260929.md`、`docs/payload_device_adapter_plan.md`、
`algorithm_lab/mission_llm_poc/docs/ROUND2_SCENE_BINDING_HANDOFF_20260930.md`

---

## 0. 为什么现在写这一份

算法侧的巡检计划是 `TAKEOFF → GOTO → OBSERVE → RETURN_HOME → LAND`。
**动作端点层面**，其中四个已实现并真飞验证（`RETURN_HOME` 与 `HOLD` 见
`docs/algorithm_runtime_execution_contract_v0_1.md` 3.1.1），只剩 `OBSERVE`。

> ⚠️ **但"只剩 OBSERVE"只对端点成立，对提案链路不成立。**
> 提案转换器 `tools/proposal-to-plan.mjs` 目前只展开 `TAKEOFF / GOTO / LAND`，
> 把 `HOLD` 与 `RETURN_HOME` 归入 `CONVERTER_NOT_EXPANDABLE`。
> 因此**即使 `OBSERVE` 端点实现，巡检提案仍会因整份拒绝而跑不通**。
> 这是算法负责人于 2026-10-04 指出的，我方确认其成立。
> 契约文档第 211-212 行原先写作"巡检任务现在只差感知载荷接口这一项"，
> **该表述不准确，已更正**。

`OBSERVE` 卡住的原因**不是"还没排上"**：它此前没有可依据的接口定义
（拍什么、存哪、如何判定"确实观察到了"），而且**仿真此前出不了图**。
在没有定义的情况下实现它，只会产生一个"看起来完成、实际没拍照"的假成功 ——
这正是本项目反复避免的那类失败。

---

## 1. `OBSERVE` 与 `camera_capture` 不是同一件事

仓库里已有一个**载荷桩**：`src/uav_runtime/adapters/payload_mapping.py` 声明了
`camera_capture`（`device_type: camera`，`placeholder_action: capture_image`），
`payload_adapter.py` 返回 contract-compatible 的 placeholder 结果。
**但它没有 HTTP 端点**，也从未接过真实设备。

| | `camera_capture` | `OBSERVE` |
| --- | --- | --- |
| 层级 | **设备动作**：让相机拍一张 | **任务动作**：确认"对某个目标进行了观察" |
| 需要什么 | 相机、参数（分辨率等） | 相机 **+ 目标绑定 + 判定判据 + 证据结构** |
| 成功意味着 | 触发了一次拍摄 | **该目标被有效观察**（可举证） |

**建议的关系**：`OBSERVE` 建立在 `camera_capture` 之上，是它的**语义封装**，
而不是另造一套设备接口。这样设备层只需实现一次。

---

## 2. 当前的事实边界（**实测，非推断**）

本节区分"已验证的事实"与"推断/未验证"，因为 OBSERVE 是否可做完全取决于这些事实。

### 2.1 仿真当前出不了图 —— 已实测

```
对运行中的世界查询话题，x500_0 上实际存在的传感器：
  base_link/sensor/air_pressure_sensor/air_pressure
  base_link/sensor/imu_sensor/imu
  base_link/sensor/magnetometer_sensor/magnetometer
  base_link/sensor/navsat_sensor/navsat
  airspeed_link/sensor/air_speed/air_speed
  flow_link/sensor/optical_flow/optical_flow
  lidar_sensor_link/sensor/lidar/scan            ← 2D 测距，非成像
  link/sensor/lidar_2d_v2/scan
  camera_link/sensor/camera_imu/imu              ← 注意：这是 IMU，不是相机
```

**没有任何 `image` 话题。** 也就是说：PX4 的 x500 模型**带了可选传感器的挂载位置**
（`camera_link` / `flow_link` / `lidar_sensor_link`），但**当前配置里没有装配成像传感器**。

> ⚠️ **一处必须纠正的早期说法**：我方曾在 `docs/OPEN_vehicle_capability_semantics_ownership.md`
> 中依据静态 SDF 写"未声明相机传感器"。静态检查**不足以**判断运行时有什么 ——
> 运行中的世界确实出现了 `camera_link`，只是它上面挂的是 IMU。
> 结论（拿不到图像）不变，但**依据必须是运行时话题**，不是读文件。

**这一项的直接影响**：`OBSERVE` 的"图像来源"**目前不存在**，需要仿真侧先解决选型，
这不是接口设计能绕过的前提。

### 2.2 可行的仿真侧选项（未验证，需仿真负责人确认）

同一 PX4 checkout 里有带成像的变体：

| 变体 | 组成 |
| --- | --- |
| `x500_mono_cam` | `x500` + `model://mono_cam` |
| `x500_mono_cam_down` | `x500` + `model://mono_cam` |
| `x500_depth` | `x500` + `model://OakD-Lite`（深度相机） |
| `x500_gimbal` | `x500` + `model://gimbal` |

**我方未验证**：切换后能否正常启动、图像输出格式与帧率、与现有三机 harness 是否兼容、
以及**仿真能成像是否代表真机能成像**（后者属机型负责人）。

### 2.3 载荷适配器已有桩，但无端点

`camera_capture` 存在 placeholder；把它接到 HTTP 端点上是集成侧能做的事，
**但它拍不到真实图像** —— 端点通了也只是"调用了一次桩"。

### 2.4 相机选型已确认（2026-10-04，仿真侧实测）

**仿真负责人已在隔离世界中实测 `x500_mono_cam`，输出真实场景图像**（完整 RGB 帧、
能看到测试场景中的实际目标，非空帧或占位消息）。**这解除了第 2.1 节的阻塞。**

| 项目 | 实测结果 |
| --- | --- |
| PX4 模型 | `gz_x500_mono_cam` |
| PX4 airframe | `4010_gz_x500_mono_cam` |
| 消息类型 | `gz.msgs.Image` |
| 像素格式 | `RGB_INT8`（即 RGB8） |
| 分辨率 | **1280 × 960** |
| 行步长 | 3840 bytes |
| 标称帧率 | 30 Hz |
| 实测采样间隔 | 32–36 ms |
| 水平视场角 | 1.74 rad ≈ **99.7°** |
| 相机信息类型 | `gz.msgs.CameraInfo` |
| `frame_id` | `camera_link` |

**相机内参（实测）**：

```
K = [ 539.93633,   0,        640,
        0,       539.93637,  480,
        0,         0,          1 ]
畸变参数均为零
```

**相对 `base_link` 的安装位姿**（来自模型定义）：
`translation = [0.12, 0.03, 0.242] m`，`rotation_rpy = [0, 0, 0] rad`

> ⚠️ **这是 Gazebo 机体坐标定义，不是光学坐标。** 目前**没有单独声明 ROS optical frame**，
> 因此**算法侧暂时不能自行假定 x-right / y-down / z-forward**。
> 光学坐标约定必须由**图像适配层**明确后，算法侧才能据此解释像素与视场。

**三机话题**（模型名将变为 `x500_mono_cam_0/1/2`）：

```
/world/simple_recon_v0_1/model/x500_mono_cam_<i>/link/camera_link/sensor/camera/image
/world/simple_recon_v0_1/model/x500_mono_cam_<i>/link/camera_link/sensor/camera/camera_info
```

### 2.5 其他变体的结论（仿真侧实测，供记录）

| 变体 | 结论 |
| --- | --- |
| `x500_gimbal` | **不能解决 OBSERVE**：只有云台机构和 `camera_imu`，**没有 `type="camera"` 成像传感器** |
| `x500_depth` | 能输出 1920×1080 RGB + 640×480 浮点深度，**但深度模型使用未按飞机隔离的话题**（`/depth_camera`、`/depth_camera/points`、`/camera_info`），**三机可能话题混流**。本轮不选 |
| `x500_mono_cam` | **话题按模型路径隔离，结构简单**，选作第一版 |

> `x500_depth` 这个话题混流的问题值得记住：**三机场景下"话题是否按载具隔离"是选型的硬条件**，
> 不只是参数好坏。混流会表现为"A 机拿到了 B 机的图"，且**不会报错**。

### 2.6 ⚠️ 三机兼容性尚未回归（**执行端在此之前必须禁用**）

仿真侧明确说明：当前三机正式世界与三个 MAVLink endpoint **正由 Runtime 联调占用**，
因此**没有抢占环境切换模型**。以下五项**尚未验证**：

1. harness 改为 airframe `4010` + `gz_x500_mono_cam`
2. 更新模型身份、health evidence 与测试 fixture
3. 回归三机启动、ARM / TAKEOFF / GOTO / HOLD / LAND
4. 验证**三路图像隔离**、持续帧率及 Gazebo 实时因子
5. 验证停止流程与端口释放

**因此：在上述三机回归完成前，执行端应保持禁用，或明确返回
`camera_not_validated`，不能报告成功。**
算法侧可以先行实现 `OBSERVE` 语义与图像结果校验。

---

算法侧在 `ROUND2_SCENE_BINDING_HANDOFF_20260930.md:43-47` 已给出最小数据需求，
**我方认为方向正确，直接采用**：

> 最小数据需求是有时间戳的 RGB 图像引用、相机内参/视场、相机相对机体位姿、
> 对应载具的场景定位和观察结果定义。可先以 640×480、5 Hz、图像年龄不超过 500 ms
> 作为**实验假设**建立基线；这些不是已确认的 x500 或真机指标。
> `OBSERVE` 的成功证据还需定义目标 ID、图像/检测引用、置信度、采集时间与对应节点。

**并明确**：具体相机变体、真机能力及阈值须由**仿真和机型负责人**确认。

---

## 4. 本草案提出的一处**关键设计分歧**（需要讨论，请不要默认接受）

算法侧要求证据里含 **"置信度"**。这里有一个我认为必须先想清楚的问题：

**仿真里没有真实目标，因此没有"真实的检测结果"。**

如果要产出"置信度"，只有三种可能：

| 做法 | 后果 |
| --- | --- |
| **A. 让仿真给出理想化的完美检测**（"确实看到了、置信度 1.0"） | 会得到一个**永远成功**的判据。在它之上做的任何算法评估都无意义 —— 那是在用真值冒充观测量 |
| **B. 让仿真输出"未检测到"** | 诚实，但无法验证任何感知闭环 |
| **C. 分层：先只证明"拍到并落盘"，不声称"看懂了"** | 可验证、可举证、不撒谎 |

**我方主张 C**，并建议把 `OBSERVE` 拆成两级：

| 级别 | 判据 | 当前可做性 |
| --- | --- | --- |
| **L1 采集确认** | 在**指定位置与时刻**确实拍到一张图像，且可举证（引用 + 时间戳 + 相机位姿 + 载具定位） | **仿真侧装了相机就能做** |
| **L2 观察判定** | 从该图像**判定**目标是否被观察到（检测/分类/人工） | **需要检测器或人工标注，仿真给不出真值之外的依据** |

**建议的实现顺序**：先做 L1，并把 L1 的结论明确表述为"采集已确认、观察未判定"。
**不要在 L1 之上就宣称"巡检完成"。**

> 这个分歧不解决就实现 OBSERVE，会重复本仓库已经踩过两次的失败形态：
> 命令被接受、零报错、而实际什么都没发生。

### 4.1 ⚠️ 状态语义：算法负责人指出的问题（**代码层面确认成立**）

算法负责人 2026-10-04 指出：

> 若 OBSERVE 步骤的完成条件是"确认目标"，L1 不应给该步骤返回会被 Runtime
> 当作任务完成的 `result: "pass"`；建议用明确的部分完成/待判定状态。

**我方核实后确认这成立，不是措辞问题**：

```python
# executor.py:362
ok = bool(accepted is True) and result != "fail" and status < 400
# lifecycle.py:365
if getattr(outcome, "ok", False):
    self.mark_step_succeeded(plan, step, mode="real", ...)
```

**即 `accepted=true` + `result="pass"` → 该步判成功 → 计划判 `completed`。**

**而且现有状态里没有中间态**：

```
StepStatus : pending / ready / needs_operator_confirm / running / succeeded / failed
PlanStatus : draft / validated / awaiting_confirmation / approved / executing / completed / blocked
```

`PlanStatus` **没有** partial / incomplete。所以"采集成功但观察未判定"**当前无处可放**。

> 注：`StepStatus.NEEDS_OPERATOR_CONFIRM` 存在，但它的现有语义是**执行前**的审批
> （`lifecycle.py:198` 按批准集合放行），不是**执行后**的待判定。复用它需要重新定义语义。

### 4.2 我方的修法建议：**改动作名，而不是加状态**

**根本问题是名字与完成条件不符**：计划里那一步实际做的是"拍一张照"，
而完成条件被写成"确认观察到"。**这两件事本来就不同；用新状态去补，是在给语义错位打补丁。**

| 方案 | 做法 | 代价 |
| --- | --- | --- |
| **A（我方建议）** | **动作叫 `CAPTURE` 而不是 `OBSERVE`**，完成条件 = "拍到合格图像"。计划诚实地说"我拍了照"，`pass` 语义正确。观察判定（L2）**根本不进执行计划** | **零架构改动**，语义诚实 |
| B | 新增 `partial` / `incomplete` 状态 | 需改 executor + lifecycle + PlanStatus + 所有消费方，改动面大 |
| C | L1 返回 `accepted=false` | 会被判失败 → 按"首败即止"**中止整份计划** |

**A 的关键好处**：它在**名称层面**就把"拍到照片"与"确认看到了东西"分开：

- `pass` 只声称"拍了照"——**这是真的**
- L2 判定在计划之外完成（人工复核或后续检测器），**它本来也不该由飞行计划保证**

**这与两位负责人的立场一致**：仿真侧要求"仅完成 HOLD 或到达航点不能算巡检完成"，
算法侧要求"L1 不应返回会被当作任务完成的 pass"。

**⚠️ 方案 A 会改动算法侧已写的动作名，需他们确认。** 在确认之前，本草案不预设结论。

> 无论选哪个方案，有一点不变：**不得把"采集完成"渲染成"巡检完成"。**

---

## 5. 建议的接口形态（L1，供讨论）

### 5.1 请求

```json
POST /api/actions/observe
{
  "node_id": "UAV-01",
  "target_id": "target-001",              // 可选：观察目标。缺省表示"观察当前视野"
  "expect_image": true,                    // 是否要求必须产出图像引用
  "settle_s": 1.0,                         // 拍摄前稳定时间
  "max_age_ms": 500                        // 图像时效上限（算法侧假设值）
}
```

### 5.2 响应中的完成证据（**必须能区分"采集"与"判定"**）

```json
{
  "result": "pass",
  "observation_state": "captured_only",     // captured_only | observed | not_observed
  "capture": {
    "image_ref": "<内容寻址的引用，非内联>",
    "captured_at": "2026-10-03T14:00:00Z",
    "width": 640, "height": 480,
    "age_ms": 42,
    "camera": {
      "sensor_name": "mono_cam",
      "fov_h_deg": null,                    // 由仿真负责人确认后填
      "fov_v_deg": null,
      "pose_in_body": { "x": 0.1, "y": 0.0, "z": 0.0 }
    }
  },
  "vehicle_pose_at_capture": {
    "scene_ned": { "north_m": 60.0, "east_m": 12.0, "down_m": -20.0 },
    "frame": "scene_ned"
  },
  "detection": null,                         // L2 才有；L1 必须是 null，不得编造
  "failure_reason": null
}
```

**L1 的判据**：`image_ref` 存在且可解析、`age_ms ≤ max_age_ms`、
`vehicle_pose_at_capture` 与当时遥测一致。
**L1 明确不声称**：目标被看到、被识别、被拍清。

### 5.3 失败原因码（建议）

| 原因码 | 含义 |
| --- | --- |
| `camera_capability_unavailable` | 该载具没有可用的成像传感器（**当前三台的默认结果**） |
| `image_capture_failed` | 有相机但未取到图像 |
| `image_stale` | 取到的图像超过 `max_age_ms` |
| `target_reference_unresolved` | `target_id` 无法解析到场景实体 |
| `observation_not_determined` | 采集成功但 L2 判定未实现（**当前应有且仅有的"拍到但未判定"结果**） |

---

## 6. 需要各方提供或确认的输入

| # | 需要什么 | 归谁 | 影响 |
| --- | --- | --- | --- |
| 1 | 仿真是否装配成像传感器；用哪个变体 | **仿真负责人** | **L1 能不能做的前提** |
| 2 | 图像输出的话题、格式、分辨率、帧率 | **仿真负责人** | 接口能否落地 |
| 3 | 相机内参 / 视场 / 相对机体位姿 | **仿真负责人**（真机另有其人） | 提供相机定位依据 |
| 4 | L2 的检测判据从哪来（检测器？人工？） | **算法负责人** | 决定 L2 是否可实现 |
| 5 | 真机是否有相机、指标如何 | **机型负责人** | 仿真能力 ≠ 真机能力 |
| 6 | 640×480 / 5 Hz / 500 ms 这几个基线值 | **算法负责人** | 目前是**实验假设**，须明确标注 |
| 7 | 观察结果的"够不够清楚"由谁判定 | **待定** | 这直接决定 L2 能否声称完成 |

**第 1 与第 4 项是硬阻塞**：1 不解决则 L1 做不了；4 不解决则 L2 做不了。

---

## 7. 我方（集成侧）能做与不做

| 能做 | 说明 |
| --- | --- |
| ✅ 把 `camera_capture` 从桩接到 HTTP 端点 | 与 `HOLD` / `RETURN_HOME` 相同的位置与方式 |
| ✅ 实现 L1 的采集确认与证据结构 | 前提是仿真能出图（第 6 节第 1 项） |
| ✅ 图像引用的**内容寻址与时效校验** | 与现有 `completion_evidence` 一致的举证方式 |
| ✅ 保证"采集"与"判定"在证据里**可区分** | 见 5.2 的 `observation_state` |
| ❌ 在仿真里装配相机 | 属仿真侧配置 |
| ❌ 伪造检测结果或置信度 | **这会制造假成功，是本次草案明确拒绝的做法** |
| ❌ 用仿真能成像推断真机能力 | 属机型负责人 |

---

## 8. 需要谁先动

按依赖顺序：

1. **仿真负责人**：确认能否/是否装配成像传感器（第 6 节第 1–3 项）
2. **算法负责人**：明确 L2 的检测判据来源（第 6 节第 4、6 项），并确认是否接受
   第 4 节的"先 L1 后 L2"分层
3. **集成侧**（我方）：在 1、2 明确后实现端点与 L1 证据

**在第 1 项明确之前，我方不做 OBSERVE 端点** —— 做了也只能调用一个拍不到图的桩，
那会产生"计划显示巡检完成、实际没有图像"的结果。

---

## 9. 相关文件

| 用途 | 位置 |
| --- | --- |
| 执行契约（3.1 已实现动作、3.1.1 真飞验证） | `docs/algorithm_runtime_execution_contract_v0_1.md` |
| 载荷适配器计划（`camera_capture` 桩的来历） | `docs/payload_device_adapter_plan.md` |
| 载荷映射表 | `src/uav_runtime/adapters/payload_mapping.py` |
| 能力语义定责（相机变体与真机能力归属） | `docs/OPEN_vehicle_capability_semantics_ownership.md` |
| 算法侧的场景绑定交接（提出证据需求处） | `algorithm_lab/mission_llm_poc/docs/ROUND2_SCENE_BINDING_HANDOFF_20260930.md` |
