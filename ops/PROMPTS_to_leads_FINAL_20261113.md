# 给三位负责人的任务书 · 最终版（第二阶段）

**日期**：2026-11-13
**取代**：`PROMPTS_to_leads_demo_20261112.md`（第一版，F1~F7 / R1~R5 / S1~S4 已全部交付）
**背景**：第一阶段的 17 项任务三位都交了，三条线已合并成一个可复现版本并跑通全量测试。
**这一版只写"还没做完的"和"共同要守的规矩"，不再重复已完成的内容。**

---

# 〇、先看这个：现在到哪一步了（都是 git 里的事实）

## 已固定的版本

| 项 | 值 |
|---|---|
| **标签** | **`demo-20261113`** |
| 分支 | `integration/demo-20261113` |
| 提交 | `421aa27`（合并提交） |
| 基线 | `main`（当时 `d60f74f`） |
| 内容 | **#98 `914b042` + #99 `74750f1` + #100 `3d5d5e4`** |
| 相对 main | 34 files changed, **+3340 −322** |
| **组合验证** | **全量 pytest：936 passed, 12 skipped, 0 failed**（225 秒） |

> ⚠️ **注意 #100 用的是 `3d5d5e4`，不是 PR 描述里的 `ee75534`。**
> `3d5d5e4` 是分支最新提交（`expose LIVE stage and prevent twin panel overlap`），比 `ee75534` 新一个。

## 三条 demo 线为什么能干净合并

**因为改的目录完全不重叠**：

```
#98  → simulation/  scenarios/  docs/simulation/
#99  → src/uav_runtime/  docs/fixtures/
#100 → frontend/swarm-console/
```

**这是团队协作的良好实践，值得保持。**

## ⚠️ 明确不在本版本里的：#97

| 指标 | #97 `8d94a80` | 三条 demo 线 |
|---|---|---|
| 分叉点 | `6fe7057`（10-20） | `bb24e38`（11-12） |
| 落后 main | **23 个提交** | 2 个提交 |
| 自身提交 | **10 个**（+1634 / +842 / +624 / +616 / +340 …） | 1~2 个 |
| 内容 | 机载 Runtime、持久任务服务、本地模型接入、MAVLink 健康修复 | demo 接口与展示 |

**#97 和 #99 有三个文件冲突**（实测 9 处）：
`routes.py`(3)、`server.py`(5)、`mavlink_backend_session.py`(1)。

---

# 一、三个人都要守的四条约定

## 1.1 版本政策：验收只用 tag

### ⚠️ 先分清两类机器，这决定你该怎么拿版本

| 机器 | 能不能连 GitHub | 怎么拿到 `demo-20261113` |
|---|---|---|
| **三位的开发机**（这台 / 各自机器） | ✅ 能 | `git fetch` + `checkout` |
| **weier 离线台式机** | ❌ **完全离线，用 U 盘拷文件** | **解压打包好的快照** |

**不要把 weier 当成能联网的机器。** 它上面没有 GitHub，`git fetch` 一定失败。

### 在开发机上（看代码、改代码用）

```bash
git fetch origin --tags
git checkout -b acceptance/demo-20261113 demo-20261113
```

### 在 weier 上（现场验收用，离线）

```bash
# ① 解源码快照到新目录（旧的 ~/uavswarm 不动）
mkdir -p ~/uavswarm-demo
tar -xzf /mnt/d/weier-offline/sync/demo-20261113-src.tar.gz -C ~/uavswarm-demo

# ② 三维构建产物不在 git 里（0 个文件被跟踪），必须另外解这一层
tar -xzf /mnt/d/weier-offline/02-frontend-3d-dist.tar.gz \
    -C ~/uavswarm-demo/frontend/swarm-console/simulation-3d/

# ③ 验证关键文件在
ls ~/uavswarm-demo/src/uav_runtime/http/demo.py                       # #99
ls ~/uavswarm-demo/simulation/px4_gazebo/area_coverage.py             # #98
ls ~/uavswarm-demo/frontend/swarm-console/mission-dashboard.js        # #100
ls -lh ~/uavswarm-demo/frontend/swarm-console/simulation-3d/dist/assets/index-DCSbRQMB.js   # 应为 4.3 MB
```

