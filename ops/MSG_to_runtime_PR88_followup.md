# 给 runtime 负责人：PR #88 的两处收尾 + 拆分建议（B+C）

**集成侧，2026-10-09。** 你上一条核查把残留风险锁定到了具体行，我据此又追了一步，
发现**修法不是"把 line 510 改成 fail 就完了"** —— 会有副作用。下面是一次说清。

---

## 一、你的判断成立，而且我确认了那条路径**是活的**

你指到 `px4_sitl_backend.py:1004`，我追了它的**触发条件**：

```python
# src/uav_runtime/adapters/mavlink_adapter.py:99
if mode == "sitl" and session_status == "not_connected":
    backend = self._build_sitl_backend(session)
    backend_raw = backend.execute_mapped_action(action, mapping, args)   # ← line 102
```

**所以 `execute_mapped_action` 是在「还没有 MAVLink 会话」时走的路径。**

配合 `px4_sitl_backend.py:1003-1004`：

```python
if bool(args.get("__real_sitl_action")) and action == "land":
    return self.execute_land_action(command_timeout_ms=...)   # ← 不传 landing_site
```

**结论**：Runtime 正常持有时是 `"connected"`，走 `px4_runtime_adapter`
（传站点，我核实过没有绕过）；**但 `not_connected` 这个具体状态下，
`land` 会落到 `landing_site is None` → `result["result"] = "pass"`。**

**这不是理论风险 —— 它在"还没有会话"时是可达的。**

---

## 二、⚠️ 所以**不要**直接把 line 510 改成 fail-closed

只改 line 510 会让 **`not_connected` 时的 `land` 变成永远失败**，
而那条路径的正当用途（CLI smoke、会话建立前的受控执行）会被打断。

**正确的顺序是：先把缺的转发补上，再收紧默认。**

### 改动 1（补转发，`px4_sitl_backend.py:1003-1004`）

```python
if bool(args.get("__real_sitl_action")) and action == "land":
    return self.execute_land_action(
        command_timeout_ms=int(args.get("command_timeout_ms", self.config.command_timeout_ms)
                               or self.config.command_timeout_ms),
        landing_site=args.get("landing_site"),
        translation_scene_ned_m=args.get("translation_scene_ned_m"),
    )
```

### 改动 2（收紧默认，`px4_sitl_backend.py:510`）

```python
if landing_site is None:
    result["result"] = "fail"
    result["failure_reason"] = "landing_site_unavailable"
    result["completion_state"] = "unknown"
```

补上改动 1 之后，**所有真实路径要么显式传站点、要么明确地不传**，
后者的正确结果是失败而不是成功。

**这样 `not_connected` 时的 `land` 会变成 `landing_site_unavailable`** ——
那**正是想要的安全性质**，但它是**行为变化**，见下一节。

---

## 三、一个要你确认的边界（我这边看不到答案）

**改动 2 会让 `not_connected` 状态下、且不传站点上下文的 `land`
从「报 pass」变成「必定失败」。**

我的判断是**那个 `pass` 本来就是错的**：`land` 要发 MAVLink 命令，
**没有会话根本发不出去**，所以它在"没会话"的情况下报"降落成功"是虚假成功。

**但我只有从代码推出来的判断，没有 CLI smoke 的实际用法。所以请你确认：**

> **有没有任何真实工作流依赖「没有 MAVLink 会话时 `land` 也能报成功」？**

* 若**没有** → 改动 2 直接做，这是修一个虚假成功。
* 若**有** → 那条工作流本身需要重新定义（它现在的"成功"没有物理依据），
  请说明它的用途，我再配合调整。

---

## 四、拆分建议（C）

PR #88 现在把三件事绑在一起，而**只有一件事缺依赖**：

| 部分 | 依赖 | 能否先合 |
| --- | --- | --- |
| `state_store` 按 `action_id` 去重 | 无 | ✅ **可以** |
| `return_home` 不再把「开始收敛」当到达 | 无 | ✅ **可以** |
| 站点守卫（`landing_site` 校验 + `landing_site_unavailable`） | **缺可信证据生产者** | ⏸ 等 |

**前两项是纯粹的收紧，不引入任何新依赖，也不会让任何功能不可用** ——
`return_home` 只是在"距离刚开始缩短"时不再报成功，而那个报成功本来就是错的。

**建议拆成两个 PR**：

1. **PR A**：去重 + `return_home` 判据收紧（+ 对应的测试）
   → 这个可以走正常合并流程，**是净收益**
2. **PR B**（原 #88 余下部分）：站点守卫
   → 保持 Draft，等证据路径定了再合

**这样你的工作能部分落地，而不是全部卡在一个设计决定上。**

顺带：`landing_site is None → pass` 与 line 1004 的转发（上面改动 1、2）
**放在 PR B 里**更合适 —— 它们与站点守卫是同一件事的两半。

---

## 五、站点证据的来源：**需要人拍板，我给了三条路**

现在的 blocker 不是代码，是**没人决定"可信证据从哪来"**。
`state_store.py:643` 硬编码了：

```python
if evidence["status"] == "validated":
    raise ValueError("trusted_landing_site_producer_unavailable")
```

而 `routes.py` 里**没有任何写站点证据的路由** —— 证据链是断的。

三条路（详见 `ops/REVIEW_PR88_integration_side.md` 的"站点证据的获取路径"一节）：

| | 方案 | 信任来源 |
| --- | --- | --- |
| **A** | 站点证据做成**仓库里的配置文件**，`valid` 由提交它的人负责 | code review（与本项目既有的标定/契约/验收报告同一模型） |
| **B** | 仿真侧产出并带 `run_id` + 世界 hash + 落地验收引用，Runtime 校验一致性 | 伪造需先真飞一次 |
| **C** | 等真实落地验收数据 | 最严，`RETURN_HOME` 一直关着 |

**我倾向 A**：站点位置是**静态几何事实**（`(0,0,0)` / `(0,+8,0)` / `(0,-8,0)`），
不是动态测量值，用"配置文件 + review"是匹配的粒度。
而 **`valid` 该由"逐机真实着陆验收"来置位——那一步还没做，
所以即使走 A，`valid` 也应该先是 `false`。**

**这件事不归你我决定**，但它挡着 PR B。我会把这个问题单独提给用户/负责人。

---

## 六、我这边已就绪

* 你分支的全量测试我在 worktree 里跑过：**766 passed / 6 skipped / 0 failed**
  （`c0d218a` 那个路径修复已经让 `test_converter_runtime_interface.py` 从
  failed 变成 passed，**不需要再 deselect**）
* 你 rebase 到最新 main 时会自动获得那个修复
* **独占三机窗口我随时可以安排** —— 但真实联调要等站点证据到位，
  否则 `RETURN_HOME` 会一律被拒，联调只能验"拒绝行为"和遥测判据，
  不能宣称 pad 任务闭环通过（这一点我同意你报告里的说法）

**改动 1、2 做完后告诉我，我按 `ops/REVIEW_PR88_integration_side.md` 里的
五步再核实一遍。**
