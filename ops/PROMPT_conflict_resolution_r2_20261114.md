# Task: merge #97 into the demo version (r2) — resolve the conflicts yourself

**For**: Runtime lead
**Date**: 2026-11-14

冲突位置你自己找得到。这份文档只写**你从 diff 里看不出来的东西**：几个一旦解错、
测试还可能是绿灯的坑，以及验收标准。

---

## 1. 起手

```bash
git fetch origin --tags

# 从已验证的 demo 组合开工（已含 #98 #99 #100，这个提交上 936 passed / 12 skipped）
git checkout -b integration/demo-20261113-r2 origin/integration/demo-20261113

git merge --no-ff origin/codex/runtime-platform-autonomy \
  -m "integration: merge runtime platform autonomy (#97) into demo version"
```

**结果是 3 个文件、9 处冲突**：`routes.py`(3)、`server.py`(5)、
`mavlink_backend_session.py`(1)。位置自己定位。

**不要先 rebase #97 到 main。** 集成分支已经带着三条 demo 线，合 #97 是
一次合并、一套冲突、一轮测试；先 rebase 会变成两套冲突。

---

## 2. 五件从 diff 里看不出来的事（**这一节是重点**）

### 2.1 `matched_source` 被下面的代码直接用，丢了不会报错

冲突处一个是赋值 `matched_source = (...)`，另一个是 `self._health_sample_sources[kind] = (...)`。
看起来"选一个"就行，但下面几行有：

```python
if kind == "HEARTBEAT":
    if matched_source:
        self._link_heartbeat_at = received_monotonic
```

**丢了 `matched_source`，心跳时钟永远不前进 → 链路评分恒为 0 或永远 stale。**
这种错编译不报（模块级 if 里用未定义名要到运行时才炸），测试也可能碰不到。
**两个都要，赋值在前。**

### 2.2 demo 的 `127.0.0.1` 限制是安全属性，不能因为合并丢掉

`server.py` 里 demo 侧那半把 `/api/demo/` 的 POST 限定为
`self.client_address[0] == "127.0.0.1"`；#97 那半只查 Origin。

**演习注入是能改变界面显示的操作，必须在本地才允许触发。** 合并后这个限制要保住。
**另外**：冲突块外面有一个共享的 `return`，解完要检查控制流 —— 每个拒绝分支都要
有一个可达的 `return`，不能有走不到的死代码。

### 2.3 `vehicle_snapshot()` 的顺序，以及 `merge_projection` 返回的是什么

demo 侧：取本地快照 → 套 DEMO 的 `link_quality` 覆盖（带 `link_quality_mode="DEMO"`）
#97 侧：`_merge_platform_view(...)` 把平台节点合进投影

**两者都要**，建议先平台合并、再套 DEMO 覆盖。但有个**必须确认**的点：

> `merge_projection(local, platform_view, key)` 返回的是**新建的 dict**，
> 还是**平台缓存对象本身**？

如果是后者，`vehicle.update(...)` 会**就地改掉平台缓存**。
这种情况要 deep-copy 再改。这个错跑测试很可能发现不了，但会让平台侧视图被污染。

### 2.4 `main()` 里两个注册表名字可能不是同一个对象

demo 侧写 `VEHICLE_REGISTRY.start_all()`，#97 侧写 `registry.start_all()`。

**先确认合并后的文件里这两个名字指向同一个对象。** 如果不是，两个调用都得留；
如果是同一个，留一个但别把 `leases` 那段丢了（它管 TransportLease）。

### 2.5 `finally` 必须镜像 `startup`，漏一个 `lease.close()` 就泄漏端口

启动多了 `leases` / `gateway`，清理就必须对应上：

```
demo.close() → gateway.close() → *.stop_all() → lease.close() → server.server_close()
```

漏了 `lease.close()`，UDP 端口不释放，下一次起就 `address already in use` ——
正是 S4（起停可靠性）要防的那类问题。

---

## 3. 验收标准（把你的输出贴进报告）

```bash
# ① 无冲突残留（连注释里的都不该有）
grep -rn '^<<<<<<<\|^=======$\|^>>>>>>>' src/ tests/ && echo "FAIL" || echo "OK"

# ② 全量回归，不能低于基线
PYTHONPATH=src python3 -m pytest -q
#   基线：936 passed, 12 skipped, 0 failed

# ③ 语法/缩进没被破坏
python3 -m compileall -q src/uav_runtime && echo "compileall OK"
```

| 项 | 要求 |
|---|---|
| 冲突残留 | 零 |
| 全量 pytest | **≥ 936 passed, 0 failed** |
| #97 自带测试 | 全过 |
| compileall | 干净 |

**如果某处冲突逼得你要改测试才能过，停下来报告，不要改测试去迁就代码。**
那说明行为变了，需要决策，不是一次静默修复。

---

## 4. 报告里对每处冲突写三句话

1. 保了哪边（或两边）
2. **为什么**（你依据的语义）
3. 有没有不能干净合并、你做了取舍的地方

例：
```
server.py POST origin   保两边   demo 的 127.0.0.1 限制是安全属性
main() 启动             保两边   VEHICLE_REGISTRY 与 registry 是同一对象，只调一次， leases 保留
mavlink session         保两边   matched_source 被下方 if 使用，丢了心跳不前进
```

**每处一句理由，是我验收合并的依据。**

---

## 5. 通过之后

```bash
git push -u origin integration/demo-20261113-r2
```

然后我上 weier 做现场验收。**测试绿不是终点** —— #97 自己注明"未飞行、
未加载模型和前端"，11 条现场验收才是标准。

---

## 6. 不要做

- ❌ 不要先 rebase #97 到 main
- ❌ 不要对这三个文件整文件 `--ours` / `--theirs`
- ❌ 不要删 `matched_source`、`127.0.0.1` 检查、`lease.close()`
- ❌ 不要为了让测试过而放宽断言
- ❌ 做这个的时候不要往同一分支再合别的东西

---

## 7. 顺手该清的（与本任务无关，但欠着）

`runtime-action-lifecycle` 工作区里有 **69 个未跟踪的 `.tmp_runtime_*` 目录**
（实测其中 0 个 `.py`，都是草稿）：

```bash
git status --porcelain | grep '^??' | grep '\.tmp_runtime' | wc -l   # 应为 69
git clean -fdn -- '.tmp_runtime_*'                                   # 先 dry-run
git clean -fd  -- '.tmp_runtime_*'                                   # 再执行
```

另外这个**目录名和它的分支不一致**（`runtime-action-lifecycle` vs
`codex/runtime-platform-autonomy`）。r2 落地后统一清 worktree 时，**必须用
`git worktree remove <path>`，不要 `rm -rf`** —— 否则 `.git/worktrees/` 留脏元数据。