**之后所有服务都从 `~/uavswarm-demo` 起**，不用 `~/uavswarm`。
**这样旧的 `~/uavswarm` 保持原样，出问题还能退回去。**

### 三条共同纪律

- **各人原有的 `codex/*` 分支不动**，验收完再回去继续
- **验收期间不改代码** —— 发现问题在群里说，统一决定是出 r2 还是各回分支修
- **`demo-20261113` 这个 tag 就是"我们要验的东西"**，验的就是它，不多也不少

## 1.2 分支政策（针对这次踩过的坑）

**这次暴露的真实问题**：同一个人的两条分支从同一点分叉后各走各的（#97 走 10 步停在 11-01，
#99 从 main 新位置走 1 步），结果 #97 被搁置、越放越难合。

**从这一版起**：
- ❌ **不再开超过 1 周不合并的长期分支**
- ✅ 大改动拆成小 PR，逐个合
- ✅ 未合并分支必须**每周 rebase 一次 `origin/main`**，控制冲突面
- ✅ 开工前先 `git fetch`，**从最新 `origin/main` 开工**，不要从数周前的点开工

## 1.3 口径政策：模拟必须标"演习"

**问题**：#99 的降级处置是"模拟 HOLD / 返航 / 重分配，不发送飞控指令"，
而 #98 的三机是真飞。放在一次演示里，观众会看到"横幅说已 HOLD，三维里飞机还在飞"。

**统一按 A 方案**（保留模拟，三处显式标演习）：

| 谁 | 要做什么 |
|---|---|
| **Runtime** | `policy_decision_event` 和 `action_result` 的审计字段里带可机读标记（`simulated: true` 或既有等价字段），**一处定义、全链一致** |
| **主控台** | 横幅与审计详情里显示"演习 / SIMULATED"，**不要和真实执行混在一起** |
| **仿真** | 确认"降级期间不干预飞行（各自按航点继续）"这个前提 |

**统一话术**：
> "策略判定与审计是**真实的**，执行动作被标记为**演习模拟**，不会改变真实飞行计划。"

**为什么不选"真停"**：那需要合并 #97（落后 23 提交、10 个提交、9 处冲突）**并且**把 R3 从模拟改成真实下发
—— 是两件事，不是一件。

## 1.4 清理政策：先打 tag，再删分支

远端现在 **22 个分支**，一大半是死的。清理时：

```bash
# ① 先给要删的分支打归档 tag
git tag archive/pr97-20261113  8d94a80
git tag archive/pr98-20261113  914b042
git tag archive/pr99-20261113  74750f1
git tag archive/pr100-20261113 3d5d5e4
git push origin --tags

# ② 确认 r2 已含全部内容后，才删远端分支
git push origin --delete codex/simulation-demo-readiness
```

**顺序不能反**：删了分支不会丢 commit，但 **Draft PR 会变 Closed，评审记录不好找**。

---

# 二、给【Runtime】负责人的任务书

> 你的任务最重。第一阶段 R1~R5 已交付并合并，这一阶段有三件事。

## ✅ 已完成（确认一下，不用重做）

R1 链路评分、R2 演习注入、R3 降级判定、R4 任务进度、R5 失败归因 —— 都在 `74750f1` 里，
已在 `demo-20261113` 中，全量测试通过。

## R6 ★★★ 把 #97 合并成 r2（**本阶段最重的任务**）

### 为什么必须由你来做

我实测过：**9 处冲突全在 `routes.py` / `server.py` / `mavlink_backend_session.py`**，
都是语义级改动。**只有你懂，别人解就是瞎猜。**

### 怎么做（**顺序很重要，不要按"把 #97 搬进 #99"的思路**）

```bash
git fetch origin --tags

# ① 从已验证的 demo 集成分支开工（它已含 #98 #99 #100，测试全绿）
git checkout -b integration/demo-20261113-r2 origin/integration/demo-20261113

# ② 只合 #97 这一件事
git merge --no-ff origin/codex/runtime-platform-autonomy \
  -m "integration: merge runtime platform autonomy (#97) into demo version"

# ③ 解 9 处冲突
#    - src/uav_runtime/http/routes.py                        3 处
#    - src/uav_runtime/http/server.py                        5 处
#    - src/uav_runtime/adapters/mavlink_backend_session.py   1 处
#    参考：routes.py 的冲突看起来是两边都往同一段 import 里加东西，正确解法是全留下。

# ④ 跑全量测试（基线：936 passed, 12 skipped, 0 failed）
PYTHONPATH=src python3 -m pytest -q

# ⑤ 推上去
git push -u origin integration/demo-20261113-r2
```

