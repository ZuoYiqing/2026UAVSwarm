# 观察复核（L2）记录规格 v0.1

**日期**：2026-10-05
**状态**：**规格 + 校验器已实现。存储与运行时的接入尚未实现**（见第 5 节）。
**相关**：
`docs/OBSERVE_interface_requirements_draft.md`（L1/L2 分层与相机依据）、
`docs/algorithm_runtime_execution_contract_v0_1.md` 3.1.2（超时分类）

---

## 0. 这份文件解决什么问题

三机相机回归之后，`CAPTURE`（L1 采集）随时可能接通。**但采集通了不等于"观察到了目标"** ——
那是 L2，需要判定。三方已对齐的边界是：

> `CAPTURE` 是 L1 执行动作，`pass` 只表示**真实图像采集及关联证据满足要求**，
> **不能**把 `OBSERVE`、巡检步骤或原任务自动标记为 completed。

算法负责人给出的 L2 可接受形式是**人工复核**，并列出至少要记录的字段。
本文件把那组字段**固化成可校验的记录格式**，并实现校验器。

**为什么需要校验器而不是"写文档让大家照着填"**：这条链路上最容易出的事，是
**把"没看到"当成"不存在"**、或者**给人工判断补一个编造的置信度**。文档拦不住这些，
校验器能。

---

## 1. 记录格式

```json
{
  "review_version": "0.1",
  "review_id": "rev-<16 hex>",
  "created_at": "2026-10-05T12:00:00Z",

  "task_id": "TASK-1",
  "target_id": "target-001",
  "capture_id": "cap-<16 hex>",

  "image": {
    "ref": "sha256:3f2a...",
    "sha256": "3f2a...",
    "width": 1280,
    "height": 960,
    "encoding": "RGB8",
    "captured_at": "2026-10-05T11:59:30Z",
    "vehicle_id": "UAV-01",
    "camera_id": "front_rgb"
  },

  "criterion_version": "l2-criterion-v0.1",
  "reviewer": "human:<标识>",
  "reviewed_at": "2026-10-05T12:00:00Z",
  "outcome": "observed",

  "confidence": null,
  "region": { "x": 512, "y": 384, "w": 256, "h": 192 },
  "note": "目标位于画面中央偏右，可见其侧面轮廓。",

  "linked_task_completion": "not_asserted"
}
```

### 字段说明与理由

| 字段 | 必填 | 理由 |
| --- | --- | --- |
| `review_id` | ✅ | 复核自身的标识。**与 `capture_id` 分开**：一次采集可以被多次复核，结论也可能不同 |
| `task_id` / `target_id` | ✅ | 说明这次复核服务的是哪个任务与目标 |
| `capture_id` | ✅ | 与 L1 的显式关联。没有它就不知道复核的是哪一次采集 |
| `image.ref` + `image.sha256` | ✅ | **不可变图像引用**。哈希必须与 `ref` 一致，否则拒绝 |
| `criterion_version` | ✅ | 判据版本。**判据变了结论可能变**，所以必须记录用的是哪一版 |
| `reviewer` | ✅ | 必须以 `human:` 开头 —— **本阶段 L2 只接受人工复核**（见第 2 节） |
| `reviewed_at` | ✅ | 判定时间 |
| `outcome` | ✅ | `observed` / `not_observed` / `undetermined` |
| `confidence` | ✅ | **必须是 `null`**（见第 2 节） |
| `region` / `note` | 二选一 | 支持结论的图像区域或文字说明。**`undetermined` 也必须给**，说明为什么判不了 |
| `linked_task_completion` | ✅ | 固定为 `not_asserted`（见第 3 节） |

---

## 2. 三条由校验器强制的规则

### 规则一：不得编造数值置信度

**`confidence` 必须为 `null`。** 给一个 0–1 的数字，会被下游当成"模型的输出概率"，
而它实际是**某个人的主观印象** —— 那是把一个判断伪装成一种测量。

算法负责人原话：

> 人工结论**不伪造数值置信度**；`not_observed` 只表示"在这份图像中未按判据看到"，
> **不证明真实场景中目标不存在**。

### 规则二：`reviewer` 必须是 `human:`

本阶段 L2 **只接受人工复核**。校验器拒绝任何非 `human:` 开头的 reviewer
（例如 `detector:`、`auto:`），理由是：

