# 算法侧 → Runtime 计划执行契约 v0.1

本文件规定**算法侧（Agent / 任务规划 / 集群智能）向 Runtime 提交计划、并读回执行结果**的接口。
它是 `docs/agent_plan_lifecycle_v0_1.md` 与 `docs/frontend_runtime_api_contract.md` 的姊妹文档。

**契约与"消息协议"的区别**：消息协议只规定字段名与格式；本契约还要规定**哪些动作真的能飞**、
**参数的方向语义**、**什么算成功**、**执行前必须满足什么条件**。少任何一项，都会出现
"字段全对、飞机没动"或"返回成功、飞机飞错"这类静默错误。

> 本契约的每一条都对应可执行代码与测试，不是设计意图：
> - 端点：`src/uav_runtime/http/routes.py` → `plans_execute`
> - 执行器：`src/uav_runtime/agent/executor.py`
> - 状态机：`src/uav_runtime/agent/lifecycle.py` → `execute_plan_real`
> - 测试：`tests/unit/test_plans_execute_endpoint.py`、`tests/unit/test_plan_real_execution.py`

---

## 0. 职责边界（先读这一节）

```text
算法侧（Agent / Swarm Intelligence）
  │  任务理解 → 任务分解 → 车辆分配 → 航点与路径规划 → 按反馈决定是否重规划
  │  产出：Mission Proposal（本契约第 2 节）
  ▼
POST /api/plans/execute
  ▼
Runtime（Mission Executor / Policy Gate / VehicleRegistry）
  │  计划校验 → 逐条执行 → 监控 ACK 与遥测 → 故障处理 → 如实报告
  │  **不发明规划策略**，也**不放松任何安全检查**
  ▼
MAVLink → PX4
```

两条必须理解的分工：

1. **提案不是授权。** 提案里写什么都不构成执行许可。每一步都会在 Runtime 内**重新**过
   Policy Gate，用**实时上下文**评估后才发 MAVLink 命令。
2. **"决定下一步干什么"与"保证当前动作真正完成"是两件事。** 前者属于算法侧，后者属于
   Runtime。Runtime 返回的完成证据就是为了让算法侧能区分这两者。

---

## 1. 端点

```text
POST http://127.0.0.1:8765/api/plans/execute
Content-Type: application/json
```

Runtime 默认监听 `127.0.0.1:8765`，仅本机回环可达。

---

## 2. 请求体

```json
{
  "operator_id": "operator-01",
  "decision": "approve",
  "plan": {
    "plan_id": "plan-20260928-001",
    "intent_id": "intent-001",
    "mission_type": "takeoff_goto_land",
    "explanation": "园区 A 巡检",
    "created_at": "2026-09-28T00:00:00+00:00",
    "steps": [
      {
        "step_id": "step-1-takeoff",
        "action_type": "takeoff",
        "node_id": "UAV-01",
        "params": { "altitude_m": 3, "stable_duration_ms": 2000 }
      },
      {
        "step_id": "step-2-goto",
        "action_type": "goto",
        "node_id": "UAV-01",
        "params": { "north_m": 30, "east_m": -20, "down_m": -8,
                    "arrival_tolerance_m": 0.8, "hold_s": 1.5 }
      },
      {
        "step_id": "step-3-land",
        "action_type": "land",
        "node_id": "UAV-01",
        "params": {}
      }
    ]
  }
}
```

### 2.1 顶层字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `operator_id` | string | **是** | 非空。真实执行必须可追溯到人。空白字符串会被拒。 |
| `decision` | string | 否 | `approve`（默认）或 `reject`。`reject` 是**合法请求**：审批被记录，但不执行任何动作。 |
| `plan` | object | **是** | 见下。 |

### 2.2 `plan`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `plan_id` | string | **是** | 非空。用于审计与后续按计划查询。 |
| `scene_id` | string | **是** | 非空。必须与 Runtime 的活动场景一致，见 5.3。 |
| `map_version` | string | **是** | 非空。必须与当前标定的地图版本一致，见 5.3。 |
| `intent_id` | string | 否 | 上游意图标识，便于串联。 |
| `mission_type` | string | 否 | 任务类型标签，仅用于显示与审计。 |
| `explanation` | string | 否 | 人类可读说明。 |
| `created_at` | string | 否 | ISO-8601；缺省时 Runtime 填入当前时间。 |
| `steps` | array | **是** | 非空数组。**顺序即执行顺序。** |

