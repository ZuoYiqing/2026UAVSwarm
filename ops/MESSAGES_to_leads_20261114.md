# 四段可直接粘贴的消息（2026-11-14）

> 总任务书 `PROMPTS_to_leads_FINAL_20261113.md` 太长，发群没人看完。
> 这里是四段**可直接复制粘贴**的短消息，每人一段，细节指向文档。

---

## 给 Runtime 负责人

> r2 我这边独立核验过了，**结论是通过**：9 处冲突解法正确（`matched_source` 没丢、
> demo 的 `127.0.0.1` 限制在、`simulated` 贯通 5 个文件）。
> 特别说一句：`main()` 用 `ExitStack` 按逆序注册清理，比我建议的 `finally` 手写更稳，这个写法留着。
>
> 剩下的活：
>
> **① 把 #101 合进 r2 然后打 tag**（最后一步，我预演过：干净合并、1083 绿）
> ```bash
> git checkout integration/demo-20261113-r2
> git merge --no-ff 7b9d42c -m "integration: merge #101 (frontend F-C) into r2"
> PYTHONPATH=src python3 -m pytest -q          # 期望 1083 passed / 12 skipped
> git push
> git tag -a demo-20261113-r2 -m "demo r2: three demo lines + #97 + #101"
> git push origin demo-20261113-r2
> ```
>
> **② 答复 4 个算法接口问题**（不用写代码，勾 4 个选项，5 分钟）
> 见 `ops/PROMPT_to_runtime_intelligence_answers_20261114.md`
> 这份需求从 9-24 挂到今天没答复，算法线因此完全停着。**Q1 最关键**：
> `objective`（自然语言）和 `tasks[]`（结构化）谁权威 —— 现在反了，模型没有生成任务的权限。
>
> **③ 清临时目录**：你实查 78 个 `.tmp_runtime_*`，我之前数的是 69，**以你的为准**。
> ```bash
> git clean -fdn -- '.tmp_runtime_*'   # 先 dry-run
> git clean -fd  -- '.tmp_runtime_*'
> ```
>
> 谢谢你没动 `main` 和旧标签，这个边界守得对。

---

## 给【前端】负责人

> #101 收到了，**F-C 做得对**：我核了 `app.js` 里「航点完成度」和「面积覆盖率」两个指标都在，
> 而且你没有把缺面积证据的情况伪造成数字（仍标"覆盖未知"），这个处理是对的。
>
> 我预演了 `#101` 合进 r2：**干净合并 + 1083 passed**，等 Runtime 合完就打 `demo-20261113-r2`。
>
> 你这一轮剩下的：
>
> **① 等 r2 定版**（不用你动手，Runtime 会合）
>
> **② F-B 覆盖分布上图 —— 等仿真 S7 的数据**，我已让仿真开始做，
> 并要求他给：可选字段、坐标系说明、网格粒度 10~50 m。
> 他给了你再用，**没给就保持"未知"，不要用假数据填**。
>
> **③ 第二阶段你基本收尾了**，LIVE 三机验收留到第三阶段（weier）。
>
> 一个小提醒：`mission-dashboard.js` 现在 319 行，F-B 加进去可能会变大，
> 如果拆成子模块记得同步 `index.html` 的 script 顺序。

---

## 给【仿真】负责人

> 你的判断全对：S7 就是"把已记录的网格作为可选字段交出去"，S5/S6 留 weier 现场。
> **现在开始做 S7。**
>
> 但有三个约束必须满足，否则前端画不上、或者传输会炸：
>
> **① 必须是可选字段**（缺省不返回或返回 `null`）
> 不能破坏现有 `/api/mission/progress` 的契约 —— r2 的 1083 个测试依赖它。
>
> **② 网格必须带坐标系说明**
> NED 还是 ENU？相对哪个原点？是相对 `scenarios/*/scene.json` 的锚点，还是 PX4 HOME？
> 不写清楚前端无法把网格叠到三维场景上。
>
> **③ 粒度要控制**
> 8 km² 如果按 1 m 网格是 **800 万个点**，JSON 传输直接炸。
> 建议 **10~50 m 网格**（8 km² / 20 m ≈ 2 万个格子，可接受）。
> 如果精度不够，可以只回**已覆盖的格子列表**（稀疏表示），不要回全量矩阵。
>
> 交付形式建议：先给 Runtime 一个函数 + 一份样例 JSON，让他决定暴露成哪个字段。
>
> 另外提醒：S7 不进 `demo-20261113-r2`（r2 已定型），**单独作为 r3 的增量**。
> 所以不用赶，但要保证不破坏现有契约。

