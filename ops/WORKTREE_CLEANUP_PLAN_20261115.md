# Worktree 与分支清理方案（2026-11-15）

**负责人已确认**：旧的文件夹**不删，归档保留**（"心里安心，占空间就占空间"）。

本文按这个决定写。**分本地和远端两段，本地先做，远端最后做。**

---

## 一、先分清两类目录（这一步不做，后面全错）

`D:\2026UAVSwarm-worktrees` 下有 **23 个目录**，但只有一部分是 git worktree：

```bash
# 只有这个命令列出来的才是 worktree
git worktree list
```

**不是 worktree 的**（是负责人自己建的，直接 `mv` 就行，不能用 `git worktree remove`）：

| 目录 | 性质 |
|---|---|
| `_ops` | 我的工作区（未跟踪） |
| `_patent_rev` | 你自己建的 |
| `_tianqian_work` | 你自己建的 |
| `专利A_附图_预览` | 你自己建的 |
| `.tmp_dsh_extract` | 临时解压目录 |

**这 5 个不进下面的清理流程。** 要不要归档你自己决定。

---

## 二、本地 worktree 归档（推荐做法）

### ⚠️ 为什么不能直接 `mv` 目录

每个 worktree 目录里有个 `.git` **文件**，内容是指向主仓库的指针：

```
gitdir: D:/2026UAVSwarm/.git/worktrees/runtime-action-history
```

**一移动这个指针就断了** —— 目录变成"坏掉的 worktree"，`git worktree list` 会报错。

### ✅ 正确做法：拷纯文件 → 再让 git 移除

```powershell
# 目标归档目录（放在仓库外！）
$Archive = 'D:\2026UAVSwarm-oldcode'
New-Item -ItemType Directory -Force $Archive | Out-Null

# 对每个要归档的 worktree：
$wt = 'D:\2026UAVSwarm-worktrees\runtime-action-history'
$name = Split-Path $wt -Leaf

# ① 拷纯文件到归档目录（排除 .git）
robocopy $wt (Join-Path $Archive $name) /E /XD .git /NFL /NDL /NJH /NJS

# ② 再用 git 正确移除 worktree
git worktree remove $wt
```