### 2.3 `steps[]`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `step_id` | string | **是** | 非空，计划内唯一。失败报告按它定位。 |
| `action_type` | string | **是** | 非空。取值见第 3 节，**小写**。 |
| `node_id` | string | **是（执行时）** | 目标载具，例如 `UAV-01`。**没有合理默认值——缺失会被拒绝**，见 5.2。 |
| `params` | object | 否 | 动作参数，见第 3 节。缺省 `{}`。 |

> `step_id` / `action_type` / `params` 的类型错误在 **HTTP 400** 阶段就被拒；
> `node_id` 允许为空字符串通过校验（以便报出"哪一步缺目标"），但**执行时会被拒绝**。
> 这一分工是刻意的：校验层管"结构是否合法"，执行层管"能不能飞"。

---

## 3. 动作支持矩阵（**最重要的一节**）

### 3.1 当前可真实执行的动作

| `action_type` | `params` | 完成判据 |
| --- | --- | --- |
| `takeoff` | `altitude_m`（默认 3.0）<br>`altitude_tolerance_m`（默认 0.3）<br>`stable_duration_ms`（默认 1000） | 高度进入容差并**稳定保持**指定时长 |
| `smoke_takeoff` | 同上，另 `auto_land`（默认 true） | 达到阈值比例并自动降落 |
| `goto` | `north_m` / `east_m` / `down_m`（`scene_ned`，见 4）<br>`arrival_tolerance_m`（默认 1.0）<br>`hold_s`（默认 1.0） | 三维距离**持续** `hold_s` 秒落在容差内 |
| `land` | 无（只需 `node_id`） | 落地且 disarmed |

`params` 里**端点不认识的键会被丢弃**，不会转成 Runtime 忽略的未知字段。这样规划层的拼写错误
不会静默生效。

### 3.2 已声明、但**无法执行**的动作

Runtime 的策略注册表声明了 **21 个动作**，其中只有 4 个有真实端点（3.1）。
其余按"为什么不能执行"分为三类，**错误措辞刻意不同**：

| 类别 | 动作 | 原因码 |
| --- | --- | --- |
| **未实现**（飞行类） | `hover` `hold` `hold_position` `return_home` `land_safe` `reduce_speed` `maintain_heading` | `action_endpoint_not_implemented` |
| **未实现**（系统类） | `health_query` `report_status` `sensor_read` | `action_endpoint_not_implemented` |
| **未实现**（载荷类） | `camera_capture` `gimbal_set_angle` `light_set_state` `speaker_play_message` | `action_endpoint_not_implemented` |
| **未实现**（上游专有） | `observe`（不在策略注册表内，但算法侧 schema 允许） | `action_endpoint_not_implemented` |
| **不支持**（高风险载荷） | `attack` `strike` `drop` `deploy` `payload_release` | **`action_not_supported`** |

后一类的措辞与"尚未实现"**刻意区分**：它们不是待办项，而是本执行路径不提供的能力。
把它们说成"还没实现"会读成"以后会开放"。

**所有不可执行的动作都会被拒绝，不会被静默跳过。**

> 为什么必须拒绝而不是跳过：跳过会产生"计划显示完成、实际什么都没发生"的**假成功**。
> 本项目已经踩过一次同类问题——位置设定点的 `type_mask` 写错时，命令被接受、
> 10Hz 流正常发出、零报错，而飞机一动不动。

**给算法侧的请求**：请把任务模板里的 `required_actions` 限制在 3.1 的集合内，或明确标注
哪些动作属于"待实现"。当前 `base_context.json` 里每个任务的 `required_actions` 是
`["TAKEOFF","GOTO","OBSERVE","RETURN_HOME","LAND"]`，其中 **3 个无法执行**
（`OBSERVE`、`RETURN_HOME` 未实现），因此这样的任务目前**无法端到端跑通**。

### 3.3 大小写

**大小写不敏感。** `TAKEOFF` 与 `takeoff` 等价，都会映射到 `/actions/takeoff`。

算法侧 schema 目前用大写（`TAKEOFF` / `GOTO` / `OBSERVE`），可以直接提交，
无需自行转换。拒绝响应里会**原样回显调用方写出的名字**（`requested_action_type`），
便于对照。

---

## 4. 坐标与方向（写错会撞地）

`goto` 的参数是 **`scene_ned`**：

| 字段 | 含义 | 符号约定 |
| --- | --- | --- |
| `north_m` | 北向，米 | 向北为正 |
| `east_m` | 东向，米 | 向东为正 |
| `down_m` | **向下为正** | **高度 8 米 = `down_m: -8`** |