> 本阶段不做自动 L2。**仿真真值只能用于离线标注与评价，不得写入运行时检测或冒充检测结果。**

若将来接入离线检测器，它应当是**另一个** `reviewer` 类型，并且**先经过离线评测**
（用真值当标签、报告准确率），而不是直接写进复核记录。

### 规则三：`not_observed` 必须给出依据

`outcome = "not_observed"` 时**必须**有 `region` 或 `note`。理由同上：

> `not_observed` 只表示"**在这份图像中**未按判据看到"，不证明目标不存在。

没有依据的 `not_observed` 与"检测器没报"无法区分 —— 而后者**不能**作为结论。

---

## 3. 为什么不自动完成任务

`linked_task_completion` 固定为 `"not_asserted"`。这是把三方共识**写进数据结构**：

> `CAPTURE` 成功不能自动完成 `OBSERVE`、巡检步骤或原任务。

算法负责人还指出，一旦替换动作枚举就把原任务报为完成，**不能通过枚举替换把语义迁移伪装过去**。
因此这里不是靠"大家记得不要那么做"，而是**记录里根本没有"已完成"这个取值**。

**要表达任务完成，需要另一个显式动作**（尚未设计）—— 它必须同时引用
`capture_id` 与 `review_id`，并有自己的授权路径。

---

## 4. 存储决定（设计决定 ①）

**决定：复核记录以内容寻址的 JSON 文件保存，不由 Runtime 管理。**

理由：

1. **Runtime 侧明确冻结**：agent runtime 负责人声明「当前不启动服务、不修改代码、不冻结接口」，
   且图像执行能力 `fail closed`。现在要求 Runtime 新增实体与路由，会与那个边界冲突。
2. **L2 不是控制面动作**：它**不指挥任何载具**。把它建模成一个 Runtime action 会让
   "CAPTURE 成功"和"复核完成"在同一个生命周期里，**正是三方要求分开的东西**。
3. **与既有惯例一致**：本项目的证据都是文件 + 哈希（标定证据、快照 fixture、审计 JSONL）。

**存储位置**：`artifacts/observations/reviews/<review_id>-<内容哈希前16位>.json`
（`artifacts/` 已被 Git 忽略，与算法侧的 `artifacts/runs/` 同惯例。）
文件名带内容哈希，因此**记录被改动过**时文件名与实际内容会不一致 ——
`scripts/observe_review.py validate` 会以退出码 2 指出这一点。

**已知的不便**：文件存储下，前端跨会话查询要靠后端提供列表接口 —— 而 Runtime 现在不接。
因此**本阶段的界面支持"新建并导出"与"导入并校验"，不做跨会话检索，也不假装能做**。

**将来若要改由 Runtime 管理**：需要 Runtime 新增 `review` 实体与路由，并明确它与
`capture` 的关联由谁校验。**这不是必须的**，取决于是否需要多操作者共享与集中审计。

---

## 4b. 界面决定（设计决定 ②）

**决定：在控制台新增一页「观察复核」（导航 `OR`），不放进 3D 视图、也不塞进现有页面。**

理由：

1. **它是一条独立的生命周期**。三方要求 CAPTURE / 图像证据 / OBSERVE-复核 / 上层任务完成
   四者**显式关联但不能互相越级**。塞进仿真中心或 Runtime 页会让它们在界面上也糊在一起。
2. **它不依赖三维态势**。复核看的是图像与元数据，不是空间关系；放 3D 视图里反而要求
   先有场景与载具数据。
3. **它必须能独立显示"本阶段不能当验收证据"**。独立页面才有位置放这句提示。

**界面刻意不提供的**：

| 不提供 | 理由 |
| --- | --- |
| 置信度输入框 | 人工结论不伪造数值置信度 —— 界面上就不该给它入口 |
| "标记任务完成"按钮 | 复核记录**无从表达**任务完成（见第 3 节） |
| 自动结论 | 本阶段不做自动 L2 |

---

## 5. 当前边界（**不要误读为已接通**）

| | 状态 |
| --- | --- |
| 记录格式与校验器 | ✅ 已实现。Python 47 例 + JS 37 例测试，另有真实浏览器验证 15 项 |
| 记录工具（新建/校验/列出） | ✅ `scripts/observe_review.py`，实证通过 |
| 控制台「观察复核」页面 | ✅ 已实现（新建/校验/导入/导出 JSON） |
| **`CAPTURE` 端点** | ❌ **未实现**（等三机飞行与 integrated 验收；`camera_not_validated` 有效） |
| **与真实 `capture_id` 的自动关联** | ❌ **未实现** —— 现在靠人工填写，因此**可能填错** |
| 跨会话检索 | ❌ 未实现（见第 4 节末尾） |

