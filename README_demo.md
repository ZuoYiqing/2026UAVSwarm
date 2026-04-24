# 2026UAVSwarm Demo Shell (Recording Mode)

## 用途
用于领导汇报/录屏演示的轻量单页壳，重点展示：
`mission/action -> policy_decision_event -> adapter -> action_result -> replay`

> 不是正式产品前端；不连接真实 PX4/MAVLink/SITL。

## 快速运行
```bash
python -m http.server 8000
```
打开：`http://localhost:8000/demo/`

## 推荐录屏顺序（2~3 分钟）
1. ALLOW
2. DENY
3. REQUIRE_CONFIRM
4. SITL_WIRING
5. Auto Demo / Play All 自动轮播收尾

详细讲稿见：`docs/demo_video_script.md`