⚠️ **`down_m` 是"向下为正"**。传 `down_m: 8` 表示"地面以下 8 米"，不是"高度 8 米"。

`scene_ned` 的原点是**共享场景原点**，不是载具自身位置。Runtime 会用标定测得的平移量
换算成每台载具自己的 `vehicle_local_ned` 再下发。**算法侧不需要做这个换算**，
也不应该自己做——两边各算一遍必然分歧。

这与算法侧 `base_context.json` 里航点的表示**完全一致**（`north_m` / `east_m` / `down_m`），
因此航点坐标可以原样使用，无需换算。

---

## 5. 前置条件（不满足则拒绝，不"尽力而为"）

### 5.1 坐标标定必须有效

`goto` 依赖 Runtime 内**每个节点**的坐标标定（由仿真侧发布，有效期 60 秒）。
标定缺失或过期时，动作会被拒绝：

```json
{ "result": "fail", "accepted": false,
  "failure_reason": "coordinate_calibration_unavailable",
  "calibration_status": "unavailable" }
```

**这是有意的。** 没有可信平移量而把 `scene_ned` 当本机坐标发出，载具会飞到一个
偏移量之外的错误位置（本项目三机各自偏移最大约 8 米）。长时间任务需要在飞行前
刷新标定。

### 5.2 每个步骤都必须有目标载具

**没有任何默认载具。** 任一 `step` 的 `node_id` 为空时，**整份计划在起飞前**即被挡下：

```json
{ "result": "blocked", "failure_reason": "step_target_vehicle_missing",
  "detail": { "steps_without_target": ["step-2-goto"] } }
```

之所以在起飞前全量校验：否则会出现"飞了第 1 步才发现第 2 步没目标"。

### 5.3 场景身份必须携带且必须一致（**已实现**，2026-09-28）

`plan.scene_id` 与 `plan.map_version` 是**必填**的非空字符串，Runtime 会在执行前
与自己的**活动场景**核对：

| 情况 | 原因码 |
| --- | --- |
| `scene_id` 与 Runtime 实际加载的场景不一致 | `scene_id_mismatch` |
| `map_version` 与当前标定的地图版本不一致 | `map_version_mismatch` |
| Runtime 无法确定自己的活动场景 | `scene_identity_unavailable` |

**任一情况都在任何一步起飞前拒绝整份计划。**

对照基准是 Runtime **实际加载**的场景（由 `scenarios/<id>/scene.json` 决定），
不是计划里声明的 —— 拿调用方的声明去核对调用方等于没校验。

为什么必须挡在这里：坐标只在某个场景里有意义。为 A 地图生成的计划若在 B 地图上
执行，飞机会飞到由错误基准推导出的位置，**而动作层不会报错** —— 它会老老实实
飞到那个错误坐标并返回 `pass`。

> 缺失字段同样被拒绝（HTTP 400）。不能因为"字段没填"就跳过校验：无法核对的
> 计划正是最该拒绝的情况。

**一个刻意的克制**：没有标定时**不**报 `map_version_mismatch`。缺标定是 `goto`
自己该报的 `coordinate_calibration_unavailable`，在此冒充"地图不匹配"会把调用方
引向错误的排查方向。

#### 5.4 计划必须经审批

`decision: "reject"` 时不执行任何动作，返回：

```json
{ "result": "declined", "failure_reason": "operator_rejected" }
```

---

## 6. 响应

### 6.1 成功（HTTP 200）

```json
{
  "result": "completed",
  "failure_reason": null,
  "execution_mode": "real",
  "plan": { "plan_id": "plan-20260928-001", "status": "completed", "steps": [ ... ] },
  "step_outcomes": [
    {
      "step_id": "step-1-takeoff",
      "ok": true,
      "action_type": "takeoff",
      "node_id": "UAV-01",
      "http_status": 200,
      "accepted": true,
      "result": "pass",
      "failure_reason": null,
      "evidence": {
        "completion_reached": true,
        "completion_state": "succeeded",
        "last_altitude_m": 2.753,
        "arm_result_name": "MAV_RESULT_ACCEPTED",
        "takeoff_result_name": "MAV_RESULT_ACCEPTED"
      }
    },
    {
      "step_id": "step-2-goto",
      "ok": true, "action_type": "goto", "node_id": "UAV-01",
      "accepted": true, "result": "pass", "failure_reason": null,
      "evidence": {
        "mode_confirmed": true,
        "arrival_observed": true,
        "arrival_error_m": 0.141,
        "arrival_reason": "stable_within_tolerance",
        "restored": true,
        "still_in_offboard": false,
        "observed_sub_mode": 3
      }
    }
  ]
}
```

