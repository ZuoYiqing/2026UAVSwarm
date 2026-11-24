# 给【算法】负责人：拉最新代码的正确姿势（别丢你自己的东西）

**日期**：2026-11-16

---

## 一、先说结论：你的代码不会丢

我查过了，你的两条分支**都已经在 GitHub 上**：

| 分支 | 远端 SHA | 状态 |
|---|---|---|
| `codex/algorithm-lab-local-llm-poc` | `4a42f2d` | ✅ 已在远端 |
| `codex/algorithm-uav02-local-candidate` | `0ff77c1` | ✅ 已在远端 |

两个工作区我也查了：**已跟踪改动 0 个，未跟踪文件 0 个**。

**所以现在不管怎么操作，你的代码都不会丢失** —— 它已经在云端了。

---

## 二、⚠️ 但**不要**照别人的 prompt 做这两件事

### ❌ 不要在你自己那两个工作区里 `git checkout main`

因为**你的代码不在 main 里**（这是故意的，见第四节）。
一旦切到 main，你工作区里的算法代码会**全部消失**（能切回来，但会以为出事了）。

**你现在的工作区保持原样不要动。**

### ❌ 不要执行 `git add -A && git commit`

那条命令是给"干净工作区"的人用的。
**你这边如果有模型权重、数据集、大文件，`git add -A` 会把它们全部塞进 git**
（几个 GB，可能直接卡死，而且以后很难从历史里清掉）。

---

## 三、✅ 正确做法：给 main 单独开一个工作区

**你的两个老工作区一个都别动**，另开一个新的。

> ⚠️ **注意：不能直接 `git worktree add <路径> main`**
> —— 主工作区 `D:\2026UAVSwarm` 已经占用了 `main`，会报
> `fatal: 'main' is already used by worktree at 'D:/2026UAVSwarm'`。
>
> **必须用 `--detach`（只核代码）或者 `-b`（要开发）。**

### 情况 A：只核对基线（不改任何分支）

```bash
cd D:\2026UAVSwarm
git fetch origin --tags

git worktree add --detach D:\2026UAVSwarm-worktrees\algorithm-main main

cd D:\2026UAVSwarm-worktrees\algorithm-main
git log -1 --oneline
git merge-base --is-ancestor demo-20261113-r3 HEAD && echo "OK: 版本正确" || echo "错了"
```

### 情况 B：要基于新基线开发（推荐）

```bash
cd D:\2026UAVSwarm
git fetch origin --tags

# 从最新 origin/main 开一个新分支 + 新工作区
git worktree add -b codex/algorithm-intent-anchoring D:\2026UAVSwarm-worktrees\algorithm-intent-anchoring origin/main

cd D:\2026UAVSwarm-worktrees\algorithm-intent-anchoring
git merge-base --is-ancestor demo-20261113-r3 HEAD && echo "OK: 版本正确" || echo "错了"
```

**两种都要看到 `OK: 版本正确`。**

**这样你的工作区变成：**

```
D:\2026UAVSwarm-worktrees\algorithm-lab-local-llm-poc      ← 老工作，原样不动
D:\2026UAVSwarm-worktrees\algorithm-uav02-local-candidate  ← 老工作，原样不动
D:\2026UAVSwarm-worktrees\algorithm-intent-anchoring       ← 新的，基于 main
```

**随时能回去看老代码：**
```bash
cd D:\2026UAVSwarm-worktrees\algorithm-uav02-local-candidate
git status          # 还是你原来那个分支，一点没变
```

---

## 四、你的代码为什么没合进 main

**这是有意的，不是漏了。**

> ⚠️ **更正我先前的说法**：我一开始写的是"只有需求文档进了 main"，**这个说法太宽**。
> 实际情况是：`main` 上的 `algorithm_lab/` 已经有 **89 个文件**，
> 包括 `mission_llm_poc/`（66 个）和 `world_model_lab/`（21 个），**这些早就在了**。
> 真正没进 main 的，只有你两条分支独有的那部分
> （`4a42f2d` 的 13 个文件、`0ff77c1` 的 19 个文件）。

### main 上已有的（早就在）

