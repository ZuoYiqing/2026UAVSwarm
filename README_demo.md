# 2026UAVSwarm Demo Shell（录屏演示模式）

## 用途
这是一个用于**领导汇报 / 评审录屏**的轻量单页演示壳，核心展示链路：

`mission/action -> policy_decision_event -> adapter -> action_result -> replay`

> 说明：该页面用于演示控制面逻辑与状态流转，不等同于正式产品前端；当前不连接真实 PX4/MAVLink/SITL 后端。

## 快速运行
```bash
python -m http.server 8000
```

浏览器打开：`http://localhost:8000/demo/`

## 演示重点（中文主叙述）
- 顶部总览条：场景 / 任务 / 动作 / 适配器 / 后端 / 系统状态；
- 四个核心场景：
  1. 正常放行（ALLOW）
  2. 高风险拒绝（DENY）
  3. 等待确认（REQUIRE_CONFIRM）
  4. 接入位预留（SITL_WIRING）
- 时间线展示：从 mission_request 到 replay 的全链路事件可回放。

## 推荐录屏顺序（2~3 分钟）
1. 正常放行（ALLOW）
2. 高风险拒绝（DENY）
3. 等待确认（REQUIRE_CONFIRM）
4. 接入位预留（SITL_WIRING）
5. 自动演示（Auto Demo / Play All）作为收尾

详细讲稿请见：`docs/demo_video_script.md`
