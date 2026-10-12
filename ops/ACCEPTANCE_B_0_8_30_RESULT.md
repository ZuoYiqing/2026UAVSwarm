# 在线 0/8/30 秒验收结果：B 已修复（2026-10-12，集成侧）

**执行方：集成侧。** 起因：Runtime 侧报告"在线 0/8/30 秒复测尚待集成方完成" ——
他们那次在线验收没做成（首次启动 `PYTHONPATH` 被展开成主仓库 `src`，跑的是旧代码，
`/api/preflight` 返回 404）。本轮由我做，**系统现己全部停止**。

---

## 1. 被测版本

| | |
| --- | --- |
| 验收 worktree | `D:\2026UAVSwarm\.runtime\acceptance-88-92-fresh-20261011` |
| HEAD | `78ea4e2`（含 #88 `f4a51b8` 与 #92 `fbbad1d`） |
| 仿真配置 | `three_uav_mono_cam_sitl.json`（相机版） |
| 启动方式 | `MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA` + `--headless` |

---

## 2. ⭐ 结果：三个时点全部 `ready`

**发布一次证据，之后不再刷新任何东西** —— 那正是本条修复要证明的。

```
T=0s    preflight ready   reason_codes []   ground_context 可读   evidence_fresh=True  (age 154ms)
T=8s    preflight ready   reason_codes []   ground_context 可读   evidence_fresh=False (age 7258ms)
T=30s   preflight ready   reason_codes []   ground_context 可读   evidence_fresh=False (age 29349ms)
```

**它同时证明了两件相反的事**，这才是判据真正要的：

| | T=0 | T=8 | T=30 |
| --- | --- | --- | --- |
| **动态健康**（**该**过期） | `ready` | `unknown` ⏰ | `unknown` ⏰ |
| **静态几何**（**不该**过期） | ✅ 可读 | ✅ **可读** | ✅ **可读** |

**T=30 时动态健康已过期 29.3 秒，而 `ground_context` 依然可读。**

`simulation_health` 字段如实反映了这一点：

```json
T=0  {"status":"ready",   "evidence_fresh":true,  "age_ms":152,   "valid_for_ms":4893}
T=8  {"status":"unknown", "evidence_fresh":false, "age_ms":7256,  "reason":"simulation_evidence_stale"}
T=30 {"status":"unknown", "evidence_fresh":false, "age_ms":29347, "reason":"simulation_evidence_stale"}
```

---

## 3. 其余同时成立的项

| 项 | 值 | 评价 |
| --- | --- | --- |
| `execution_authorized` | `False` | ✅ 只读预检，仍不授权 |
| `flight_command_sent` | `False` | ✅ 无飞行副作用 |
| `home_evidence` | 三点都可读 | ✅ |
| 标定 | `calibrated`，age 5.5s → 12.6s → 34.7s | ✅（TTL 60s 内） |
| `run_id` | `6f7fb16a...` 三点一致 | ✅ 无跨 run 复用 |
| `world_sha256` | `9086de5bea22ae04...` | ✅ 与仓库一致 |
| RTF | `0.8732` | ✅ 高于门槛 0.20 |

**结论：`preflight` 的 `ready` 不再是"5 秒窗口"了 —— 手动测试的路通了。**

---

## 4. ⚠️ 过程中挖出并修掉一个真正的阻塞：验收 worktree 的 `.sh` 是 CRLF

### 症状（会误导）

```
simulation/px4_gazebo/scripts/start_three_uav.sh: line 2: set: pipefail
: invalid option name
```

第 2 行是 `set -euo pipefail`。**CRLF 让 bash 把选项名读成 `pipefail\r`**，
`set` 拒绝 → 脚本秒退 → **仿真完全起不来**。

### 实测字节对比

```
主仓库   : s e t   - e u o   p i p e f a i l \n          ✅
worktree : s e t   - e u o   p i p e f a i l **\r** \n   ❌   （CRLF 行 = 5/5）
```

CRLF 的脚本：`start_three_uav.sh`、`stop_three_uav.sh`。
（`.py` 也有 CRLF 但**无害** —— Python 处理 `\r\n` 正常。**只有 bash 脚本在此致命。**）

### ⚠️ 危险在于症状会骗人

```
仿真没起来
   → 标定 FAIL、health not_ready
   → preflight 的 reason_codes 里一堆 *_unavailable
   → **看起来像"B 没修好"**
```

**我第一版脚本超时后继续往下跑，差点就这么归因了。** 已修：仿真起不来就
**硬停并打印日志**，绝不继续。

### 修法

* **本会话已做**（可回退）：`tr -d '\r'`，只改行尾不改内容。
  转换后语法检查通过、worktree 的 `git status` **干净**（行尾转换未被 git 视为改动）。
* **根因修法**：仓库**没有 `.gitattributes`**。建议加

  ```
  *.sh text eol=lf
  ```

  否则**任何 Windows 侧的新 checkout 都会重现**，而它的症状又是"看起来像别的问题"。
  这属于仓库改动，留给负责人决定。

---

## 5. 本轮的操作边界（可复核）

* 未修改任何负责人分支的代码
* 只把验收 worktree 里两个 `.sh` 的**行尾**转为 LF（内容未变，`git status` 干净）
* **未发送任何飞行命令**（`flight_command_sent: False` 三点都成立）
* 未合并、未推送任何 PR
* 结束时系统全部停止（PX4 0 / Gazebo 0 / Runtime 0，端口全空）

---

## 6. 现在可以做什么

| | 事项 | 状态 |
| --- | --- | --- |
| 1 | **手动实飞验收**（UAV-02 起飞→保持→降落；01/03 全程 disarmed） | ✅ **路已通**，`preflight` 可稳定 ready |
| 2 | 验两个反例：**"靠近 HOME 但未到达"不能报成功**、**"屋顶落地"不能报成功** | ⏳ 待做（需实飞） |
| 3 | 合并顺序：**#92 → #88** | ⏳ 待实飞通过后 |
| 4 | 加 `.gitattributes`（`*.sh text eol=lf`） | ⏳ 建议，防复发 |

**注意：`execution_authorized` 始终为 `False` 是设计如此** —— 预检只读，
**不能把它的 `ready` 当成飞行许可**。
