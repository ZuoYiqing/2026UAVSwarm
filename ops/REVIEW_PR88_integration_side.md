# 对 PR #88（`codex/runtime-return-home-land`）的集成侧核实

**日期**：2026-10-09
**被核实的提交**：`591953d`（`origin/codex/runtime-return-home-land`），Draft PR #88
**核实方式**：独立读代码 + 独立跑测试（不采信报告里的人数）

---

## 结论

**修复方向正确，实现基本扎实。同意"当前不应合并"。**

不建议合并的**核心理由不是"代码有问题"，而是**：合并后
`RETURN_HOME` 会在发送 RTL 前就拒绝（因为缺可信站点证据），
**动作链会从"误报成功"变成"一律不可用"**。这是正确的 fail-closed，
但**需要一个可信的站点证据生产者**才算闭环。

---

## 我独立核实的四项

### ① `return_home` 不再把"开始收敛"当完成 ✅

`routes.py:548` 现在调 `_validated_landing_context(node_id)`，
拿不到就直接：

```python
out = {..., "result": "fail", "accepted": False,
       "execution_admitted": False,
       "failure_reason": "landing_site_unavailable",
       "code": "landing_site_unavailable", "completion_state": "unknown"}
```

**这是正确的 fail-closed**：连 RTL 都不发，并明确报出原因。

### ② `land` 的落点校验 ✅ 且**没有 HTTP 绕过**

```python
routes.py:577    "landing_site": site,            # ← 真实 HTTP 路由确实传了
```

三层都通了：`routes.py` → `px4_runtime_adapter.py`（转发 `landing_site`）
→ `px4_sitl_backend.execute_land_action`（按 `center_scene_ned_m` +
`horizontal_tolerance_m` + `ground_down_m` 算水平/垂直误差判 `on_site`）。

**关键：我专门去找了绕过路径，在 HTTP 上没找到。**

### ③ `/api/actions/recent` 去重 ✅

```python
state_store.py:226-228
    action_id = view.get("action_id")
    if action_id:
        self._actions = [row for row in self._actions if row.get("action_id") != action_id]
```

先移除同 `action_id` 的旧行再追加 —— **修法正确**，而且是我先前那个
"同一条记录存 3 次"问题的根因位置。

### ④ 测试 ✅（但有一处需要更正，见下）

---

## ⚠️ 我独立跑出来的结果与报告不同 —— 已修

报告说"760 passed、11 skipped、1 deselected、0 failed"。

**我从 worktree 跑出来的是 `1 failed`**：

```
FAILED tests/unit/test_converter_runtime_interface.py::test_rejected_proposal_returns_no_executable_plan
```

**根因（就是判断的那个）**：

```python
REPO_ROOT = Path(__file__).resolve().parents[2]
WORKTREES = REPO_ROOT.parent / "2026UAVSwarm-worktrees"
```

`parents[2]` 假设仓库是 `<父目录>/<repo>/`，但 worktree 是
`<父目录>/2026UAVSwarm-worktrees/<name>/` —— **多了一层**，于是算成
`D:\2026UAVSwarm-worktrees\2026UAVSwarm-worktrees\...`。
**从主仓库通过、从 worktree 必失败。**

**我已修根因**（改为向上逐级查找，两种布局都能命中；可用
`UAV_WORKTREES_ROOT` 覆盖）并提交到 main（`c0d218a`）：

```
主仓库                      6 passed
worktree                    6 passed

worktree 全量   766 passed / 6 skipped / 0 failed     ← **不再需要 deselect**
（修前         760 passed / 1 failed / 11 skipped / 1 deselected）
```

**所以那条测试不需要被 deselect 了** —— 而且 skip 数从 11 降到 6，
有 5 条原本被 `skipif` 挡掉的测试现在真正跑起来了。

> 这是共享测试（`tests/unit/`），报告里也写明"主责仍是系统集成"，
> 所以由集成侧修根因比让每个在 worktree 里干活的人各自 deselect 更彻底。

---

## 🔴 我发现的**残留绕过风险**（建议在合并前收掉）

