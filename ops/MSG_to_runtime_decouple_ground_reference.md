# 给 Runtime 负责人：请把静态 `ground_reference` 从 health 的 TTL 里解耦（B）

**集成侧，实测发现，2026-10-12。**
**只做验证与报告，未改任何代码、未合并、未发飞行命令。**

---

## 0. 一句话

**`ground_reference` 是静态几何，却被"health 信封收到多久了"这个时钟判掉了。**
实测同一系统、同一条命令，**发布后立刻 `ready`，8 秒后 `not_ready`**。

**这使手动验收无法进行** —— 不是代码错，是 TTL 绑错了对象。

而三方讨论里其实**已经达成过正确结论**，只是没落到代码：

> 站点几何与着陆能力**都不按时间失效**（分别跟 `map_version` 和软件版本走），
> 按时间失效的只有"当前是否允许使用"。

---

## 1. 根因（精确到函数与行）

`src/uav_runtime/http/state_store.py` → `ground_landing_context()` 的**第一道门**：

```python
with self._lock:
    evidence = copy.deepcopy(self._simulation_evidence)
    received = self._simulation_evidence_received_at
if not evidence or received is None or \
   self._monotonic() - received > evidence["valid_for_ms"] / 1000.0:
    return None                    # ← 收下超过 valid_for_ms 就整段作废
```

**实测那个 TTL**：

```
GET /api/simulation/status
  evidence_valid_for_ms : **4913 ms**       ← 不到 5 秒
  evidence_age_ms       : 178849            ← 178 秒前发布
  evidence_fresh        : false
```

**而它放行的对象是静态几何**（`docs/simulation/fixtures/ground_reference_simple_recon_v0_1.json`）：

```json
{
  "contract_version": "1.0",
  "kind": "horizontal_plane",
  "ground_down_m": 0.0,
  "surface_id": "ground_plane",
  "frame": "scene_ned",
  "source": "world_collision_geometry",
  "world_sha256": "9086de5bea22ae0470fe76f6b06cf9e73b6ac9bdf96477c2171ae304a7b575fa",
  "world_sha256_scheme": "sha256-lf-v1",
  "xy_bounds_m": { "north_min_m": -1000.0, "north_max_m": 1000.0,
                   "east_min_m": -1000.0,  "east_max_m": 1000.0 }
}
```

**这里面没有任何一个字段会随时间变。** 它绑的是 `world_sha256` 与 `map_version`。

---

## 2. 实测证据（可复现）

### 2.1 发布后立刻 → ready

```
# 取遥测 → 发布 integrated health → **立刻**查 preflight
GET /api/preflight?node_id=UAV-02

status                   : **ready**
execution_authorized     : false
flight_command_sent      : false          ← 只读预检，无飞行副作用 ✅
home_evidence            : {sequence: 74953, x: -0.00106, y: -0.00680, z: -0.05178,
                            latitude: 473979706, longitude: 85462698, ...}   ← **真读到了**
evidence_age_ms          : 47
```

### 2.2 → 8 秒后 → not_ready

```
status        : **not_ready**
reason_codes  : ["ground_reference_unavailable", "home_or_rtl_not_checked"]
home_evidence : null
```

**同一个系统、同一条命令，唯一变化是过了 8 秒。**

> `home_or_rtl_not_checked` 也随之出现 —— 说明 `ground_context` 拿不到时，
> HOME/RTL 那一项也一并没检查。**两项是串在一起的。**

### 2.3 为什么"手动测试"这条路是堵的

```
点"起飞"前要 preflight ready
  → ready 要求 ground_reference 新鲜（< 4.913 秒）
  → 而发布一次 integrated health 本身要采样 clock + models，约 4.5 秒
  → **人手操作赶不上这个窗口**
```

---

## 3. 建议的修法（供讨论）

**把两件事分开：**

| | 是什么 | 该怎么判 |
| --- | --- | --- |
| **A. 信封的接收新鲜度** | clock / models / clock_advancing 这些**动态**量 | 保留现有短 TTL（它们确实会变） |
| **B. `ground_reference` 本身** | **静态**几何，绑 `world_sha256` + `map_version` | **按版本绑定判定，不按墙钟过期** |