---

## 给【算法】负责人

> 三件事：
>
> **① 你的两份 handoff 文档我帮你提交进 git 了**（提交 `5eff9f2`）
> ```
> algorithm_lab/INTELLIGENCE_HANDOFF/01_runtime_interface_requirements.md
> algorithm_lab/INTELLIGENCE_HANDOFF/02_intelligence_problem_definition.md
> ```
> 它们之前是 `??` 未跟踪状态，一次误 `clean` 就没了。**这是整条算法线的需求基线，比代码值钱。**
> 以后改这两份走正常 PR，不要再留 untracked。
>
> **② 你的接口需求已正式转给 Runtime 负责人**
> 见 `ops/PROMPT_to_runtime_intelligence_answers_20261114.md`，4 个问题都附了建议答案让他勾选。
> 尤其 **Q1（objective vs tasks 谁权威）**，那是指出架构倒置的那一条，我建议他分阶段放开。
> **他答完你才能排期。** 这件事挂了一个多月，我催他本周内答。
>
> **③ 两个分支建议这样处置**
>
> | 分支 | 规模 | 建议 |
> |---|---|---|
> | `codex/algorithm-lab-local-llm-poc` `4a42f2d` | 13 files，**落后 main 54 提交** | 打 `archive/` tag 后**删分支**（落后太多，8-11 月 main 结构变了，已经没有合并价值） |
> | `codex/algorithm-uav02-local-candidate` `0ff77c1` | 19 files +1746，落后 27 | 打 `archive/` tag **保留**（模型候选服务实现，将来要用） |
>
> ```bash
> git tag archive/algorithm-llm-poc-20261010  4a42f2d
> git tag archive/algorithm-uav02-20261030   0ff77c1
> git push origin --tags
> ```
> 删分支我可以做，但**要你确认 `4a42f2d` 里没有你还想要的东西**
> （它只有 1 个提交：`feat(algorithm): add offline landing evidence baseline`）。
>
> **④ 关于这次演示：不含算法，话术我写好了**
>
> > "算法这块我们做了问题定义和接口契约，也验证了模型候选服务能被 Runtime 调用
> > （12/12 任务步骤候选及时有效）。但真正的智能算法还没开始 ——
> > 我们刻意先把契约和边界冻住，避免做完发现接不上。
> > 现在有一份接口需求在等 Runtime 答复，答完就进入实现阶段。"
>
> **当前唯一能交付给演示的东西**：模型候选服务的**调用证据**
> （`docs/runtime_local_model_verification_20261029.md` + `scripts/verify_local_model_runtime.py`）。
> 这条可以作为"链路已打通"的证据，**但不能当作"算法能力"**。
>
> **⑤ 下一个该做的是什么（等 Q1 有答复后）**
> 建议从**问题 A 语义锚定**起步 —— 五个智能问题里它最独立、最容易做出可见效果，
> 而且不依赖几何求解。详见你自己写的 `02_intelligence_problem_definition.md` 第 4 节。

---

## 附：给所有人一句（如果只发一条）

> 三条 demo 线 + #97 已合成 `demo-20261113-r2`（1083 测试全绿），
> 只差把 #101 合进去就定版。详细任务见 `ops/PROMPTS_to_leads_FINAL_20261113.md`，
> 每人一节，只看自己那节就行。
