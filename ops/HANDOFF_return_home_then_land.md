# 交接：`return-home` 之后接 `land`，飞机停在约 10 m 且 `armed=False`

> ## ⚠️ 本文件的诊断已被推翻 —— 结论见下方更正
>
> **2026-10-09 查明**：飞机**不是悬停在空中**，而是**落在了 building-001 的
> 10 m 屋顶上**。
>
> 完整物理证据（ULog + world SDF）：
> [`docs/simulation/RETURN_HOME_LAND_ROOFTOP_20261009_ZH-CN.md`](../docs/simulation/RETURN_HOME_LAND_ROOFTOP_20261009_ZH-CN.md)
>
> **本文件以下内容保留原样**（它记录了当时的观察与我的推测，交接历史有价值），
> 但**两处判断是错的**，读的时候必须带上：
>
> | 我写的 | 实际 |
> | --- | --- |
> | "飞机停在离地约 10 m … 不是下降，是停住" | **是屋顶着陆**。PX4 `dist_bottom ≈ 0.01 m` 与 `building-001` 的 10 m 屋顶碰撞体接触相符 |
> | "推测：`return-home` 进入 `RTL`，与 `land` 冲突" | **冲突不存在**。`LAND` 正常执行：PX4 Commander 的 `VEHICLE_CMD_NAV_LAND` 强制请求 `AUTO_LAND` 并记录 `Landing at current position` —— 在**当前位置正下方**降落 |
>
> **我为什么会误判**：只看了"相对原点高度约 10 m"这一个数，没有对照
> `dist_bottom` 与场景碰撞体。**相对高度单独一个数，不足以判断"在空中"
> 还是"在某个东西上面"。**
>
> **真正的问题在两个别的地方**（都不是本文件原先指的方向）：
>
> 1. **Runtime 的 `return_home` 完成语义过松**（⚠️ 未修）：审计里的
>    `5.039 m` 进度取自"途中 `max_distance` − `final_distance`"，
>    **不是** `28.625 − 23.704`（= 4.922）。它只证明"开始向 home 收敛"，
>    不能证明已到 home。于是 Runtime 在距离刚开始缩短时就报成功，
>    随后的 `LAND` 变成"在当前位置降落"。
> 2. **仿真 standalone 巡逻**把屋顶 `landed` 当成场景地面着陆成功
>    —— 已在 PR #87（`af1136b`）修复：现在要求公共 `scene_ned` 高度
>    在地面 ±0.3 m 内，屋顶会报 `scene_ground_not_reached`。
>
> **另外**：`landing-pad-UAV-0x` 在 world 里只有**视觉**对象（无 collision），
> 承重面是 `ground_plane`。所以"视觉半径 1.5 m"不能当成已验证的安全半径；
> 起降点证据仍需逐机真实着陆验证后才能发布给 Runtime。

**日期**：2026-10-09
**环境**：主仓库 `2475e27`（WORKTREE 无关，仿真从主仓库起）
**仿真**：相机版 `three_uav_mono_cam_sitl.json`，`x500_mono_cam_0/1/2`，RTF 0.82
**Runtime**：`python3 -m uav_runtime.http.server`，独占 14540-14542
**场景**：`simple_recon_v0_1`，标定在每次飞行前用 `sample_calibration.py` 现场发布

---

## 现象

一条动作链，**每个动作都返回 `status=succeeded` / `result=pass`**，
但最后飞机**没有落地**：

```
takeoff        ✅ px4_sitl_action_pass   max_altitude 5.728 m（目标 6，容差 0.3）
goto           ✅ px4_sitl_action_pass   → N=28.7 m
hold-position  ✅ px4_sitl_action_pass   max_drift 0.986 m（容差 3.0）
return-home    ✅ px4_sitl_action_pass   completion_state=converging_on_home
                  initial_distance_m = 28.625
                  final_distance_m   = 23.704      ← 确实收敛（≥ min_progress_m 5.0）
                  **模式变为 RTL**
land           ✅ px4_sitl_action_pass
                  ACK: MAV_CMD_NAV_LAND → MAV_RESULT_ACCEPTED
```

**但随后直连 MAVLink 采样 12 秒**：

```
  0s  10.02 m   N=15.63   armed=False   mode=LOITER
  1s  10.02 m   N=15.62   armed=False   mode=LOITER
  ...
 11s   9.97 m   N=15.61   armed=False   mode=LOITER

高度平均变化 = -0.005 m/s   → 基本静止悬停，不是下降
```

**即：飞机停在离地约 10 m、水平静止、`armed=False`、模式 `LOITER`。**

**没有继续发 `land`**（它刚返回过 succeeded 而飞机没下来，再发是在一个自相矛盾的状态上反复下命令），也没有尝试起飞。

---

## 对照实验：去掉 `return-home` 就正常

同样的环境、同样的动作，**只把 `return-home` 去掉**：

```
takeoff        ✅ max_altitude 5.733 m
goto           ✅ 北 25 m
hold-position  ✅ max_drift 0.594 m（容差 3.0）
land           ✅ MAV_RESULT_ACCEPTED

10 秒后直连采样（两次，间隔 8 秒）：
  UAV-01  armed=False  mode=LOITER  高= 0.02 m
  UAV-01  armed=False  mode=LOITER  高= 0.00 m      ← 稳定在地面
UAV-02 / UAV-03 全程未被触碰（0.03 / 0.02 m）
```