上例取自 2026-09-28 的真实三机实测（UAV-01 起飞 → 北飞 8 米 → 降落，全程 28 秒）。

### 6.2 失败（HTTP 200，`result: "failed"`）

**失败即中止**（当前策略）：首个失败步骤停下，后续步骤**保持未执行**。

```json
{
  "result": "failed",
  "failure_reason": "action_endpoint_not_implemented",
  "aborted_at_step": "step-2-goto",
  "remaining_steps_pending": ["step-3-land"],
  "execution_mode": "real",
  "step_outcomes": [ ... ]
}
```

`remaining_steps_pending` 明确列出**从未执行**的步骤。绝不会出现"部分完成"的模糊状态。

---

## 7. 失败原因码

`step_outcomes[].failure_reason` 与顶层 `failure_reason` 使用同一套原因码：

| 原因码 | 含义 | 算法侧应如何应对 |
| --- | --- | --- |
| `action_endpoint_not_implemented` | 已声明但 Runtime 无端点 | **改任务模板**，不要重试 |
| `action_not_supported` | 高风险载荷类动作（`risk_level=10`），本路径不提供 | **不要重试**；这不是待办项 |
| `unknown_action_type` | 不在已实现、也不在注册表已声明动作里 | 检查拼写 |
| `step_target_vehicle_missing` | 该步骤没有 `node_id` | 补目标；整份计划被挡下 |
| `transport_error` | 无法连接 Runtime | 可重试（检查 Runtime 是否存活） |
| `malformed_response` | Runtime 返回了非对象 | 报告问题 |
| `coordinate_calibration_unavailable` | 标定缺失/过期（`goto` 专用） | **刷新标定后重试** |
| `offboard_not_confirmed` | PX4 未真正进入 OFFBOARD | 报告问题；不要盲目重试 |
| `arrival_timeout` | 未在超时内到达目标 | 检查目标可达性与距离 |
| `mode_restore_failed` | 动作完成但未收敛回安全模式 | **视为严重**，检查 `still_in_offboard` |
| `plan_not_approved` / `operator_id_required_for_real_execution`<br>/ `no_action_executor_configured` | 前置条件不满足 | 修正请求 |

**注**：`action_endpoint_not_implemented` 与 `action_not_supported` 的区别是刻意的。
前者表示"能力合理，只是还没做"；后者表示"本路径不提供该能力"。把后者写成前者，
会误导调用方以为以后可以用。

### 7.1 判定规则（与"HTTP 是否成功"无关）

**HTTP 200 不代表动作成功。** 以下任一情况都判为失败：

- `accepted` 为 `false`
- `result` 为 `"fail"`
- HTTP 状态码 ≥ 400

只看 HTTP 状态码会重现本项目的 RTL 事故：动作返回 `pass`，而载具实际在自主返航。

---

## 8. 完成证据字段（算法侧判断"是否真的完成"必须读这些）

`evidence` 里的字段是 Runtime 从遥测观测到的**事实**，不是命令回执：

| 字段 | 适用 | 含义 |
| --- | --- | --- |
| `arm_result_name` / `takeoff_result_name` / `land_result_name` | takeoff / land | 命令回执，`MAV_RESULT_ACCEPTED` 表示被接受 |
| `completion_reached` | takeoff / land | **遥测确认**已达目标状态 |
| `last_altitude_m` | takeoff | 完成时的实际高度 |
| `mode_confirmed` | goto | PX4 是否**真的**进入 OFFBOARD（不只命令被接受） |
| `arrival_observed` | goto | 是否**持续**落在容差内（不是"某一刻路过"） |
| `arrival_error_m` | goto | 实际三维偏差，米 |
| `restored` | goto | 结束时是否收敛到安全的定点悬停模式 |
| **`still_in_offboard`** | goto | **若为 `true`：载具仍停在 OFFBOARD，属危险状态** |

> 算法侧若只读 `result: "pass"` 而不读这些字段，就无法区分"真做到了"与"命令发了但没动"。
> 这正是 Runtime 把这些字段放进响应的原因。

---

## 9. 算法侧不应做的事