### 验收标准

| 项 | 要求 |
|---|---|
| 合并冲突 | 全部解决，**没有 `<<<<<<<` 残留**（`grep -rn '<<<<<<<' src/` 必须为空） |
| 全量测试 | **不低于 936 passed, 12 skipped, 0 failed** |
| 冲突解法 | 每处冲突在 merge commit message 里写明"为什么这样解" |
| 不许做的事 | ❌ 不要顺手改无关代码 ❌ 不要为了过测试放宽断言 |

### 一个明确的提醒

**单测绿不等于能演示。** #97 自己写着"未飞行、未加载模型和前端"。
合并后我会在 weier 上做现场验收，**那才是真正的通过标准**。

## R7 ★★ 补 `simulated` 标记（A 方案）

见 §1.3。具体：

- `policy_decision_event` 与 `action_result` 里加一个**可机读**的演习标记
- 命名你定（`simulated` / `rehearsal` / `dry_run` 都行），但**一处定义、全链一致**
- 审计留痕：`demo_inject` / `demo_clear` 事件要能被回放读出

**验收**：`curl /api/policy/decisions?n=5` 里能看到这个字段；
前端不读它也能工作（向后兼容），读了就能显示"演习"。

## R8 ★ 清理工作区的临时目录

你的 `runtime-action-lifecycle` 工作区里有 **69 个未跟踪的 `.tmp_runtime_*` 目录**
（实测：**0 个 `.py` 改动**，全是草稿）。

```bash
# 确认都是草稿后清掉
cd <你的工作区>
git status --porcelain | grep '^??' | grep '\.tmp_runtime' | wc -l   # 应该 69
git clean -fdn -- '.tmp_runtime_*'                                   # 先 dry-run 看
git clean -fd  -- '.tmp_runtime_*'                                   # 确认后执行
```

或者加进 `.gitignore`（如果还想留）：`.tmp_runtime_*/`

---

# 三、给【仿真】负责人的任务书

## ✅ 已完成（确认一下）

S1 遥测采集、S2 静态坐标对齐、S3 覆盖面积函数、S4 起停可靠性 —— 都在 `914b042` 里。

## S5 ★★★ 现场验收的环境准备（**最要紧**）

你在报告里写：

> "本机 Windows 可用内存实测 **0.89-2.50 GiB，低于此前三机相机版启动时观察到的内存增量**"

**原因基本确定**：weier 有 **63.6 GB** 物理内存，但 **WSL2 在 Windows 10 上的默认上限是
`min(物理内存 50%, 8 GB)` = **8 GB**。**

**要做的**（Windows 侧，不是 WSL 里）：

```ini
# C:\Users\<你的用户名>\.wslconfig
[wsl2]
memory=48GB
processors=12
swap=8GB
```

```powershell
wsl --shutdown
```

WSL 里确认：
```bash
free -h          # Mem total 应为 47Gi 左右
nproc            # 应为 12
```

**验收标准**：三机 + Gazebo 相机版跑起来后，`free -h` 的 available 仍 **> 4 GiB**。

## S6 ★★ 场景一致性的现场核对（S2 只做了静态验证）

你在报告里写：

> "静态验证 `scene_ned(100,0,0)` 映射到 Cesium 参考视图正北 100 米。已导入街区的 12 栋楼与青岚市生成器的位置和尺寸一致。**现场位置仍待核对**。"

**要做的**：在 weier 上真正跑起来之后，做一次**动态核对**：

1. 用 `patrol` 让一架机从原点飞到 NED(100, 0, 0)
2. 同时看三维画面里它相对某个**具体地物**（某栋楼、河岸）的位移
3. 方向和距离都要对得上

**这是演示时最容易被看出破绽的地方** —— 观众会对照建筑和飞机位置。

