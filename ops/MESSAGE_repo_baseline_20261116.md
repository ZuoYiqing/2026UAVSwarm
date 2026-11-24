# 仓库基线已统一，请拉取最新代码

**发给**：前端 / Runtime / 仿真 / 算法 四位负责人
**日期**：2026-11-16

---

## 一句话

**所有人的工作已经合并到 `main` 了。请拉到最新的 `main`，以后从这里开新分支。**

以前大家各自在 `codex/*` 分支上开发，现在这些分支的内容**全部已经在 `main` 里**。

---

## 现在的版本号

| 项 | 值 |
|---|---|
| **分支** | **`main`** |
| **提交** | **`8e41b4e`** |
| **对应的 tag** | **`demo-20261113-r3`**（指向 `54c4e12`） |
| **验证状态** | 1100 passed / 12 skipped / 0 failed |

---

## 怎么拉（照抄，按顺序）

```bash
# ① 先看自己有没有未提交的改动
git status

# ② 如果有，先保存（★ 千万不要用 git stash -u，会吞掉未跟踪目录，本仓库踩过这个坑）
git add -A
git commit -m "wip: 保存当前工作"

# ③ 拉最新
git fetch origin --tags
git checkout main
git pull origin main

# ④ 确认版本对不对
git log -1 --oneline
git merge-base --is-ancestor demo-20261113-r3 HEAD && echo "OK: 版本正确" || echo "错了: 没拉到最新"
```

**第 ④ 步必须看到 `OK: 版本正确`。**

也可以看 `git describe --tags`，应该显示类似 `demo-20261113-r3-13-g8e41b4e`（数字会变，`demo-20261113-r3` 前缀说明基于 r3）。

---

## 三个注意事项

### ① 不要再从旧的 `codex/*` 分支继续开发

那些分支的内容**已经全部在 `main` 里**了。继续在旧分支上改，会产生两套分叉，
下一次又要花一整天解冲突（这次 #97 就是这么拖了两个月的）。

**以后：从 `main` 开新分支。**

```bash
git checkout main
git pull origin main
git checkout -b codex/你的新任务名
```

### ② 不要用 `git stash -u`

本仓库的 `core.autocrlf = true`，而且有**大量未跟踪目录**（专利材料等）。
`git stash -u` 会把它们全部卷进 stash，恢复起来非常麻烦。

**要暂存就老实 `git add` + `git commit`。**

### ③ 切分支时看到很多"改动"是正常的

因为 `core.autocrlf = true`，切分支时 git 可能认为大量文件"改了"（实际只是 LF/CRLF 差异）。
**不要慌，也不要提交这些行尾改动。** 用 `git status` 看具体的文件列表，
只有你真正改过的那些才需要提交。

---

## 这次合进来的内容（按负责人）

### 前端
- `#100` 3d5d5e4 — demo 线（首屏重构 / 时间轴 / 降级大屏 / 完成度 KPI / 横幅 / LIVE-DEMO 双模式）
- `#101` 7b9d42c — F-C：航点完成度与面积覆盖率**分开显示**，缺证据时保留"未知"
- `#103` e3d8e10 — F-B：任务地图绘制覆盖网格，沿任务区边界裁剪（新增 `coverage-grid.js`）

### Runtime
- `#99` 74750f1 — demo 线（链路评分 / 演习注入 / 降级判定 / 任务进度 / 失败归因）
- `#97` 8d94a80 — 机载 Runtime / 平台网关 / 本地模型接入 / MAVLink 健康修复
- `#105` 1575c99 + 9499534 — **P0：把位姿可用性与链路健康分开**（转发期间新帧不再把链路分归零）+ `coverage.grid` 透传

### 仿真
- `#98` 914b042 — demo 线（遥测采集 / 坐标对齐 / 覆盖面积 / 起停可靠性）
- `#102` 82729c9 — S7：可选稀疏覆盖网格（`scene_ned` / 20 m 格 / 上限 25000 格）
- `#104` 3a4a070 — 健康修复：world digest 缓存 + `now_provider`（修掉 flaky，连跑 3 次全过）

### 算法
- ⚠️ **两条分支没有合进来**（`codex/algorithm-lab-local-llm-poc`、`codex/algorithm-uav02-local-candidate`）
- 原因：算法不进入本次演示，另行排期
- 但你的两份需求文档已经入库：`algorithm_lab/INTELLIGENCE_HANDOFF/`
- 4 个接口问题已答复（A / C / A / A），见 `ops/PROMPT_to_runtime_intelligence_answers_20261114.md`

---

## 你自己的工作区怎么办

你现在的工作区可能还 checkout 在某个 `codex/*` 分支上。**两种处理都行：**

**方式一（推荐）**：切到 main，工作区继续用
```bash
git checkout main
git pull origin main
```

**方式二**：保留旧工作区不动，另开一个新目录给 main
```bash
git worktree add D:\2026UAVSwarm-main main
```

**旧分支先别删** —— 等大家都切到 main 并确认没问题后统一清理（会先打 `archive/` tag）。

---

## 有问题怎么反馈

**不要直接改 main。** 开分支改，然后提 PR。

这次的教训是：**分支放太久会烂掉**（#97 放了 23 天，落后 23 个提交，解冲突花了半天）。
**建议每个分支不超过一周，每周至少 rebase 一次 `origin/main`。**