**唯一的差别就是那一发 `return-home`。**

---

## 两次运行的对比

| | 含 `return-home` | 不含 |
|---|---|---|
| 五个动作的返回 | 全部 `succeeded` | 全部 `succeeded` |
| **实际落地** | ❌ 停在约 10 m | ✅ 0.00 m |
| `return-home` 后模式 | **`RTL`** | 未进入 |
| 之后的 `land` | 返回 `succeeded`，**无效** | 正常落地 |

---

## 我的推测（**未确证，不要当结论**）

`return-home` 进入 **`RTL`** 模式，而 **`RTL` 自带"返航 + 自动降落"**。
我在 RTL 执行到一半时插入了一发 `land`。

**可能**是这两者在 PX4 内部冲突，导致 `land` 的 ACK 被接受但飞控没有真正执行下降；
随后飞控自行 disarm，于是出现"已上锁但停在空中"。

**我没有证据**证明这一点 —— 我不知道 PX4 内部如何处理 `RTL` 期间的 `MAV_CMD_NAV_LAND`。
所以我只报告可观察到的部分，把根因留给有权限查的人。

---

## 需要你们判断的

1. **`return-home` 应该进入 `RTL` 模式吗？** 还是应当用别的模式（例如 `AUTO.LAND` 或
   位置设定点下降）？如果契约里对"返航"的模式有规定，这次是否符合？
2. **`RTL` 期间收到 `land` 应该怎样？** 拒绝？排队？还是被接受但被 RTL 覆盖？
   当前的表现是"ACK 接受、实际不动"，这对操作者不友好 —— 它返回成功而没做事。
3. **"`armed=False` 但离地 10 m"这个状态谁来判、怎么处置？**
   现有动作判据里没有覆盖它（`land` 报成功、`not_on_ground_after_land` 也没触发）。
   这看起来是一个判据缺口。
4. **`return_home` 的收敛判据是否过松？**
   这次 `initial 28.625 → final 23.704`，只收敛 4.92 m 就判 `pass`
   （`min_progress_m` 默认 5.0，我显式传了 5.0，实际 4.92 —— 边界附近）。
   而**飞机最终回到的是 N=23.7 而不是 home（N≈0）**。
   "距离缩小了"与"回到 home 了"是两件事，前者被当成了后者。

---

## 复现步骤

```bash
# 仿真（相机版）+ Runtime 起来之后
# ① 现场发布标定（TTL 只有 60 秒，必须先发）
python3 simulation/px4_gazebo/scripts/sample_calibration.py \
  --duration 2 --publish-runtime http://127.0.0.1:8765/api

# ② 依次发（每一步都等它返回）
curl -s -X POST http://127.0.0.1:8765/api/actions/takeoff \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"UAV-01","altitude_m":6,"observe_timeout_ms":30000}'

curl -s -X POST http://127.0.0.1:8765/api/actions/goto \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"UAV-01","north_m":30,"east_m":0,"down_m":-6,"arrival_tolerance_m":2.0,"hold_s":0}'

curl -s -X POST http://127.0.0.1:8765/api/actions/hold-position \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"UAV-01","hold_s":4,"tolerance_m":3.0,"timeout_s":30}'

curl -s -X POST http://127.0.0.1:8765/api/actions/return-home \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"UAV-01","timeout_s":90,"min_progress_m":5.0}'

curl -s -X POST http://127.0.0.1:8765/api/actions/land \
  -H 'Content-Type: application/json' -d '{"node_id":"UAV-01"}'

# ③ 直连 MAVLink 看真实高度（**不要只看动作返回**）
#    UAV-01: udpin:127.0.0.1:14540，读 LOCAL_POSITION_NED 的 -z
```

**注意**：`land` 返回 `succeeded` **不等于**飞机落地。判"是否落地"必须读遥测。

---

## 顺带：一个与本次无关的独立问题

`/api/actions/recent` 里**同一个动作出现多次**：

```
action_id  : act_755094d78099     ← 三条完全相同
request_id : req_e2f080f65e8b
trace_id   : trace_08951391edc1
failure    : return_home_not_converging（相同）
只有 started_at 差几毫秒（03:15:51.176 / .181 / .197）

唯一性: action_id 1 个、request_id 1 个  → **是重复记录，不是重试**（无重复执行风险）
```

根因位置：`src/uav_runtime/http/state_store.py:222`

```python
def record_action_result(self, action, *, limit=50):
    self._actions = (self._actions + [finite_json(action)])[-limit:]   # 无去重
```

**两个后果**：

1. 任何读原始 API 的脚本会把一次动作数成三次 —— 而"动作是否重复执行"正是安全审查的核心问题
2. `limit=50` 的窗口被重复项挤占，**真实历史被提前丢弃**

前端已经自己绕过了（`console-model.js:242` 按 `action_id` 去重），所以**界面看起来正常、原始 API 是脏的**。

---

## 附：本次唯一未验证动作的现状

在此之前 `return_home` 是三机之外**唯一没有真飞验证**的动作。
本次补验**判据通过**（`converging_on_home`，距离确实收敛），
但**留下了上面那个操作序列问题**。

所以 `return_home` 的状态应当记为：
**实现 ✅ / 判据通过 ✅ / 与 `land` 的衔接 ⚠️ 待查**。
不宜记为"完全通过"。