## S7 ★ 覆盖分布数据（前端需要）

主控台现在把"覆盖分布"标为**未知**（做法诚实，我们认可）。
但如果演示要展示"侦察了多少区域"，灰块会引来提问。

**要做的**：把 `patrol.py` 里已有的足迹数据**暴露成一个可读的形式**：
- 已飞航迹的多边形/折线列表
- 或者简单网格（每格 0/1 表示是否覆盖）

**接口层面很小**，但演示观感提升明显。

---

# 四、给【前端 / 主控台】负责人的任务书

## ✅ 已完成（确认一下）

F1 首屏重构、F2 主时间轴、F3 降级大屏、F4 完成度 KPI、F5 横幅+溯源面板、
F6 LIVE/DEMO 双模式+演示大屏、F7 显式化 —— 都在 `3d5d5e4` 里，114 项前端测试通过。

**特别确认一件做得对的事**：演示大屏带 `DEMO · 内置演习` 标记，且明确"即使没有遥测也能播完"。
**这个设计是对的** —— 保证演示不翻车。**唯一要守的规矩：演示时不能把 stage 画面说成实时数据。**

## F-A ★★★ 现场验收配合：LIVE 三机

你在报告里写："LIVE 三机任务进度和真实链路变化仍待联合验收。"

**验收时要看**（这不是让你改代码，是让你一起看）：

| 检查 | 期望 |
|---|---|
| LIVE 模式下三架都在 | 不是 0/3 |
| 任务地图的任务区轮廓 | 有（来自 Runtime 的区域边界） |
| 完成度百分比 | 随任务推进真实增长（不是假动画） |
| 链路质量 | 80~100 波动；注入后掉下去变红 |
| 降级横幅 | 显示规则名 + **演习标记**（R7 落地后） |
| 时间轴 | 有黄色降级节点、蓝色恢复节点 |

## F-B ★★ 覆盖分布（等 S7 的数据）

如果仿真负责人能给出足迹数据（S7），把地图上的"未知"换成实际分布；
给不出就保持"未知"，**不要用假数据填**。

## F-C ★ 风险 3 的补充

如果演示时确实要展示"侦察覆盖率"，需要在任务地图上**区分两种指标**：

- **航点完成度**（已验证到达的航点 / 总航点）← Runtime 现在有
- **面积覆盖率**（已覆盖面积 / 总面积）← Runtime 现在有汇总，没有分布

**这两个不要混成一个百分比**，混淆会被懂行的人挑出来。

---

# 五、关于算法与 GPU（影响算法放在哪一边）

## 结论先说

**当前 weier 的 WSL 用不了 RTX 3080。**

## 依据（微软官方文档）

