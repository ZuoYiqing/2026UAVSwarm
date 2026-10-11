# 合并前核查：PR #91 / #92 / #88（集成侧，2026-10-09）

**结论：不建议现在合并。** 代码方向对，但**有一处实际测试失败**，而且负责人说还在继续做。
本文只做核查与记录，**没有修改任何代码、没有合并任何分支**。

---

## 1. 三条分支的位置（实测）

| 分支 | HEAD | 领先 main | 落后 main |
| --- | --- | --- | --- |
| `origin/main` | `22b2158` | — | — |
| `codex/runtime-return-home-land`（PR #88） | `1d13019` | 6 | **16** |
| `codex/simulation-ground-reference-evidence`（PR #92） | `7c3a026` | 1 | 0 |
| `codex/algorithm-lab-local-llm-poc`（PR #91） | `4a42f2d` | 1 | 0 |

三个报告的提交（`f1d2e76` / `1d13019` / `7c3a026`）**都存在**，报告内容属实。

---

## 2. ⚠️ 发现一处实际测试失败（PR #92）

```
$ python -m pytest tests/unit/test_three_uav_health.py -q     # 在 7c3a026 上
1 failed, 22 passed

FAILED test_integrated_health_publishes_only_known_ground_collision_geometry

  assert {'world_sha256': '9086de5bea22ae04...'} == {'world_sha256': 'fa125d95963236b0...'}
```

**根因**：该 PR 自带的 fixture 里 `world_sha256` 与仓库里的实际 world 文件不符。

```
fixture:  docs/simulation/fixtures/ground_reference_simple_recon_v0_1.json
          → "world_sha256": "fa125d95963236b04bdd7b1eecf63083922dd73938b38424ade642b89efd315e"

实际文件: scenarios/simple_recon_v0_1/worlds/simple_recon_v0_1.sdf
          → sha256 = 9086de5bea22ae0470fe76f6b06cf9e73b6ac9bdf96477c2171ae304a7b575fa

（全仓只有一个 .sdf 匹配这两个哈希前缀 —— 即那个 world 本身）
```

**这条失败恰好是它要防的那类错误**：`world_sha256` 是这个 PR 用来锚定
"证据对应哪个 world" 的字段，而 fixture 里的值与实际 world 不匹配。
（`git log` 显示该 world 最近被 `bb110fe` 改过 —— 它扩展了地面以覆盖导入的城市。）

**所以"68 个相关单元测试通过"至少这一条对不上。** 需要 Simulation 侧确认：
是 fixture 该更新，还是他们的 test 运行状态与推送的提交不一致。

---

## 3. 接线是完整的（不是"换了样子的死锁"）

这是本次核查最要紧的一条结论。我担心 PR #88 会需要一份没人提供的地面参考，
于是追了完整链路：

```
PR #92  simulation/px4_gazebo/health.py:529
            runtime_evidence["ground_reference"] = reference          ← 发布方（Simulation）

PR #88  src/uav_runtime/http/state_store.py:633
            reference = evidence.get("ground_reference")              ← 消费方（Runtime）

PR #88  src/uav_runtime/http/routes.py:564
            "ground_reference": reference
        src/uav_runtime/http/routes.py:600
            reason = "ground_reference_unavailable" if landing_context is None
                     else "ground_reference_changed_or_stale"         ← 缺失/失配时明确报因
```

**两个 PR 各占一半，必须一起才成立。**

> ⚠️ **因此合并顺序不能反**：若只合 PR #88 而不合 #92，`ground_reference` 永远拿不到，
> 退货成"**换了个样子的死锁**"（从缺站点证据变成缺地面参考）。
> **#92 必须先于 #88 合入。**

运行时还需要证据真的被发布（`/api/simulation/evidence` 收到 integrated health），
否则 `landing_context` 为 `None`、报 `ground_reference_unavailable`。
**那是运维步骤，不是代码缺口。**

---

## 4. 剩下几件需要确认的事

| # | 事项 | 谁 |
| --- | --- | --- |
| 1 | fixture 的 `world_sha256` 与实际 world 不符 | Simulation |
| 2 | PR #88 落后 main **16 个提交**，需在其上重跑全量（报告说 829 passed，但那是它自己的基线） | Runtime |
| 3 | PR #88 改了 `tests/integration/test_four_module_e2e_acceptance.py` —— **主责在集成侧**，合并前我要看那处断言改动 | 集成 |
| 4 | PR #91 的 `landing_assessment_lab` 是**离线**基线，不冒充在线感知 —— 这个边界写得对，但要确认它没有被接成运行时判据 | Algorithm |
| 5 | 真实 UAV-02 起飞—保持→降落 + UAV-01/03 隔离的联合验收 | 集成（需系统启动） |

---

## 5. 我在本次核查中的操作（可复核）

* 只做 `git fetch` / `git log` / `git show` / `git grep`
* 为跑测试做了两次 `git checkout --detach` + 回到 `main`；**未修改任何文件**
* 两次 `git stash push/pop` 仅针对 `audit/runtime.audit.jsonl`（Runtime 一直在写的运行产物）
* **没有合并、没有推送、没有改动任何负责人分支**
* 系统当前**全部停止**（用户要求），所以未做任何飞行或联调

---

## 6. 建议的下一步顺序

```
1. Simulation 修 fixture 的 world_sha256（或说明为何两者应当不同）
2. #92 合并 → main
3. #88 在最新 main 上重跑全量（含集成侧那处断言）
4. #88 合并
5. 启动系统 → 发布 integrated health（含 ground_reference）→ 联合实飞验收
6. #91 是离线基线，与运行时解耦，可独立合
```
