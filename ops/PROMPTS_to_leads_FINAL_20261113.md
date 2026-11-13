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

```bash
git fetch origin --tags
git checkout -b acceptance/demo-20261113 demo-20261113
```

**各人原有的 `codex/*` 分支不动**，验收完再回去继续。
**验收期间不改代码** —— 发现问题请在群里说，统一决定是出 r2 还是各回分支修。

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

| 序 | 任务 | 谁 | 阻塞别人吗 |
|---|---|---|---|
| **1** | **S5 内存配置**（`.wslconfig` 48GB） | 仿真 | 🚨 **阻塞全部现场验收** |
| **2** | **R6 合 #97 成 r2** | Runtime | 阻塞"机载 Runtime / 真停"路线 |
| 3 | R7 `simulated` 标记 | Runtime | 阻塞 §1.3 口径落地 |
| 4 | 现场验收 11 条（用 `demo-20261113`） | 全体 | — |
| 5 | S6 场景动态核对 | 仿真 | 阻塞"三维可信度" |
| 6 | S7 覆盖分布 + F-B | 仿真→前端 | 观感提升 |
| 7 | R8 清临时目录 / 分支清理 | Runtime / 全员 | 不阻塞 |

**注意**：任务 4（验收）**不需要等 2 和 3**。先用现有 `demo-20261113` 把主链路验掉，
不要为了等 #97 把今天浪费掉。

---

# 附录：命令速查

## 拉取验收版本

```bash
git fetch origin --tags
git checkout -b acceptance/demo-20261113 demo-20261113
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