> "**Install Windows 11 or Windows 10, version 21H2**"
> — [Enable NVIDIA CUDA on WSL 2](https://learn.microsoft.com/en-us/windows/ai/directml/gpu-cuda-in-wsl)
> 另需 WSL 内核 ≥ 5.10.43.3

| 项 | 要求 | weier 现状 | 结论 |
|---|---|---|---|
| Windows 版本 | 11 或 **10 21H2（19044）** | **10 19041（2004）** | ❌ **不满足** |
| NVIDIA 驱动 | ≥ 470 | 531.29 | ✅ 满足 |
| WSL 内核 | ≥ 5.10.43.3 | 需确认 | 待查 |
| WSL2 | 必需 | ✅ 是 | ✅ |

## 三条路

| 路线 | 代价 | 适用 |
|---|---|---|
| **A. 算法服务跑在 Windows 侧**（用 Windows 的 Python + CUDA），Runtime 通过 HTTP 调它 | 小。但 WSL→Windows 要用网关 IP（`$(ip route show default \| awk '{print $3}')`），不是 `127.0.0.1` | **推荐**，现在就能做 |
| **B. 升级 Windows 到 21H2 / Win11** | 大。离线环境要准备升级包，升完要重验 WSL / 驱动 / Gazebo | 中期考虑 |
| **C. 算法用 CPU** | 最小 | **如果现在只是小模型/规则推理** |

> **补充事实**：#97 里的"本地模型接入"验证的是 **"真实 Linux CPU 模型 + 算法候选服务"**（CPU，不是 GPU）。
> 也就是说**当前这条链路本来就不依赖 GPU**。

## 需要你回答的问题

1. 这次演示的算法，**是 CPU 推理还是需要 GPU 训练/推理**？
2. 如果是 GPU：能否接受"算法跑 Windows、Runtime 跑 WSL、中间走 HTTP"？
3. 如果必须同机同环境：能否排期升级 Windows 到 21H2？

---

# 六、联合验收清单（11 条，现场打勾）

| # | 验收项 | 命令 / 操作 | 期望 |
|---|---|---|---|
| 1 | 三机起飞 | 主控台点起飞 | 三维里三架离地 |
| 2 | **位置真的在变** | 间隔 3 秒两次 `curl -s .../api/telemetry/latest \| grep local_position` | 两次 `x/y/z` **不同** |
| 3 | 地图有任务区 | 看首屏 | 多边形 + 三机进度 |
| 4 | 完成度在涨 | 观察 60 秒 | 百分比单调增长 |
| 5 | 链路质量有数 | 看降级大屏 | 80~100 波动 |
| 6 | 注入降级 | 点注入 / `POST /api/demo/inject` | 3 秒内掉到注入值并变红 |
| 7 | **系统自己处置** | **不做任何操作**，等 10 秒 | 出现 policy 决策 + 横幅 |
| 8 | **处置标为演习** | 看横幅/审计 | 明确显示"演习"/`SIMULATED` |
| 9 | 时间轴降级节点 | 看时间轴 | 黄色节点，可点开看 JSON |
| 10 | 恢复 | 点清除注入 | 链路恢复，蓝色节点 |
| 11 | 审计可重建 | Audit·Replay | 整条链按时间排出来 |

**外加三件容易漏的**：

| 项 | 怎么验 |
|---|---|
| 双前端同时在线 | 5178 + 5179 同时开，都看得到三机 |
| 三维位置与 Gazebo 对得上 | Gazebo 挪一架，看三维里方向/距离 |
| 停干净 | `stop_three_uav.sh` 后 `ss -lunp` 无 1454x/1458x、`pgrep -fa 'bin/px4\|gz sim'` 为空 |

---

# 七、优先级与时间

## 7.1 当前阶段：**先本地收敛，weier 现场验收往后放**

阶段划分（**这是最新决定，前面的时间安排以这一节为准**）：

| 阶段 | 在哪做 | 目标 | 状态 |
|---|---|---|---|
| **第一阶段** | `demo-20261113` 已定型 | 三条 demo 线合并 + 全量测试全绿 | ✅ **已完成**（936 passed） |
| **第二阶段（现在）** | **本地开发机** | **合并 #97 成 r2 → 再测试 → 修 → 再合并，收敛到能演示** | ⏳ **进行中** |
| 第三阶段 | weier（离线） | 11 条现场验收 | ⏸ **往后放** |

**所以现在不要在 weier 上折腾**，也不要把 weier 当验收环境。
本地能做的先做完、合并干净、测试绿了，再谈上机。

## 7.2 第二阶段的任务顺序

| 序 | 任务 | 谁 | 能不能在本地做完 |
|---|---|---|---|
| **1** | **R6 合 #97 成 r2**（见 `PROMPT_conflict_resolution_r2_20261114.md`） | Runtime | ✅ 能（纯代码 + 单测） |
| **2** | **R7 `simulated` 标记** | Runtime | ✅ 能 |
| 3 | **R8 清临时目录** | Runtime | ✅ 能（5 分钟） |
| **4** | **S7 覆盖分布数据** | 仿真 | ✅ 能（写代码） |
| 5 | **F-C 航点完成度与面积覆盖率分开** | 前端 | ✅ 能（改代码） |
| 6 | F-B 覆盖分布上图 | 前端 | ⏳ 等任务 4 |
| — | **S5 内存配置** | 仿真 | ❌ 在 weier 上做，第三阶段 |
| — | S6 场景动态核对 / F-A LIVE 验收 | 仿真 / 前端 | ❌ 需要真跑，第三阶段 |

**一句话**：现在能动的只有 **Runtime 全部 + 仿真 S7 + 前端 F-C**。
其余的任务需要真实的 PX4 + Gazebo + 双前端同时在线，等第三阶段。

## 7.3 第二阶段的收敛标准

全部满足才算第二阶段结束：

1. `integration/demo-20261113-r2` 合并完成，**无冲突残留**
2. 全量 `pytest` **≥ 1083 passed, 0 failed**（r2 基线是 1083/12，不是 936）
3. `simulated` 标记贯通 Runtime → 前端（口径一致）
4. **#101（前端 F-C）已合进 r2**
5. 打 tag `demo-20261113-r2`
6. **分支与 worktree 收敛**：远端分支 33 个、本地 worktree 25 个，
   都要降到只剩必要的几个
7. 之后才进入第三阶段（weier 现场验收）

## 7.4 r2 定版的状态（2026-11-14 实测）

| 项 | 状态 |
|---|---|
| r2 = `demo-20261113` + #97 | ✅ 已推送，`c1a3736` |
| 9 处冲突解法 | ✅ **独立核验通过**（`matched_source` 未丢、`127.0.0.1` 限制在、`ExitStack` 清理齐全、`simulated` 贯通 5 文件） |
| r2 全量测试 | ✅ **1083 passed, 12 skipped, 0 failed** |
| **#101 是否已合入** | ❌ **还没有**，但已预演：干净合并 + **1083 passed** |
| tag `demo-20261113-r2` | ❌ 未打（等 #101） |

**结论：技术上只差一步 —— 把 #101 合进 r2，然后就能打 tag 定版。**
这一步没有技术风险，只是走流程。

---

# 八、算法线：**不进这次演示，但有三件事要做**

> 这一节是后加的。之前整理三条 demo 线时**漏掉了算法**，已补齐。

## 8.1 算法线现在的真实状态

| 层次 | 在哪 | 状态 |
|---|---|---|
| 问题定义 + 接口需求 | `algorithm_lab/INTELLIGENCE_HANDOFF/`（**2026-11-14 已入库**） | ✅ 已跟踪 |
| 研究脚手架 + 模型实验 | `algorithm_lab/mission_llm_poc/`（main 上 66 个文件） | ✅ 已跟踪 |
| 两条实现分支 | `codex/algorithm-lab-local-llm-poc`（1 提交，**落后 54**）<br>`codex/algorithm-uav02-local-candidate`（8 提交，+1746，落后 27） | ❌ 未合并 |

**算法负责人自己写的一句话（`01_runtime_interface_requirements.md:24`）**：

> 当前 `algorithm_lab/mission_llm_poc` 的实现是"**闭环验证脚手架**"
> （greedy 分配 + 严格校验器），**不是算法成果**。
> 它的价值在于冻结 I/O 契约、可复现、可审计。**真正的智能算法尚未开始。**

## 8.2 为什么这次演示不演算法

**不是不想演，是现在演不了，硬演会露底**：

1. **`planner.py` 仍是 plan-only** —— 不调模型，没有"自然语言 → 任务计划"的链路
2. `#97` 的 `876bb92` 只是**验证脚本**（`scripts/verify_local_model_runtime.py`，322 行），
   证明 Runtime 能调通模型候选服务，**不是产品化接入**
3. 算法提的 P0 数据（场景实体清单 / 载具能力语义 / 区域自然语言描述）
   **Runtime 一项都没提供**
4. 五个"真正的智能问题"（`02_intelligence_problem_definition.md` 第 1 节）全部未开始

**演示话术（主动说，别等人问）**：

> "算法这块我们做了**问题定义**和**接口契约**，也验证了模型候选服务能被 Runtime 调用
> （12/12 任务步骤候选及时有效）。但**真正的智能算法还没开始** ——
> 我们刻意先把契约和边界冻住，避免做完发现接不上。
> 现在有一份接口需求在等 Runtime 答复，答完就进入实现阶段。"

## 8.3 三件现在就该做的事

### ① 【已完成】两份 handoff 文档入库

```
algorithm_lab/INTELLIGENCE_HANDOFF/01_runtime_interface_requirements.md
algorithm_lab/INTELLIGENCE_HANDOFF/02_intelligence_problem_definition.md
```

之前是 `??` 未跟踪状态，一次误 `clean` 就没了。**已提交进 main。**
**算法负责人以后改这两份文档，走正常 PR，不要再留 untracked。**

### ② 【Runtime 负责人的活】答复那 4 个接口问题

`01_runtime_interface_requirements.md` 文末有 4 个问题，**从 2026-09-24 挂到今天没有答复**：

| # | 问题 |
|---|---|
| 1 | `objective`（自然语言）与 `tasks[]`（结构化）**谁权威**？冲突怎么处理？变更窗口？ |
| 2 | P0 数据由 Runtime 提供，还是算法侧从现有数据推导？ |
| 3 | 职责划分（几何归规划、调度归 Runtime、Policy 归 Policy Gate）是否一致？ |
| 4 | 算法提案进主线的路径？快照过期重验由谁负责？ |

**这一项不需要写代码，只需要表态。** 详细版见
`ops/PROMPT_to_runtime_intelligence_answers_20261114.md`（含建议答案供勾选）。

> ⚠️ **第 1 个问题最关键**。它指出的是架构倒置：
> 现在 `tasks[]` 是权威、`objective` 是"不可信附加数据"，
> 而自然语言才是操作员原始意图，结构化任务清单**本应是它的派生结果**。
> 这个不定，算法线永远起不来。

### ③ 【算法负责人的活】两个分支处置 + 明确当前唯一可交付的是什么

| 分支 | 规模 | 建议 |
|---|---|---|
| `codex/algorithm-lab-local-llm-poc` `4a42f2d` | 13 files, +1382，**落后 54 提交** | 打 `archive/` tag 后删分支（落后太多，无合并价值） |
| `codex/algorithm-uav02-local-candidate` `0ff77c1` | 19 files, +1746，落后 27 | 打 `archive/` tag **保留**（模型候选服务实现，将来要用） |

**当前唯一能交付给演示的东西**：模型候选服务的**调用证据**
（`docs/runtime_local_model_verification_20261029.md` + 那个 322 行验证脚本）。
**这条可以作为"算法线已打通链路"的证据，但不能当作"算法能力"。**

## 8.4 算法线在第三阶段（weier 验收）要不要参与

**不要。** 第三阶段只验三机飞行的 11 条，算法没有可验的东西。

**算法线进入的时间点**：等 Runtime 答复 4 个问题之后，单独排期，
届时再定第一个"真正的智能问题"（建议从**问题 A 语义锚定**起步，
因为它最独立、最容易做出可见效果）。

---

# 附录：命令速查

## 拉取验收版本

**开发机（能连 GitHub）**：
```bash
git fetch origin --tags
git checkout -b acceptance/demo-20261113 demo-20261113
```

**weier（离线，只用 U 盘拷进来的文件）**：
```bash
mkdir -p ~/uavswarm-demo
tar -xzf /mnt/d/weier-offline/sync/demo-20261113-src.tar.gz -C ~/uavswarm-demo
tar -xzf /mnt/d/weier-offline/02-frontend-3d-dist.tar.gz \
    -C ~/uavswarm-demo/frontend/swarm-console/simulation-3d/
```

## 起四件套（weier WSL）

```bash
# 终端 1：三机仿真
cd /root/uavswarm && bash simulation/px4_gazebo/scripts/start_three_uav.sh \
  --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json --gui

# 终端 2：Runtime（必须 /usr/bin/python3 = 3.10）
cd /root/uavswarm && PYTHONPATH="$PWD/src" /usr/bin/python3 -m uav_runtime.http.server

# 终端 3：主控台
cd /root/uavswarm/frontend/swarm-console && python3 -m http.server 5178 --bind 0.0.0.0

# 终端 4：三维（必须反代，不能用 http.server）
cd /root/uavswarm && python3 /mnt/d/weier-offline/serve_3d_proxy.py \
  --dir frontend/swarm-console/simulation-3d/dist
```

## 端口

| 端口 | 用途 |
|---|---|
| 8765 | Runtime API |
| 5178 | 主控台 |
| 5179 | 三维（含 `/api` 反代） |
| 14540-14542 | PX4 → Runtime（遥测），`14540 + 实例号` |
| 14580-14582 | Runtime → PX4（指令），`14580 + 实例号` |