**结果**：
- `D:\2026UAVSwarm-oldcode\<名字>\` 是**纯文件归档**，谁都能打开看
- `git worktree list` **保持干净**
- 代码仍在 git 对象库里，tag 也在，随时能用 `git worktree add` 重建

### 为什么归档目录必须放仓库外

```
✅ D:\2026UAVSwarm-oldcode\      ← 仓库外
❌ D:\2026UAVSwarm\oldcode\      ← 仓库内，`git status` 会多出一堆 `??`
```

---

## 三、逐个判定（23 个 worktree）

### 3.1 建议归档（已合并进 main / 已被 r2 吸收）

| worktree 目录 | 分支 | HEAD | 归档理由 |
|---|---|---|---|
| `runtime-action-lifecycle` | `codex/runtime-platform-autonomy` | `8d94a80` | **#97 已被 r2 吸收** |
| `runtime-demo-readiness` | `codex/runtime-demo-readiness` | `74750f1` | **#99 已被 r2 吸收** |
| `simulation-demo-readiness`（在 `.runtime/`） | `codex/simulation-demo-readiness` | `914b042` | **#98 已被 r2 吸收** |
| `frontend-demo-readiness`（在 `.codex/`） | `codex/frontend-demo-readiness` | `3d5d5e4` | **#100 已被 r2 吸收** |
| `runtime-heartbeat-lifecycle` | 同名分支 | `b4e2f6e` | 已合并进 main |
| `frontend-runtime-action-control` | 同名分支 | `907e174` | 已合并进 main |
| `frontend-selection-display-fix` | 同名分支 | `ea4bf62` | 已合并进 main |
| `integration-four-module` | 同名分支 | `b4e2f6e` | 已合并进 main |
| `px4-gazebo-runtime-integration` | `codex/simulation-ground-reference-evidence` | `ea4bf62` | 已合并进 main |
| `px4-gazebo-three-uav-mission` | 同名分支 | `b4e2f6e` | 已合并进 main |
| `.runtime/acceptance-88-92-20261011` | detached | `ea4bf62` | 旧验收快照 |
| `.runtime/acceptance-88-92-fresh-20261011` | detached | `ea4bf62` | 旧验收快照 |
| `.runtime/acceptance-b-online-20261012` | detached | `ea4bf62` | 旧验收快照 |

### 3.2 先保留（还没合并，或有独立价值）

| worktree 目录 | 分支 | 为什么先留 |
|---|---|---|
| `algorithm-lab-local-llm-poc` | 同名 | 等算法负责人确认 `4a42f2d` 里有没有还想要的东西 |
| `algorithm-uav02-local-candidate` | 同名 | 同上（`0ff77c1`，8 个提交，模型候选服务） |
| `runtime-action-history` | 同名 | 未合并，待判定 |
| `simulation-3d-cityscape` | 同名 | 未合并，三维城市相关的历史工作 |
| `simulation-uav02-onboard-agent` | 同名 | 未合并 |
| `.runtime/uav02-autonomy-integration` | 同名 | 未合并 |

> 这 6 个一共也就几个 GB，**放着不影响任何事**。等 r3 收尾再处理。

### 3.3 主仓库 `D:\2026UAVSwarm` 本身

**不动。** 它现在是 `main` 分支，是唯一的工作主目录。

---

## 四、远端分支清理（**最后做，而且必须先打 tag**）

远端现在 **33 个分支**。

### 4.1 第一步：给要删的分支打 archive tag

```bash
# 先给每个要删的分支打归档 tag（tag 指向那个提交，永久可寻回）
git tag archive/runtime-platform-autonomy-20261115  8d94a80
git tag archive/runtime-demo-readiness-20261115     74750f1
git tag archive/simulation-demo-readiness-20261115  914b042
git tag archive/frontend-demo-readiness-20261115    3d5d5e4
git tag archive/algorithm-llm-poc-20261115          4a42f2d
git tag archive/algorithm-uav02-20261115            0ff77c1
git push origin --tags
```

### 4.2 第二步：确认 tag 打上了，再删分支

```bash
# 核对
git ls-remote --tags origin | grep archive/ | wc -l

# 删远端分支（逐个删，不要批量，边删边确认）
git push origin --delete codex/runtime-platform-autonomy
git push origin --delete codex/runtime-demo-readiness
git push origin --delete codex/simulation-demo-readiness
git push origin --delete codex/frontend-demo-readiness
```

### 4.3 为什么必须先打 tag

| 打 tag 再删 | 直接删 |
|---|---|
| `git log tags/archive/xxx` 随时能看 | 只能靠 `git reflog`（会被 gc 清） |
| 能 `git worktree add` 重建 | 找不回来 |
| Draft PR 变 Closed，但 commit 有据可查 | 同上，但更慌 |

**注意**：删远端分支不会删 commit（除非哪天 gc），但**分支引用没了**，
在 GitHub 上就看不到那个分支了。**tag 是保险。**

---

## 五、执行顺序（建议）

```
现在
  ↓
① 本地归档 13 个（第三节 3.1）        ← 随时可做，零风险
② 远端打 archive tag                  ← 随时可做，零风险
  ↓
等 r3 收尾（Runtime 透传 coverage.grid + 前端联调）
  ↓
③ 远端删分支（第一批：已被 r2 吸收的）
④ 判定 3.2 那 6 个未合并的，再决定
```

**①② 现在就能做**，不影响任何人的工作。

---

## 六、一条命令先看看会发生什么（dry-run）

```powershell
# 只列清单，不动任何东西
git worktree list | ForEach-Object {
    $parts = ($_ -split '\s+')
    "  {0}" -f $parts[0]
}
```

**先看清单，确认哪些是 worktree、哪些不是。**

---

## 七、出问题怎么回滚

| 情况 | 恢复办法 |
|---|---|
| 归档目录拷坏了 | `git worktree add D:\recover\xxx <sha>` 重建（sha 用 tag 或原 branch） |
| 误删了 worktree | 同上，一行重建 |
| 误删了远端分支 | `git push origin archive/xxx:refs/heads/原分支名` 从 tag 恢复 |
| `.git/worktrees` 有脏数据 | `git worktree prune` 清理 |

**只要 tag 还在，什么都能恢复。**
