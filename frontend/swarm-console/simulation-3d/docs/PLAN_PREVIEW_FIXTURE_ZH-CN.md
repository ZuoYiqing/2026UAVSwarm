# Fake 计划预览：三维接收端

基线 `f91e4f9d2cd142f560852db0ee310414ef3d28a7`（轨迹修复），叠加在 PR #111 的 `2d01ffc` 上。本入口仅供联调用 Fake 候选展示，不引入 Runtime 接口或执行能力。

## 父页与 iframe

- 主控台只从通过校验的 Fake 候选提取有序 GOTO 航点；模板预览、Lab 候选、进度或历史记录都不是来源。两边使用同一[计划夹具](../../tests/fixtures/equipment-inspection-lifecycle.json)里的 `fake-target-001-patrol-v1`。
- 仅测试桩父页的三维集群态势 iframe 带 `?planPreview=fixture`。独立页、大屏和普通主控台 iframe 不开此入口。测试 iframe 的三维动作控件隐藏，执行处理函数也不接受操作。
- 复用现有 `uav-swarm/simulation-ready` / 窗口和 origin 校验。计划先到时等当前 iframe ready，ready 先到时等当前候选校验成功。重新加载时只由父页重发原消息，不缓存或从遥测恢复。

消息 `type: "uav-swarm/plan-preview"` 的 `payload` 是 `null`（清除），或：

| 字段 | 来源与规则 |
| --- | --- |
| `version` | 此次测试消息为 `"1.0"`，不改变载具快照契约 |
| `plan_id`, `scene_id`, `map_version` | 已校验 Fake 计划身份，场景和地图版本须与三维当前参考面匹配 |
| `frame` | 只接受 `scene_ned`，米、Down 为正 |
| `expires_at_ms` | 父页校验成功时计算的绝对 Unix 毫秒截止时间，展示 TTL 暂用 60 秒，重发不续期 |
| `waypoints` | 原顺序的 GOTO 点，包含唯一 `step_id`、`node_id`、有限数值 `north_m/east_m/down_m` |

三维按载具分组，按 `(East, North, -Down)` 投影，不重新求路径或加入起点。橙色虚线与空心点标作「计划预览 · 测试桩」，不替换 `telemetry_trail`。可信父页发来的空消息、非法格式、跨图或过期消息撤下计划层；其他窗口和来源的消息直接忽略。切换离开任务场景或进入 DEMO 也撤下计划层。计划层不消费 `run_id`、覆盖或 OBSERVE，不能据此推出飞行或巡检完成。

## 离线复跑

在三维子项目用锁定依赖运行。Playwright 探针使用已安装的 Edge（`PLAYWRIGHT_CHANNEL` 可改），所有请求由本地拦截履行，不启动 5178/5179 HTTP 监听或 Runtime。其父页是合成发送器，区别于实际主控台发送端联验。

```powershell
node --test tests/plan-preview-layer.test.js tests/inspection-observer.test.js
$env:UAV_ALGO_REPO=(Resolve-Path '../../../algorithm_lab/mission_llm_poc').Path
npm test
npm run build
node tests/plan-preview-browser.mjs
```

三维全套 97 项通过、0 失败、0 跳过；构建通过，有既有大分包警告。接收端浏览器探针在 1366×900 先推计划、390×844 先推遥测，两组均通过。截图验证虚线像素不来自空心航点，结果保存在本地 `test-results/plan-preview-*.png`，不入 Git。错图和清空不改实测历史，重载后原截止时间不变，常规 iframe 不收计划。所有浏览器请求被本地拦截，接收端未产生 API 请求。