| 目录 | 文件数 |
|---|---|
| `algorithm_lab/mission_llm_poc/` | 66 |
| `algorithm_lab/world_model_lab/` | 21 |
| `algorithm_lab/INTELLIGENCE_HANDOFF/` | 2（2026-11-16 入库） |

### 没进 main 的（两条分支独有）

| 分支 | 独有文件 | 内容 |
|---|---|---|
| `codex/algorithm-lab-local-llm-poc` `4a42f2d` | 13 个 | 离线**着陆证据基线** |
| `codex/algorithm-uav02-local-candidate` `0ff77c1` | 19 个 | **UAV-02 候选服务**（compact-view 模型视图 / Ubuntu CPU 离线包 / 候选输入哈希） |

### 为什么不合

原因：算法**不进入本次演示**。判断依据是你自己写的那份文档：

> 当前 `algorithm_lab/mission_llm_poc` 的实现是"**闭环验证脚手架**"
> （greedy 分配 + 严格校验器），**不是算法成果**。
> 它的价值在于冻结 I/O 契约、可复现、可审计。**真正的智能算法尚未开始。**
> —— `01_runtime_interface_requirements.md:24`

**你那两条分支原样保留**，等你需要的时候再合。
合进来之前建议先 rebase 到 `origin/main`（它们分别落后 54 和 27 个提交）。

---

## 五、保护措施：给你的两条分支打归档 tag

**建议现在就做**（一次性的，两分钟）：

```bash
cd D:\2026UAVSwarm
git tag archive/algorithm-llm-poc-20261116  4a42f2d
git tag archive/algorithm-uav02-20261116    0ff77c1
git push origin --tags
```

**为什么**：以后清理远端分支时，就算 `codex/*` 分支被删了，
这两个 tag 还钉着你的提交，**随时能完整找回**：

```bash
# 以后要从 tag 恢复成可用的分支
git checkout -b algorithm-uav02 archive/algorithm-uav02-20261116
```

---

## 六、你现在的状态和下一步

### 已完成的

| 项 | 状态 |
|---|---|
| 问题定义 + 接口需求 | ✅ 已入库（`algorithm_lab/INTELLIGENCE_HANDOFF/`） |
| 两条实现分支 | ✅ 已推远端，**未合 main（故意）** |
| **那 4 个接口问题** | ✅ **Runtime 已答复：A / C / A / A** |

### 4 个答复的内容（你这是重点）

| 问题 | 答复 |
|---|---|
| **Q1 权威关系** | **A** — r2 保持 `tasks[]` 权威；`objective` 冲突时**请求澄清**，不让模型擅自改任务。**演示后另开 `intent` 模式**：`objective` 是意图来源，模型生成的任务仍是候选 |
| **Q2 P0 数据** | **C** — 按数据主责供给：Runtime 先交付**场景实体清单与载具能力样例**；续航/速度包线/视场/分辨率由机型或仿真负责人核定，**未核定就标未知**；**算法负责把自然语言映射到实体 ID** |
| **Q3 职责分工** | **A** — 认可原表，补齐拒绝语义：拒绝的作用域、有效期及复核方式由 **Runtime/Policy 定义**，算法只消费 |
| **Q4 接入方式** | **A** — 提案经 **Schema 校验 + 人工确认**；输出附输入/提示词/输出哈希及模型和推理设置；Runtime 在执行前判快照是否过期，**过期提案作废**，算法基于新快照重算，不自动重试 |

**Q1 的关键**：`intent` 模式是**演示后才开**，现在不改。
所以你的"自然语言 → 任务图"能力，**下一阶段才有地方接**。

### 建议的下一步

1. **先完成第三节**（开 algorithm-main 工作区）+ **第五节**（打 archive tag）
2. **等排期**。第一个要做的建议是 `02_intelligence_problem_definition.md` 里的
   **问题 A：语义锚定** —— 五个智能问题里最独立、最容易做出可见效果、不依赖几何求解
3. **Q2 的落地**：Runtime 会先给场景实体清单和载具能力样例，
   你负责**把自然语言映射到实体 ID** —— 这块可以在拿到样例后先动

---

## 七、一句话总结

> **你的代码在云端，丢不了。别动你现有的两个工作区，另开一个 `algorithm-main` 用新基线。**
> **你的分支没合进 main 是故意的，等你排期到了再合。**