1. **不要自己做 `scene_ned` → `vehicle_local_ned` 的换算。** Runtime 用标定做，两边算必然分歧。
2. **不要假设提案即授权。** 提案只表达意图；每一步仍会被重新评估。
3. **不要依赖未被拒绝就说明动作存在。** 未被拒绝的动作请对照第 3.1 节。
4. **不要宣称几何/安全结论。** 当前输入不含障碍物几何、禁飞区、间距、能源或航迹可行性证明，
   因此**不能**声称"路径直达"、"约束全部满足"。这一点算法侧已在 `FIRST_MODEL_REQUEST_20260928.md`
   中识别并加固，Runtime 侧确认这一约束是必要的。
5. **不要用同一个 `plan_id` 重复提交不同内容。** 审计按 `plan_id` 串联。

---

## 10. 待扩展项（需双方确认后实现）

| 项目 | 状态 |
| --- | --- |
| `HOLD` / `RETURN_HOME` 端点 | 未实现；注册表已声明 |
| `OBSERVE` 端点 | 未实现；需要感知载荷接口定义 |
| `scene_id` / `map_version` 纳入请求并校验 | ✅ **已实现**（2026-09-28，见 5.3） |
| proposal → plan 的转换器 | ✅ **已实现**：`frontend/swarm-console/simulation-3d/tools/proposal-to-plan.mjs`（尚未接 CLI/HTTP） |
| 计划级反馈回调（Runtime → 算法侧推送） | 未实现；当前算法侧需轮询 `GET /api/actions/recent` 或重读计划结果 |

### 转换器（`proposal-to-plan.mjs`）

把提案展开成可提交的 plan。**先全量校验，任一问题就拒绝整份提案**并指出具体的
task / action / waypoint 与原因 —— 绝不静默跳过，也绝不提交"可执行子集"充当原任务。

```js
import { proposalToPlan, ProposalRejected } from "./tools/proposal-to-plan.mjs";

try {
  const { plan, notes } = proposalToPlan(proposal, context, { takeoffAltitudeM: 5 });
  // plan 可直接作为 POST /api/plans/execute 的 plan 字段
} catch (error) {
  if (error instanceof ProposalRejected) {
    return error.toResponse();   // { result:"blocked", failure_reason, detail:{violations} }
  }
  throw error;
}
```

**`takeoffAltitudeM` 必须显式传入**，不从 `context.constraints.min_altitude_m` 推断 ——
那是"允许的最低高度"约束，不是任务要求的高度。

#### 闭环验证脚本

`_ops/run-converter-flight.py`（运维工具，不在仓库内）把整条链串起来：
转换 → 契约校验 → 场景核对 → 执行。

```bash
# 默认：只转换与校验，不提交、不执行
python _ops/run-converter-flight.py

# 真飞（会让 UAV-01 起飞）
python _ops/run-converter-flight.py --execute
```

**安全默认是刻意的**：这个脚本会让飞机起飞，所以"演练"必须是默认、"真飞"必须是
显式选择。早先的版本把提交写成无条件执行，只用一个 `--dry-run` 去跳过提示语，
结果本意只是校验的那次真的让飞机飞了出去 —— 已修正，并把这个教训写在脚本注释里。

**2026-09-28 实测结果**（`simple_recon_v0_1`，UAV-01）：

```
[1] 转换器产出 3 步：takeoff(altitude_m=3) → goto(north=60,east=12,down=-20) → land
[2] 场景核对 ✅
[3] result=completed，三步全 pass，耗时 50 秒
[4] 落在 N=59.2 E=12.0（目标 60/12，误差 0.8 m），已 disarm、高度 0
```

#### 已知的接口事实：算法样例的场景身份与本机不同

算法侧的 `examples/flight_validation_only.json` 用 `scene_id=lab-campus`，
而本机运行的是 `simple_recon_v0_1`。**因此那份样例不能直接在本机执行** ——
提交会被 `scene_id_mismatch` 拒绝。这是校验按设计工作，不是缺陷。

要在本机跑通需要一份与本机对齐的 context（见 `_ops/context-runtime-e2e.json`）。
`tests/unit/test_converter_runtime_interface.py` 里有一条测试专门钉住这个事实：
若算法样例的场景身份哪天变了，测试会失败以提醒更新本节。

---

## 11. 相关文档

| 文档 | 内容 |
| --- | --- |
| `docs/agent_plan_lifecycle_v0_1.md` | 计划生命周期与审批 |
| `docs/agent_planner_v0_1.md` | 模板规划器 |
| `docs/action_capability_registry_v0_1.md` | 动作能力注册表 |
| `docs/frontend_runtime_api_contract.md` | 前端 → Runtime API |
| `algorithm_lab/.../docs/FIRST_MODEL_REQUEST_20260928.md` | 算法侧首次真实推理记录 |
