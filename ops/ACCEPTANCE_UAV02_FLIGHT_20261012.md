# 联合实飞验收报告（2026-10-12，集成侧）

**执行方：集成侧。** 被测版本：`acceptance-88-92-fresh-20261011` @ `78ea4e2`
（含 Runtime `#88 f4a51b8` 与 Simulation `#92 fbbad1d`，**未合并 main**）。

**UAV-02 实飞，UAV-01/03 全程未动。真实 Gazebo/PX4，相机版 manifest。**

---

## 0. 结论

| # | 要验的 | 结果 |
| --- | --- | --- |
| 1 | **「落在非地面不能报成功」** | ✅ **通过** |
| 2 | **「距离缩短 ≠ 到达」** | ✅ **通过** |
| 3 | **三台隔离** | ✅ **通过** |
| 4 | **`goto` 到达语义** | ⚠️ **未通过，原因未定** —— 单独列在第 4 节，**不阻塞合并** |

**三台最终状态**：全部 `armed=False`、`landed_state=1`(on_ground)。
UAV-02 回家水平精度 **0.088 m**。

---

## 1. ✅ 落地判据：完整成立（含地面高度检查）

**这是"屋顶假成功"那处修复的直接验证。**

```json
"result": "pass"                     "completion_state": "succeeded"
"completion_mode": "scene_ground_landed_disarmed"
"failure_reason": null

"physical_landed_disarmed": true     landed_state_name: "on_ground"
"landed_state": 1                    armed: false

"ground_check": {
    "scene_position_ned_m": { "north": 0.0058, "east": 8.0182, "down": 0.0095 },
    "vertical_error_m":     0.009510,     ← 与地面仅差 9.5 毫米
    "in_reference_bounds":  true,
    "on_scene_ground":      true,         ← 关键
    "ground_down_m":        0.0,
    "vertical_tolerance_m": 0.3
}
"ground_stable_samples": 5
"ground_stable_ms":      550
"ground_reference": { "surface_id": "ground_plane",
                      "world_sha256": "9086de5bea22ae0470fe76f6b06cf9e73b6ac9bdf96477c2171ae304a7b575fa" }
"site_completion": { "state": "not_requested" }
```

**三方那三项分解逐条对上**：

| 三方要求 | 实测 |
| --- | --- |
| 完成需 `landed` + `disarmed` | ✅ |
| **还需站点位置 + 地面高度 + 持续新鲜样本** | ✅ `vertical_error_m=0.0095`、5 样本、550 ms |
| 普通 LAND 无须指定站点 | ✅ `site_completion: not_requested` |

### 1.1 缺证据时的 fail-closed 也实测到了

同一动作在**标定过期**时（`ground_reference` 拿不到）：

```json
"result": "fail"        "status": "failed"
"failure_reason": "ground_reference_unavailable"
"completion_state": "unknown"
"physical_landed_disarmed": true     ← 如实记录"物理上确实落地了"
"completion_reached": false          ← 但**不报任务完成**
```

**"物理落地"与"任务完成"被分开，且缺证据时不猜。** 这正是要求的行为。

---

## 2. ✅ 返航判据：「距离缩短 ≠ 到达」实测通过

```json
"reason":              "arrived_at_home"
"initial_distance_m":   6.751140153691969     ← 飞机**真的离开了 home**
"final_distance_m":     0.36155987756345076
"distance_reduction_m": 6.547408379832944     ← 缩短了 6.55 m
"min_progress_m":       5.0                   ← **老判据恰好也会满足**
"arrival_samples":      10
"home_tolerance_m":     0.75
"completion_goal":      "px4_home_horizontal_arrival"
"autonomous_execution_may_continue": true
```

**⭐ 关键在于"老判据也会通过"**：`distance_reduction_m (6.55) > min_progress_m (5.0)`，
**如果判据没换，这次同样会报成功——而它报了成功是因为 `arrival_samples=10` 落在 0.75 m 容差内。**

**这是比"飞机本来就在 home"那种空过强得多的证据。**

### 2.1 三方要求的 HOME / RTL 核验也在生效

```json
"home_evidence": {
    "verified": true,
    "verification": "global_local_xy_crosscheck",   ← 用独立方法交叉核对
    "crosscheck_error_m": 0.009446,                 ← 9.4 毫米
    "x": 0.0535, "y": -0.0408, "z": 0.0078,
    "latitude": 473979710, "longitude": 85462697
}
"rtl_destination_evidence": {
    "verified": true,
    "rtl_type": { "param_id": "RTL_TYPE", "param_value": 0.0 },   ← 真读了参数
    "rally_points": { "mission_type": 2, "count": 0 },            ← 无 rally 点
    "failure_reason": null
}
"landing_site_id": null
```

**PX4 日志印证了完整链路**：

```
INFO [commander] Takeoff detected
INFO [navigator] RTL: start return at 15 m (15 m above destination)
INFO [navigator] RTL: land at destination
INFO [commander] Landing detected
INFO [commander] Disarmed by landing        ← 回家→降落→上锁全自动
```

---

## 3. ✅ 三台隔离

全程快照：**UAV-01 / UAV-03 始终 `armed=False`、`landed_state=1`、位置几乎未变**
（距各自 home 1.30 m / 0.015 m）。仅 UAV-02 执行动作。

---

## 4. ⚠️ `goto` 未通过：到了 2.9 m 又漂到 37 m（原因未定）

