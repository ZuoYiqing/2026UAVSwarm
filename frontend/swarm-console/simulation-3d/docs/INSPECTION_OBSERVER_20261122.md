# 设备巡检：预期航线、实测航迹和任务进度的观察验收

基线：`6a680feb6e50bdc7729e3ded6069cce6c0928dd3`；场景：`simple_recon_v0_1 / simple_recon_v0_1-map-1`。本次是内存测试桩，不运行执行器，不采集飞行数据，不证明巡检完成。

## 三种证据不能互相替代

| 问题 | 本轮数据和消费位置 | 不能由此得出什么 |
| --- | --- | --- |
| 计划经过哪里？ | [设备巡检只读样例](../tests/fixtures/equipment-inspection-observer.json) 是测试用的 context/proposal 字段摘录：按 assignment 的有序 waypoint ID 查 context 的 scene_ned 坐标。不是完整提案或可执行计划，不发给任何端点。 | 申请或批准了任务、飞机经过此处、已完成设备检查。 |
| 实际收到哪些位置？ | [公共快照测试桩](../tests/fixtures/public-snapshot.js) 代替 Runtime；生产路径是 [场景校验与投影](../src/scene-alignment.js)、[快照状态](../src/vehicle-snapshot-state.js)、[Cesium 实体与轨迹](../src/vehicle-layer.js)。`vehicle-route:<id>` 的语义是 `telemetry_trail`，不是计划航线。 | 两个稀疏位置样本之间的连续飞行、属于某一次任务、航点验证成功。 |
| 是否有执行或覆盖证据？ | 首页消费 `/api/mission/progress`。复用 [未执行响应](../../../../docs/fixtures/runtime_demo_readiness_v1.json) 和 [S7 合成覆盖报告](../../tests/fixtures/coverage_grid_s7_v1.json)，调用[首页数据模型](../../mission-dashboard.js)，不调用 HTTP。 | 三架在线、在航点附近或航点完成度 50% 均不能证明覆盖了 50% 的面积。没有覆盖报告是未知，不是零。 |

当前 iframe [父页消息处理器](../src/parent-bridge.js) 接受载具快照、模式与载具选择，没有计划航点或按任务绘制预期线的消息。现有 LIVE 航迹按载具而非 run 保存。**没有画预期线，不等于已经验证双线同屏。**

## 可复核断言

见 [inspection-observer.test.js](../tests/inspection-observer.test.js)。固定时钟，用真实 Cesium EntityCollection 读取 marker 和 polyline；图标 canvas 为桩，坐标读到 ENU 米，未验证浏览器像素、地图锚点或物理世界。

- 两个候选航点（按 N/E/D）是 (12,18,-5)、(20,18,-5)；提案不得作为完整车辆快照接受。计划/预测字段不能给缺公共位姿的载具补点。
- UAV-02 的可信 A 为 ENU (8,0,0)。过期 B 恰在第一个计划点，实体和航迹都留在 A；恢复后，新鲜 C 为 (9,3,2)，轨迹仅有 A、C。UAV-01/03 的轨迹各只有一个点。坐标、顺序和点数均作断言，不用肉眼判断。
- 对外场景或错误地图版本，冷启动不放置该节点，已有可信点不追加；仅刷新快照外层时间、保留过期的采样时间，也不能追加。
- 正对照：三架可见，UAV-02 两个新鲜位置甚至与两个候选航点完全重合。独立的进度响应仍是 `no_runtime_plan_execution` 时，首页模型没有任务进度、任务区域或覆盖层。
- 正对照：单独构造测试执行报告 1/2 航点（50%），没有覆盖证据则面积为未知。叠加同图版本的 S7 合成覆盖报告，才有对应网格；换成冲突版本则网格为未知。本用例只验证展示模型，不调用人工确认、Policy 或 Adapter。

## 两个已复现的缺口

| 负责人 | 测试桩复现（基线实际结果） | 转为通过的条件 |
| --- | --- | --- |
| 三维 | **第一帧**为已过期但带位置的 B。标记显示 STALE 是正确的；收到新鲜 C 时，实际航迹却为 [B,C]。新实体用第一个非空位置初始化了 trail，没有区别它是否新鲜。 | 可以展示最后已知标记 B，但不把 B 记入实测轨迹。恢复后只有 [C]。 |
| 主控台（与 Runtime 确认报表身份） | 构造任务和覆盖报告地图版本不同的输入：网格正确丢弃，但首页模型仍从顶层面积算出 15.115789…%。这是矛盾输入的诊断，不是本次发生过跨图覆盖。 | 同一任务没有可独立验证的同图面积证据时，百分比显示未知或明确不可用；不能以仅隐藏网格代替。 |

这两条是带断言体的 `test.todo`，在该基线实际运行并失败。Node 把它们计为 TODO，不计入 fail。修复后须移除 TODO 再验收。

## 下一次联合验收所需输入

1. 算法：给出一份针对这条非敏感设备巡检的、通过自身校验的候选样例，含任务/快照身份、分工、有序航点、明确的坐标系和地图版本；有歧义时给出澄清结果，不补点。
2. Runtime / 集成：给出人工确认、Policy 后产生的同一次 Fake Adapter 执行证据，以及拒绝/未执行的反例。应能关联候选与实际 `plan_id / mission_id / run_id`、节点、场景、地图版本、样本时间；不能假定提案任务 ID 等于 Runtime 的 mission ID。基线 [MissionProgress](../../../../src/uav_runtime/http/mission_progress.py) 使用 plan.plan_id 作为 mission_id。航点计数、覆盖采样、设备检查结果应分别举证。
3. 主控台 / 三维：协商只读计划预览入口。预期线（例如虚线、“计划/未执行”）与实测轨迹分层；候选过期、跨图时清除或拒绝预览。尚未执行的有效候选可以明确标成预览，但没有 run 关联时，不与当前执行进度或覆盖层合并。用两份不同输入及一次切换 run 验证不会沿用上一轮计划或 KPI。以上是验收条件，不是已发布的字段或能力。

## 复跑

在本 worktree 的 `frontend/swarm-console/simulation-3d` 下、有锁定依赖时：

```powershell
node --test tests/inspection-observer.test.js
$env:UAV_ALGO_REPO=(Resolve-Path '../../../algorithm_lab/mission_llm_poc').Path
npm test
npm run build
```

本轮专项 10 条：8 passed、0 skipped、2 TODO（断言未满足）；三维全套 90 条：88 passed、0 skipped、同样 2 TODO。`npm run build` 通过，有既有的大分包警告。首次构建遇到 Windows 系统临时文件删除权限错误；将当前进程的 `TEMP` 和 `TMP` 指向 worktree 内的忽略目录后重跑通过。未运行四模块、浏览器、SITL 或真实载具，未发送任何动作。集成线此前报告的 SITL 遥测通路不是本测试的执行证据。