**最后一条要特别说清**：现在没有 L1 端点，所以 `capture_id` 与 `image.sha256`
**都靠人工录入，没有任何东西能证明它们真的对应某次采集**。校验器只能保证
**格式与哈希自洽**（`ref` 与 `sha256` 一致），**不能保证它们来自真实采集**。

> 也就是说：**当前这套东西能防止"编造置信度"和"无依据的 not_observed"，
> 但防不住"整条记录都是编的"。** 等 `CAPTURE` 端点接通、`capture_id` 由 Runtime 签发后，
> 这一点才会成立。**在那之前，这些记录只能当流程演练，不能当验收证据。**

---

## 5b. 两份实现必须同步（**这是当前的已知风险**）

前端是静态页面（无构建步骤），**不能 import Python**，因此校验规则在两端各写了一次：

| 位置 | 用途 |
| --- | --- |
| `src/uav_runtime/observation/review_record.py` | 权威实现：写文件、命令行、供 Runtime 使用 |
| `frontend/swarm-console/console-model.js` | 对照实现：界面即时校验，离线可用 |

**风险**：两份实现会漂移。若前端放行、后端拒绝，操作者会看到"界面说没问题、
脚本说不行"，而这种分歧看起来像 bug。

**当前的缓解**：

* 两边的测试**逐条对应**（`tests/unit/test_observation_review_record.py` ↔
  `frontend/swarm-console/tests/observation-review.test.js`），
  违规码字符串相同，并有测试断言码名一致。
* **`review_id` 两端不同是刻意的**：前端没有同步的密码学哈希（WebCrypto 是异步的），
  它用一个非加密摘要生成 id，只用于本地预览与导出。
  **以 Python 侧写的文件为准。**

**没有解决的**：没有自动比对两份实现的机制。若要长期维护，
应考虑把校验规则抽成一个共享的数据文件（如 JSON Schema），两端都从它派生。

---

## 5c. 实现过程中抓到的两个洞（留档，因为都是"共用的盲区"）

1. **`capture_id: ""` 被放行。** 必填检查只查"键在不在"，空字符串算通过 ——
   而一个空的 `capture_id` 没有任何东西能把它关联到某次采集，恰好废掉这个字段的意义。
   现在标识类字段必须是非空字符串（违规码 `empty_identity_field`）。
   **这个洞是在前端 JS 实现里先被测试抓到的，Python 侧当时有同样的洞** ——
   两端共用一个盲区，正是"两份实现要同步"这条约定的价值所在。
2. **副标题里的 markdown 星号原样显示。** 我写了 `**人工**`，而 `pageTitle()` 用
   `esc()` 输出纯文本，星号直接显示在页面上。**单元测试抓不到**（HTML 里确实有那句话），
   是**真实浏览器截图**时看见的。已修，并加了一条测试扫描所有 `pageTitle` 参数。

> 第 2 个洞印证了本项目已有的一条教训：**"测试全绿"不等于"界面可用"**
> （此前 `ensureShell()` 破坏 CSS Grid 布局那次也是同一类）。

---

## 6. 相关文件

| 用途 | 位置 |
| --- | --- |
| L1/L2 分层、相机依据、三方边界 | `docs/OBSERVE_interface_requirements_draft.md` |
| 执行契约（3.1 动作、3.1.2 超时分类） | `docs/algorithm_runtime_execution_contract_v0_1.md` |
| 校验器与记录工具（权威实现） | `src/uav_runtime/observation/review_record.py` |
| 命令行工具 | `scripts/observe_review.py` |
| Python 侧测试（47 例） | `tests/unit/test_observation_review_record.py` |
| 前端对照实现 | `frontend/swarm-console/console-model.js`（`validateObservationReview`） |
| 前端校验测试（21 例） | `frontend/swarm-console/tests/observation-review.test.js` |
| 页面测试（18 例） | `frontend/swarm-console/tests/observation-page.test.js` |
| 控制台页面 | `frontend/swarm-console/app.js`（`observationPage`） |