```json
"status": "timed_out"       "failure_reason": "arrival_timeout"
"samples": 217
"min_error_m":  2.9112001939717422      ← 到过离目标 2.9 m
"last_error_m": 36.97063104144499       ← 最后差 37 m
"target_scene_ned_m": { "north": 15.0, "east": 0.0, "down": -3.0 }
"stream_setpoints": 257    "stream_errors": 0      ← setpoint 流本身无错
"mode_confirmed": true     "observed_main_mode": 6  ← OFFBOARD 确实进去了
"restored": { "restored": true, "observed_main_mode_name": "AUTO_LOITER" }
```

### 4.1 几何还原

```
RTL 日志: "start return at 15 m (15 m above destination)"   → goto 结束时高度 ≈ 15 m
返航起点距 home: 6.75 m                                     → 水平 ≈ (N=8.25, E=0)
```

**即 goto 结束时飞机在 (N≈8.25, E≈0, alt≈15 m)** ——
**水平离目标（N=15, E=0, alt=10）只差 6.75 m，而"37 m 误差"的绝大部分是垂直的（15 vs 10）。**

### 4.2 三个候选原因，现有数据无法区分

| # | 候选 | 支持 | 反对 |
| --- | --- | --- | --- |
| 1 | **目标高度未被跟踪**（停在 15 m 未降到 10 m） | 日志 `start return at 15 m` | — |
| 2 | **GCS 心跳中断致 OFFBOARD 退出**（PX4 要求 OFFBOARD 期间持续有 GCS 心跳） | 日志两次 `Preflight Fail: No connection to the GCS`；动作返回后 Runtime 不再发心跳 | — |
| 3 | ~~setpoint 流中断~~ | — | **`stream_errors: 0` 否掉了** |

### 4.3 ⚠️ 本轮没能拿到 `goto` 的详细证据

`/api/actions/recent` 里那条 goto 是**上一轮**的（`act_7876327526ba`），
`observations` 只有 `max_altitude_m` 与 `threshold_reached`；**本轮那条未出现在 recent 中。**

**建议下一步**：重跑一次 `goto`，用**独立只读**方式记录高度/位置曲线
（不抢 Runtime 的 14540-14542），并确认 `goto` 结果是否进入 `recent`。
**若 `recent` 会丢最新动作，那本身也是一个要修的问题。**

### 4.4 但它**不阻塞合并**

本轮修复的目标是「**不报假成功**」，而 `goto` **做到了诚实**：

```
报的是 timed_out / fail —— 没有谎报到达
```

**那个 37 m 是控制精度问题，不是诚实性问题。**

---

## 5. 我这轮犯的三个错（都已修，记录于此）

| # | 错误 | 后果 | 修法 |
| --- | --- | --- | --- |
| 1 | 测试脚本**漏了 `cd` 到验收目录** | 三次"发标定"静默失败（`can't open file .../2026UAVSwarm-worktrees/simulation/...`）→ `goto` 被拒 `coordinate_calibration_unavailable` | 加 `cd`，且**目录不对就硬停** |
| 2 | `publish_calib` **只报"标定读取失败"不报原因** | 我一度误以为标定流程本身有问题 | 改为**非零退出或非 PASS 就停并打印 stderr** |
| 3 | 用 `/api/vehicle-snapshot` 查位置 | 读到 `{}`，误判"遥测缺失" | **改用 `/api/telemetry/latest`** —— `nodes` 里才有 `local_position`(含 `altitude_m`)、`velocity_mps`；`snapshot` 的 `telemetry` 只有 6 个键 |

**另有两处观察**（不是错，但值得三方确认）：

* `goto` 被拒时返回 `execution_admitted: false` 而 `policy_decision.decision_code: "allow"`。
  语义上说得通（策略管权限、标定管可执行性），**但并列时容易被误读成"策略允许却被拒"**。
* **`mode=LAND` 时 PX4 拒绝解锁**（本轮实测触发：起飞 `timed_out`、`max_alt 0.0`，
  而 UAV-02 处于 `mode=LAND`）。**只能重起仿真** —— Runtime 没有切模式的代码（设计如此）。
  测试流程应加"动作前先查 mode"。

---

## 6. 合并建议

| | 事项 | 依据 |
| --- | --- | --- |
| 1 | **#92 先合**（`fbbad1d`） | #88 的落点判据依赖它的 `ground_reference`；只合 #88 会缺地面参考 |
| 2 | **#88 后合**（`f4a51b8`） | 本轮已验到核心两处修复 |
| 3 | **`goto` 作为待查项**，不阻塞 | 见 4.4 |
| 4 | 建议加 `.gitattributes`（`*.sh text eol=lf`） | 验收 worktree 的 `.sh` 是 CRLF，导致 `set: pipefail: invalid option name`、仿真完全起不来（症状会误导成"别的坏了"） |
| 5 | **B 已验证**（0/8/30 秒） | 见 `ops/ACCEPTANCE_B_0_8_30_RESULT.md` |

---

## 7. 本轮操作边界

* 未修改任何负责人分支的代码
* 只把验收 worktree 里两个 `.sh` 的**行尾**转为 LF（内容未变，`git status` 干净）
* **未合并、未推送任何 PR**
* 全部状态查询走只读接口，**未抢 Runtime 的 14540-14542**
* 结束时系统全部停止