`px4_sitl_backend.execute_land_action` 里保留了这条：

```python
if landing_site is None:
    # Legacy low-level physical LAND result; operator and Agent
    # routes always pass explicit site context.
    result["result"] = "pass"
```

**"真实路由都传了 site context"这个前提我核实了，当前成立。**
但它是一条**靠注释维持的不变量** —— 将来任何人从内部 dispatch
（`px4_sitl_backend.py:956` 那条 `return self.execute_land_action(...)`）
加一条新路径而忘记传 `landing_site`，守卫就被静默绕过，
**而注释不会拦住他**。

**建议**：把默认改成 fail-closed，让"跳过校验"变成**必须显式说明**的选择，例如

```python
if landing_site is None:
    result["result"] = "fail"
    result["failure_reason"] = "landing_site_unavailable"
    result["completion_state"] = "unknown"
```

而把真正需要旧行为的调用方改成显式传 `landing_site={"legacy_low_level": True}`
之类的明示参数。

**优先度**：中。当前不可利用，但它把"安全判据"变成了"取决于调用方是否记得"。

---

## 关于"可信证据生产者"——**我认为安全审查拒绝那个 HTTP 写入是对的**

报告提到自动安全审查拒绝了"通过 HTTP 发布 validated 着陆面证据"的补丁，
理由是端点没有来源认证、调用方可伪造 `real_landing` / `run_id`。

**这个拒绝是正确的，而且值得记下来**：那条路径会让**任何能访问
`127.0.0.1:8765` 的人**把"这块地已验证可降落"写进去，
从而影响飞行成功判定。**在一个把"不编造成功"当硬规矩的项目里，
开这样一个口子比暂时 fail-closed 危险得多。**

**所以"RETURN_HOME 现在一律拒绝"不是缺陷，是当前唯一诚实的行为。**

---

## 站点证据的获取路径（我的建议）

仿真侧已经给出了提案的形状，我认为可以直接用：

```
scene_id / map_version / world hash / object_id / node_id /
中心（scene_ned）/ visual_radius / collision_surface(ground_plane z=0) /
候选容差 / valid|status / 证据时间
```

**关键取舍**（报告里的判断我同意）：

* **不把静态站点位置塞进 60 秒 TTL 的动态 calibration payload** ——
  两者的生命周期完全不同，混在一起会让"站点"随标定过期
* **`valid=true` 必须来自"静态几何核对 + 真实落地验收"两件事都做过**
* **`valid` 未置位时，Runtime 必须拒绝"已在指定起降点"这一任务完成声明**
* **UAV-02/03 不能复用 UAV-01 的中心**（`(0,+8,0)` / `(0,-8,0)`）
* **`landing-pad-UAV-0x` 在 world 里只有 VISUAL、无 collision** ——
  真正承重面是 `ground_plane` 的 `z=0`。**所以"视觉半径 1.5 m"不能称为
  已验证的安全半径**，仿真侧建议的 ≤0.75 m 中心容差是**待验证提案**

**依赖链**：Simulation 产出并签署站点证据 → Runtime 消费并 fail-closed
→ 集成侧安排独占三机窗口做真实联调。

---

## 我建议的下一步顺序

| # | 事项 | 归属 |
| --- | --- | --- |
| 1 | 把 `landing_site is None → pass` 改成 fail-closed（显式 opt-in） | Runtime |
| 2 | 站点证据的**可信生产者**（含来源与有效期，不经未认证 HTTP 写入） | Simulation |
| 3 | `landing-pad` 加 collision，或明确"承重面是 ground_plane"并据此定容差 | Simulation |
| 4 | 逐机真实着陆验收 → 才能置 `valid=true` | Simulation + 集成 |
| 5 | 独占三机窗口的真实联调（含 UAV-02 起飞—保持—落地与隔离性） | 集成 |
| 6 | 之后才谈合并 PR #88 | 集成 |

**在 1~4 之前合并 PR #88，会把 `RETURN_HOME` 从"误报成功"变成"一律不可用"** ——
那不是回归，但也还不是可用状态，而且没有证据链支撑它变可用。