**具体到代码**：在信封有效时把它**存成独立的、按版本键绑定的对象**，
`ground_landing_context()` 改为校验它的绑定关系（scene / map / world_sha256 /
contract / kind / frame / source），而**不再要求"信封是刚收到的"**。

**已经做对、应当保留的部分**（`ground_landing_context` 里其余检查都很扎实）：

* 要求本机 `calibration` 已 `calibrated`（`status != "calibrated"` → None）
* 要求 `clock_advancing is True`、`world.status == "ready"`、
  本机 `models[].status == "ready"`
* 要求 `reference.scene_id`/`map_version` 与 calibration **及** evidence 双向一致
* 要求 `world_sha256` 是字符串

**所以这不是"放宽门"，而是"把门开在正确的维度上"**：
从"你多久之前告诉我"改成"你告诉我的世界还是不是这个世界"。

> ⚠️ 那个 docstring 写着
> `Re-reading an expired health file must not refresh its source age.`
> —— 那条**应当保留**：它防的是"反复读旧文件把年龄刷新成新的"。
> 本次要改的是**另一件事**：静态对象不该以信封年龄为存在前提。

---

## 4. 需要 Simulation 配合的部分（请一并考虑）

`health.py` 把 `ground_reference` 放进 `runtime_evidence` 里，
**与动态证据共用同一个 `valid_for_ms`**。若 Runtime 侧改成版本绑定，
**生产侧是否要给它一个独立的、更长的有效期**，还是干脆由 Runtime 从
**随 world 版本发布的 fixture** 读取？两种都行，但**要有一致的约定** ——
否则又会出现"一边按 5 秒、一边按版本"的分歧。

**我倾向"Runtime 从版本化 fixture 读静态部分 + 从 health 读动态部分"**：
· 静态：随 `world_sha256` 发布，`valid` 与否看版本是否匹配
· 动态：仍走 health 的短 TTL
这样两边的生命周期各自自洽，不需要谁去改谁的 TTL。

---

## 5. 这轮"不能合并"的现状（供参考）

| 项 | 状态 |
| --- | --- |
| #92 `fbbad1d` | 已修 world hash（CRLF/LF），`.gitattributes` 已在；我实测两个 checkout 的 world 哈希一致 |
| #88 `f14e7ce` | 领先 main 7 个提交；**main 上完全没有** `scene_ground_not_reached` / `ground_reference` / `home_arrival` / `RTL_TYPE` |
| `ground_reference` 是否发布成功 | ✅ **成功**，`world_sha256` 与仓库一致 |
| `home_evidence` | ✅ **能读到真实 HOME_POSITION** |
| 在线 RTF | ✅ 带 `MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA` 后 **0.688 → 0.903 → 0.942**（之前 0.1787/0.1915） |
| **preflight** | ⚠️ **只在证据发布后 < 4.913 秒的窗口内 ready** ← 本文要解决的问题 |

**两处修复的价值我确认过了，没有异议**；`GET /api/preflight` 那个只读预检
（`flight_command_sent: false`）设计得对，正是需要的东西。

---

## 6. 我不建议做的事

* **不建议降 `minimum_real_time_factor` 阈值** —— RTF 低是启动少了个环境变量，不是性能不足（带变量后 0.94）
* **不建议为了验收而延长 health 信封的 TTL** —— 那会把"动态证据的新鲜度"一起放宽，方向错了
* **不建议开一个"每 5 秒重发 health"的循环发布器来绕过** —— 那只是掩盖绑定错误，验收本身仍然不可复现

**把静态对象按版本绑定，是唯一既正确又能让验收跑起来的路。**

---

## 7. 我这边可以随时配合

* 系统当前**全部停止**（PX4 0 / Gazebo 0 / Runtime 0，端口全空）
* 起系统、发布证据、跑只读 preflight 的脚本都在 `_ops/`（我会在你们改完后重跑验证）
* 改完后我会按"发布后 30 秒再查 preflight 仍应 ready"来验证 —— **那才是这条修复的真正判据**
